"""Pipeline tests on real encoded video with a MOCK backend (never the real Qwen model)."""
from __future__ import annotations

import json
import threading
from pathlib import Path

import pytest

pytest.importorskip("av")
pytest.importorskip("PIL")
pytest.importorskip("numpy")

from orchestrator.visual_qa import store, worker
from orchestrator.visual_qa.backend import BackendUnavailable, InferenceError, InferenceResult, MockBackend
from orchestrator.visual_qa.scheduler import schedule_visual_qa, visual_qa_root
from orchestrator.visual_qa.store import QaDir, read_jsonl

from visual_qa_helpers import CLEAN_JSON, brightness_responder, issue_json, make_run, write_video


def start(env, **kwargs):
    result = schedule_visual_qa(env["run_id"], trigger="test", manual=True, spawn=env["no_spawn"],
                                runs_root=env["runs_root"], **kwargs)
    return result, QaDir(visual_qa_root(env["run_id"], env["runs_root"]) / result["qa_id"])


def run_worker(env, qa, backend, **kwargs):
    return worker.run(env["run_id"], qa.qa_id, backend=backend, runs_root=env["runs_root"], **kwargs)


def frames_of(qa):
    records, _ = read_jsonl(qa.frames)
    return [r for r in records if r.get("type") == "frame"]


def test_end_to_end_black_segment_becomes_one_event_with_evidence_and_report(tmp_path, monkeypatch):
    env = make_run(tmp_path, monkeypatch, clips={"A001/C0001.mp4": lambda p: write_video(p, 12, black_from=4, black_to=8)})
    result, qa = start(env)
    backend = MockBackend(brightness_responder)  # looks at the real pixels it is handed
    state = run_worker(env, qa, backend)
    assert state["status"] == store.COMPLETED and state["coverage"] == "full"
    frames = frames_of(qa)
    assert len(frames) == 12 and backend.calls == 12  # every decoded frame reached the backend
    assert [f["frame_index"] for f in frames if f["frame_assessment"] == "suspect"] == [4, 5, 6, 7]
    for f in frames:
        assert f["time_base"] and f["pts"] is not None and f["clip_time_s"] is not None
        assert f["source_size"] == [320, 180] and f["model_size"] == [320, 180]
    times = [f["clip_time_s"] for f in frames]
    assert times == sorted(times) and abs(times[1] - 1 / 24) < 1e-6
    findings = json.loads(qa.findings.read_text())
    assert findings["counts"]["events_total"] == 1 and findings["counts"]["frames_analyzed"] == 12
    event = findings["events"][0]
    assert (event["start_frame"], event["end_frame"], event["frame_count"]) == (4, 7, 4)
    assert event["human_review_status"] == "unreviewed"
    for ref in event["evidence_frames"]:
        assert (qa.path / ref["evidence"]["original"]).is_file() and (qa.path / ref["evidence"]["preview"]).is_file()
    report = qa.report.read_text()
    assert "MOCK 백엔드" in report and "evidence/" in report and "C0001.mp4" in report
    assert "src=\"evidence/" in report and "/tmp" not in report and str(tmp_path) not in report
    # the manifest records which replica was inspected and which model (mock) was used
    clip = findings["clips"][0]
    assert clip["replica_used"] == ["path1"] and clip["eof_reached"] is True and clip["declared_mismatch"] is False
    assert json.loads(qa.manifest.read_text())["model"]["is_mock"] is True


def test_identical_replicas_are_inspected_once(tmp_path, monkeypatch):
    env = make_run(tmp_path, monkeypatch, replicas=3, clips={"A/c.mp4": lambda p: write_video(p, 5)})
    _, qa = start(env)
    backend = MockBackend(lambda *a: CLEAN_JSON)
    run_worker(env, qa, backend)
    assert backend.calls == 5
    assert {f["replica"] for f in frames_of(qa)} == {"path1"}


def test_frame_failures_are_recorded_and_not_reported_as_normal(tmp_path, monkeypatch):
    env = make_run(tmp_path, monkeypatch, clips={"A/c.mp4": lambda p: write_video(p, 6)})
    _, qa = start(env)
    seen = {"n": 0}

    def flaky(images, system, user):
        seen["n"] += 1
        return "이건 JSON이 아닙니다" if seen["n"] in {3, 4, 5, 6} else CLEAN_JSON  # frame 2 fails after 1 try + 2 retries

    state = run_worker(env, qa, MockBackend(flaky))
    frames = {f["frame_index"]: f for f in frames_of(qa)}
    assert frames[2]["status"] == "failed" and frames[2]["error"]["kind"] == "invalid_json"
    assert frames[2].get("frame_assessment") is None  # never rewritten into no_issue_observed
    assert len(frames[2]["attempts"]) == 3
    assert state["status"] == store.PARTIAL and state["coverage"] == "incomplete"
    assert json.loads(qa.findings.read_text())["counts"]["frames_failed"] == 1
    assert "프레임 분석 실패" in qa.report.read_text()
    assert any(r["kind"] == "frame_failed" for r in read_jsonl(qa.errors)[0])


def test_retry_recovers_valid_answer_on_second_attempt(tmp_path, monkeypatch):
    env = make_run(tmp_path, monkeypatch, clips={"A/c.mp4": lambda p: write_video(p, 2)})
    _, qa = start(env)
    answers = iter(["{", CLEAN_JSON, CLEAN_JSON])
    state = run_worker(env, qa, MockBackend(lambda *a: next(answers)))
    assert state["status"] == store.COMPLETED
    assert [len(f["attempts"]) for f in frames_of(qa)] == [2, 1]


def test_truncated_output_is_failure_after_bounded_retries(tmp_path, monkeypatch):
    env = make_run(tmp_path, monkeypatch, clips={"A/c.mp4": lambda p: write_video(p, 1)})
    _, qa = start(env)
    backend = MockBackend(lambda *a: InferenceResult(text=CLEAN_JSON, finish_reason="length"))
    state = run_worker(env, qa, backend)
    assert backend.calls == 3 and state["status"] == store.FAILED
    assert frames_of(qa)[0]["error"]["kind"] == "truncated"


def test_limited_range_is_never_labelled_full_inspection(tmp_path, monkeypatch):
    env = make_run(tmp_path, monkeypatch, clips={"A/c.mp4": lambda p: write_video(p, 20)})
    _, qa = start(env, config={"max_frames_per_clip": 5, "start_frame": 2})
    state = run_worker(env, qa, MockBackend(lambda *a: CLEAN_JSON))
    assert [f["frame_index"] for f in frames_of(qa)] == [2, 3, 4, 5, 6]
    assert state["status"] == store.COMPLETED and state["coverage"] == "limited"
    report = qa.report.read_text()
    assert "제한 범위 검사" in report and "전체 클립 검사 완료로 해석하지 마세요" in report
    assert json.loads(qa.manifest.read_text())["config"]["max_frames_per_clip"] == 5


def test_no_findings_report_says_nothing_found_in_inspected_range(tmp_path, monkeypatch):
    env = make_run(tmp_path, monkeypatch, clips={"A/c.mp4": lambda p: write_video(p, 3)})
    _, qa = start(env)
    run_worker(env, qa, MockBackend(lambda *a: CLEAN_JSON))
    report = qa.report.read_text()
    assert "검사한 범위에서 의심 사항을 발견하지 못했습니다" in report and "완벽" not in report


def test_raw_and_non_video_files(tmp_path, monkeypatch):
    env = make_run(tmp_path, monkeypatch, clips={"A/c.mp4": lambda p: write_video(p, 3)},
                   extra_files={"A/clip.braw": b"RAW", "A/notes.txt": b"x"})
    _, qa = start(env)
    state = run_worker(env, qa, MockBackend(lambda *a: CLEAN_JSON))
    findings = json.loads(qa.findings.read_text())
    by_name = {c["display_name"]: c for c in findings["clips"]}
    assert by_name["clip.braw"]["status"] == "unsupported" and by_name["clip.braw"]["frames_analyzed"] == 0
    assert "notes.txt" not in by_name
    assert state["status"] == store.PARTIAL and state["coverage"] == "incomplete"
    assert "미지원" in qa.report.read_text() and "Blackmagic RAW" in qa.report.read_text()


def test_decode_failure_on_truncated_file_is_partial_with_error(tmp_path, monkeypatch):
    def broken(path: Path):
        write_video(path, 30)
        data = path.read_bytes()
        path.write_bytes(data[: len(data) // 2])
        return path

    env = make_run(tmp_path, monkeypatch, clips={"A/broken.mp4": broken, "A/ok.mp4": lambda p: write_video(p, 4)}, replicas=1)
    _, qa = start(env)
    state = run_worker(env, qa, MockBackend(lambda *a: CLEAN_JSON))
    clips = {c["display_name"]: c for c in json.loads(qa.findings.read_text())["clips"]}
    assert clips["ok.mp4"]["status"] == "completed"  # other clips keep going
    assert clips["broken.mp4"]["status"] in {"failed", "partial"}
    assert state["status"] == store.PARTIAL and state["coverage"] == "incomplete"


def test_replica_missing_switches_to_another_verified_replica_and_records_it(tmp_path, monkeypatch):
    env = make_run(tmp_path, monkeypatch, clips={"A/c.mp4": lambda p: write_video(p, 5)})
    _, qa = start(env)
    first, second = env["replica_files"]["A/c.mp4"]
    first.unlink()  # backup drive 1 went away after verification; no fallback to the card
    state = run_worker(env, qa, MockBackend(lambda *a: CLEAN_JSON))
    clip = json.loads(qa.findings.read_text())["clips"][0]
    assert clip["replica_used"] == ["path2"] and clip["replicas_rejected"][0]["label"] == "path1"
    assert state["status"] == store.COMPLETED
    assert str(tmp_path / "card") not in json.dumps(json.loads(qa.manifest.read_text())["clips"])


def test_size_changed_replica_is_rejected_and_all_replicas_gone_is_input_unavailable(tmp_path, monkeypatch):
    env = make_run(tmp_path, monkeypatch, clips={"A/c.mp4": lambda p: write_video(p, 5)})
    _, qa = start(env)
    first, second = env["replica_files"]["A/c.mp4"]
    first.write_bytes(first.read_bytes()[:-10])
    second.unlink()
    state = run_worker(env, qa, MockBackend(lambda *a: CLEAN_JSON))
    clip = json.loads(qa.findings.read_text())["clips"][0]
    assert clip["status"] == "input_unavailable" and state["status"] == store.FAILED
    assert {r["label"] for r in clip["replicas_rejected"]} == {"path1", "path2"}


def test_backend_unavailable_blocks_with_reason_and_no_fake_frames(tmp_path, monkeypatch):
    env = make_run(tmp_path, monkeypatch)
    _, qa = start(env)
    backend = MockBackend(lambda *a: CLEAN_JSON)
    backend.ready_error = BackendUnavailable("model_not_installed", "모델이 설치되어 있지 않습니다.")
    state = run_worker(env, qa, backend)
    assert state["status"] == store.BLOCKED and state["reason"] == "model_not_installed"
    assert frames_of(qa) == [] and backend.calls == 0
    assert "시작할 수 없음" in qa.report.read_text()


def test_backend_error_mid_run_is_a_failed_frame_not_a_pass(tmp_path, monkeypatch):
    env = make_run(tmp_path, monkeypatch, clips={"A/c.mp4": lambda p: write_video(p, 3)})
    _, qa = start(env)

    def down(images, system, user):
        raise InferenceError("backend_error", "inference server stopped")

    state = run_worker(env, qa, MockBackend(down))
    assert all(f["status"] == "failed" and f["error"]["kind"] == "backend_error" for f in frames_of(qa))
    assert state["status"] == store.FAILED


def test_hung_backend_stops_the_run_and_marks_remaining_clips_not_run(tmp_path, monkeypatch):
    from orchestrator.visual_qa.backend import BackendPoisoned

    env = make_run(tmp_path, monkeypatch, clips={"A/1.mp4": lambda p: write_video(p, 3), "A/2.mp4": lambda p: write_video(p, 3)})
    _, qa = start(env)
    calls = {"n": 0}

    def hang(images, system, user):
        calls["n"] += 1
        if calls["n"] == 2:
            raise BackendPoisoned("timeout", "추론이 시간 안에 끝나지 않았습니다.")
        return CLEAN_JSON

    state = run_worker(env, qa, MockBackend(hang))
    clips = {c["display_name"]: c for c in json.loads(qa.findings.read_text())["clips"]}
    assert state["status"] == store.PARTIAL and state["reason"] == "backend_stopped"
    assert clips["2.mp4"]["status"] == "not_run" and calls["n"] == 2


def test_resume_reuses_valid_frames_and_recovers_torn_journal(tmp_path, monkeypatch):
    env = make_run(tmp_path, monkeypatch, clips={"A/c.mp4": lambda p: write_video(p, 10, black_from=2, black_to=4)})
    _, qa = start(env)
    stop = threading.Event()
    seen = {"n": 0}

    def stopping(images, system, user):
        seen["n"] += 1
        if seen["n"] == 5:
            stop.set()
        return brightness_responder(images, system, user)

    state = run_worker(env, qa, MockBackend(stopping), stop=stop)
    assert state["status"] == store.CANCELLED and len(frames_of(qa)) == 5
    # simulate a crash mid-write: torn last record without newline
    with qa.frames.open("ab") as handle:
        handle.write(b'{"type": "frame", "clip_id": "x", "frame_ind')
    (qa.path / "cancel.requested").unlink(missing_ok=True)
    resumed, same_qa = start(env)
    assert resumed["action"] == "retry" and same_qa.qa_id == qa.qa_id
    backend = MockBackend(brightness_responder)
    state = run_worker(env, qa, backend)
    assert backend.calls == 5  # only the 5 unfinished frames were analysed again
    assert state["status"] == store.COMPLETED and state["counts"]["frames_analyzed"] == 10
    records, bad = read_jsonl(qa.frames)
    assert bad == 0 and len([r for r in records if r.get("type") == "frame"]) == 10
    assert json.loads(qa.findings.read_text())["counts"]["events_total"] == 1


def test_resume_retries_failed_frames_only(tmp_path, monkeypatch):
    env = make_run(tmp_path, monkeypatch, clips={"A/c.mp4": lambda p: write_video(p, 4)})
    _, qa = start(env)
    assert run_worker(env, qa, MockBackend(lambda *a: "garbage"))["status"] == store.FAILED
    _, same = start(env)
    backend = MockBackend(lambda *a: CLEAN_JSON)
    state = run_worker(env, qa, backend)
    assert backend.calls == 4 and state["status"] == store.COMPLETED


def test_model_change_blocks_mixing_results(tmp_path, monkeypatch):
    env = make_run(tmp_path, monkeypatch, clips={"A/c.mp4": lambda p: write_video(p, 3)})
    _, qa = start(env)
    run_worker(env, qa, MockBackend(lambda *a: CLEAN_JSON))

    class OtherModel(MockBackend):
        def describe(self):
            return {**super().describe(), "loaded_model": "another-model", "revision": "abc"}

    state = run_worker(env, qa, OtherModel(lambda *a: CLEAN_JSON))
    assert state["status"] == store.BLOCKED and state["reason"] == "model_changed"
    assert len(frames_of(qa)) == 3  # nothing appended by the different model


def test_report_can_be_regenerated_from_stored_results(tmp_path, monkeypatch):
    from orchestrator.visual_qa.runner import rebuild_outputs

    env = make_run(tmp_path, monkeypatch, clips={"A/c.mp4": lambda p: write_video(p, 4, black_from=1, black_to=3)})
    _, qa = start(env)
    run_worker(env, qa, MockBackend(brightness_responder))
    before = qa.report.read_text()
    qa.report.unlink()
    assert rebuild_outputs(qa.path) is None
    assert qa.report.read_text() == before or "evidence/" in qa.report.read_text()


def test_report_failure_does_not_lose_analysis(tmp_path, monkeypatch):
    from orchestrator.visual_qa import report

    env = make_run(tmp_path, monkeypatch, clips={"A/c.mp4": lambda p: write_video(p, 3)})
    _, qa = start(env)
    monkeypatch.setattr(report, "render_report", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    state = run_worker(env, qa, MockBackend(lambda *a: CLEAN_JSON))
    assert state["status"] == store.COMPLETED and "boom" in (state.get("report_error") or "")
    assert qa.findings.is_file() and len(frames_of(qa)) == 3


def test_source_media_and_replicas_are_never_modified(tmp_path, monkeypatch):
    import hashlib

    env = make_run(tmp_path, monkeypatch, clips={"A/c.mp4": lambda p: write_video(p, 6, black_from=1, black_to=3)})
    paths = [p for group in env["replica_files"].values() for p in group] + list((tmp_path / "card").rglob("*.mp4"))
    before = {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    listing = sorted(str(p) for p in tmp_path.rglob("*") if "visual_qa" not in str(p) and "pipeline" not in str(p))
    _, qa = start(env)
    run_worker(env, qa, MockBackend(brightness_responder))
    assert before == {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    assert listing == sorted(str(p) for p in tmp_path.rglob("*") if "visual_qa" not in str(p) and "pipeline" not in str(p))


def test_evidence_cap_keeps_analysis_and_says_so(tmp_path, monkeypatch):
    env = make_run(tmp_path, monkeypatch, clips={"A/c.mp4": lambda p: write_video(p, 6, black_from=0, black_to=6)})
    _, qa = start(env, config={"max_evidence_frames_per_clip": 2})
    run_worker(env, qa, MockBackend(brightness_responder))
    frames = frames_of(qa)
    assert sum(1 for f in frames if (f["evidence"] or {}).get("original")) == 2
    assert all(f["frame_assessment"] == "suspect" for f in frames)
    assert len(json.loads(qa.findings.read_text())["events"]) == 1
