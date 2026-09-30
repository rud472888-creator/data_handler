"""Backend gating/glue (fake mlx_vlm module), install registration, CLI and smoke harness (mock backend)."""
from __future__ import annotations

import json
import sys
import types

import pytest

from orchestrator import cli
from orchestrator.visual_qa import backend as backend_module, settings
from orchestrator.visual_qa.backend import BackendPoisoned, BackendUnavailable, InferenceError, MlxVlmBackend

from visual_qa_helpers import CLEAN_JSON, make_run


def test_mlx_backend_is_blocked_off_apple_silicon_with_a_concrete_reason(monkeypatch):
    monkeypatch.setattr(backend_module.platform, "system", lambda: "Linux")
    monkeypatch.setattr(backend_module.platform, "machine", lambda: "x86_64")
    with pytest.raises(BackendUnavailable) as excinfo:
        MlxVlmBackend().check_ready()
    assert excinfo.value.code == "unsupported_platform"


@pytest.fixture
def apple(monkeypatch, tmp_path):
    monkeypatch.setattr(backend_module.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(backend_module.platform, "machine", lambda: "arm64")
    monkeypatch.setenv("DATA_HANDLER_VISUAL_QA_HOME", str(tmp_path / "qa-home"))
    return tmp_path / "qa-home" / "models"


def test_mlx_backend_needs_an_installed_matching_model(apple, monkeypatch):
    with pytest.raises(BackendUnavailable) as excinfo:
        MlxVlmBackend().check_ready()
    assert excinfo.value.code == "model_not_installed"
    apple.mkdir(parents=True)
    (apple / settings.MODEL_MANIFEST).write_text(json.dumps({"local_path": str(apple / "missing"), "original_model_id": "Qwen/Qwen3.5-4B"}))
    with pytest.raises(BackendUnavailable) as excinfo:
        MlxVlmBackend().check_ready()
    assert excinfo.value.code == "model_missing"
    (apple / "w").mkdir()
    (apple / settings.MODEL_MANIFEST).write_text(json.dumps({"local_path": str(apple / "w"), "original_model_id": "Other/Model"}))
    with pytest.raises(BackendUnavailable) as excinfo:
        MlxVlmBackend().check_ready()
    assert excinfo.value.code == "model_mismatch"


def install_fake_mlx(monkeypatch, generate):
    fake = types.ModuleType("mlx_vlm")
    fake.load = lambda path: ("MODEL", "PROCESSOR")
    fake.apply_chat_template = lambda processor, config, messages, num_images, enable_thinking: (
        f"{messages[1]['content']}|images={num_images}|<think>\n\n</think>\n\n" if enable_thinking is False else "thinking on")
    fake.generate = generate
    utils = types.ModuleType("mlx_vlm.utils")
    utils.load_config = lambda path: {"model_type": "qwen3_5"}
    monkeypatch.setitem(sys.modules, "mlx_vlm", fake)
    monkeypatch.setitem(sys.modules, "mlx_vlm.utils", utils)


def ready_backend(apple, monkeypatch, generate):
    (apple / "w").mkdir(parents=True, exist_ok=True)
    (apple / "w" / "config.json").write_text("{}")
    (apple / "w" / "model.safetensors").write_bytes(b"test weights")
    (apple / settings.MODEL_MANIFEST).write_text(json.dumps({
        "local_path": str(apple / "w"), "original_model_id": "Qwen/Qwen3.5-4B", "source_repo": "Qwen/Qwen3.5-4B",
        "revision": "abc123", "quantization": None}))
    install_fake_mlx(monkeypatch, generate)
    backend = MlxVlmBackend()
    backend.check_ready()
    return backend


def test_mlx_glue_passes_pil_images_single_turn_thinking_off_and_records_versions(apple, monkeypatch):
    Image = pytest.importorskip("PIL.Image")
    seen = {}

    def generate(model, processor, prompt, image, max_tokens, temperature, verbose, enable_thinking):
        seen.update(prompt=prompt, image=image, max_tokens=max_tokens, temperature=temperature, thinking=enable_thinking)
        return types.SimpleNamespace(text=CLEAN_JSON, finish_reason="stop", prompt_tokens=10, generation_tokens=5, peak_memory=2.5)

    backend = ready_backend(apple, monkeypatch, generate)
    image = Image.new("RGB", (64, 32), (1, 2, 3))
    result = backend.infer([image], "sys", "user question", max_new_tokens=99, timeout_s=5)
    assert seen["image"] == [image] and seen["thinking"] is False and seen["temperature"] == 0.0 and seen["max_tokens"] == 99
    assert "images=1" in seen["prompt"]
    assert result.text == CLEAN_JSON and result.peak_memory_bytes == 2_500_000_000
    description = backend.describe()
    assert description["revision"] == "abc123" and description["original_model_id"] == "Qwen/Qwen3.5-4B"
    assert description["thinking_check"]["empty_think_block_present"] is True and description["is_mock"] is False


def test_weight_content_changes_model_fingerprint(apple, monkeypatch):
    from orchestrator.visual_qa.runner import model_fingerprint
    backend = ready_backend(apple, monkeypatch, lambda *a, **k: None)
    first = model_fingerprint(backend.describe())
    (apple / "w" / "model.safetensors").write_bytes(b"different weights")
    changed = MlxVlmBackend()
    changed.check_ready()
    assert changed.describe()["weights_identity"] != backend.describe()["weights_identity"]
    assert model_fingerprint(changed.describe()) != first


def test_mlx_errors_are_classified_and_timeouts_poison_the_backend(apple, monkeypatch):
    Image = pytest.importorskip("PIL.Image")
    image = Image.new("RGB", (8, 8))

    def oom(*a, **k):
        raise RuntimeError("[metal::malloc] out of memory")

    backend = ready_backend(apple, monkeypatch, oom)
    with pytest.raises(InferenceError) as excinfo:
        backend.infer([image], "s", "u", max_new_tokens=8, timeout_s=5)
    assert excinfo.value.kind == "out_of_memory"

    import threading

    release = threading.Event()
    slow = ready_backend_slow = None
    install_fake_mlx(monkeypatch, lambda *a, **k: release.wait(5) or types.SimpleNamespace(text="x"))
    backend2 = MlxVlmBackend()
    backend2._install = backend._install
    with pytest.raises(BackendPoisoned):
        backend2.infer([image], "s", "u", max_new_tokens=8, timeout_s=0.1)
    with pytest.raises(BackendPoisoned):
        backend2.infer([image], "s", "u", max_new_tokens=8, timeout_s=0.1)
    release.set()


def test_install_registers_local_weights_offline_and_rejects_unlabelled_derivatives(tmp_path, monkeypatch):
    from orchestrator.visual_qa.install import install_model

    monkeypatch.setenv("DATA_HANDLER_VISUAL_QA_HOME", str(tmp_path / "home"))
    weights = tmp_path / "weights"
    weights.mkdir()
    (weights / "config.json").write_text("{}")
    record = install_model(local_path=weights, revision="deadbeef")
    assert record["registered_offline"] is True and record["revision"] == "deadbeef" and record["quantization"] is None
    assert settings.read_model_manifest()["local_path"] == str(weights.resolve())
    with pytest.raises(ValueError):
        install_model(source_repo="someone/Qwen3.5-4B-4bit", local_path=weights)
    derived = install_model(source_repo="someone/qwen-mlx", quantization="4bit", derived_from="Qwen/Qwen3.5-4B", local_path=weights)
    assert derived["quantization"] == "4bit" and derived["original_model_id"] == "Qwen/Qwen3.5-4B"


def test_cli_foreground_start_status_and_report_regeneration(tmp_path, monkeypatch, capsys):
    pytest.importorskip("av")
    from orchestrator.visual_qa import worker
    from orchestrator.visual_qa.backend import MockBackend
    from visual_qa_helpers import write_video

    env = make_run(tmp_path, monkeypatch, clips={"A/c.mp4": lambda p: write_video(p, 4)})
    monkeypatch.setattr(worker, "make_backend", lambda name: MockBackend(lambda *a: CLEAN_JSON))
    assert cli.main(["visual-qa", "start", "--run-id", env["run_id"], "--foreground", "--max-frames-per-clip", "2"]) == 0
    out = capsys.readouterr().out
    assert '"status": "completed"' in out
    assert cli.main(["visual-qa", "status", "--run-id", env["run_id"]]) == 0
    status = json.loads(capsys.readouterr().out)
    qa_id = status["runs"][0]["qa_id"]
    assert status["runs"][0]["limited"] is True and status["runs"][0]["report_ready"] is True
    report = env["folder"] / "visual_qa" / qa_id / "report.html"
    report.unlink()
    assert cli.main(["visual-qa", "report", "--run-id", env["run_id"], "--qa-id", qa_id]) == 0
    assert report.is_file()
    assert cli.main(["visual-qa", "report", "--run-id", env["run_id"], "--qa-id", "../x"]) == 2


def test_cli_start_reports_blocked_when_existing_work_is_unfinished(tmp_path, monkeypatch, capsys):
    env = make_run(tmp_path, monkeypatch, clips={"A/c.mp4": b"x"}, datahelper=False)
    assert cli.main(["visual-qa", "start", "--run-id", env["run_id"]]) == 2
    assert "existing_processing_not_finished" in capsys.readouterr().out


def test_smoke_harness_end_to_end_with_mock_is_labelled_mock(tmp_path):
    pytest.importorskip("av")
    import numpy as np

    from orchestrator.visual_qa.backend import MockBackend
    from orchestrator.visual_qa.smoke import run_smoke
    from visual_qa_helpers import issue_json

    def responder(images, system, user):
        arr = np.asarray(images[0])
        if "색을 한 단어" in user:
            r, g, b = arr[224, 224]
            return "빨강" if r > b else "파랑"
        return issue_json() if arr.mean() < 12 else CLEAN_JSON

    result = run_smoke(MockBackend(responder), tmp_path / "smoke")
    assert result["mock"] is True and result["image_input_check"]["passed"] is True
    assert result["clips"]["normal"]["counts"]["events_total"] == 0
    assert result["clips"]["anomalous"]["counts"]["events_total"] >= 1
    assert (tmp_path / "smoke" / "smoke-result.json").is_file()


def test_smoke_stops_when_the_model_does_not_see_the_image(tmp_path):
    pytest.importorskip("PIL")
    from orchestrator.visual_qa.backend import MockBackend
    from orchestrator.visual_qa.smoke import run_smoke

    result = run_smoke(MockBackend(lambda *a: "잘 모르겠습니다"), tmp_path / "smoke")
    assert result["image_input_check"]["passed"] is False and result["clips"] == {}


def test_cli_smoke_fails_if_image_check_passes_but_clips_fail(tmp_path, monkeypatch, capsys):
    pytest.importorskip("av")
    from orchestrator.visual_qa.backend import MockBackend

    def responder(images, _system, user):
        if "색을 한 단어" in user:
            red, _, blue = images[0].getpixel((224, 224))
            return "빨강" if red > blue else "파랑"
        return "not-json"

    monkeypatch.setattr(backend_module, "MlxVlmBackend", lambda: MockBackend(responder))
    assert cli.main(["visual-qa", "smoke", "--output", str(tmp_path / "smoke")]) == 1
    result = json.loads((tmp_path / "smoke" / "smoke-result.json").read_text())
    assert result["image_input_check"]["passed"] is True
    assert {clip["status"] for clip in result["clips"].values()} == {"failed"}
