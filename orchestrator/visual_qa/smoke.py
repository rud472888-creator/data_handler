"""Real-model smoke test: image-input check, then a normal and an anomalous synthetic clip.

Run on the Apple Silicon Mac after installing the model:
    python -m orchestrator.cli visual-qa smoke --output DIR
The backend is injectable so tests can exercise the harness with a mock (clearly
labelled in the output); a real result only comes from MlxVlmBackend.
"""
from __future__ import annotations

import json
import shutil
import time
from pathlib import Path
from typing import Any

from orchestrator.jsonio import write_json
from orchestrator.visual_qa.backend import VisionBackend
from orchestrator.visual_qa.scheduler import schedule_visual_qa, visual_qa_root
from orchestrator.visual_qa.store import QaDir, read_jsonl, write_json_atomic

COLOR_QUESTION = "이미지 한가운데 있는 큰 사각형의 색을 한 단어로만 답하세요. (예: 빨강, 파랑, 초록)"
COLOR_WORDS = {"red": ("빨강", "빨간", "red"), "blue": ("파랑", "파란", "blue")}


def _solid(color: tuple[int, int, int], square: tuple[int, int, int]):
    from PIL import Image, ImageDraw

    image = Image.new("RGB", (448, 448), color)
    ImageDraw.Draw(image).rectangle([112, 112, 336, 336], fill=square)
    return image


def image_input_check(backend: VisionBackend) -> dict[str, Any]:
    """Prove pixels reach the model: two images differing only in colour must yield different, correct answers."""
    system = "이미지를 보고 질문에 짧게 답하세요."
    answers = {}
    for name, square in (("red", (220, 30, 30)), ("blue", (30, 60, 220))):
        result = backend.infer([_solid((235, 235, 235), square)], system, COLOR_QUESTION,
                               max_new_tokens=32, timeout_s=300)
        answers[name] = result.text.strip()
    ok = all(any(w in answers[name].lower() for w in COLOR_WORDS[name]) for name in answers)
    return {"passed": ok, "answers": answers, "question": COLOR_QUESTION,
            "note": "정답 라벨을 모델 입력에 넣지 않았습니다. 이미지가 비전 입력으로 전달되었는지만 확인합니다."}


def build_fixture_run(root: Path, name: str, video_maker) -> tuple[Path, str]:
    """A minimal completed run whose manifest points at one replica copy of the clip."""
    import hashlib

    runs_root = root / "pipeline" / "runs"
    run_id = f"run-smoke-{name}"
    folder = runs_root / run_id
    project = root / "backup1" / "SmokeProject"
    relpath = f"A001/{name}.mp4"
    destination = project / "001_Footage" / "R#1" / relpath
    video_maker(destination)
    checksum = hashlib.sha256(destination.read_bytes()).hexdigest()
    write_json(folder / "request.json", {
        "run_id": run_id, "project_name": "SmokeProject", "source_path": str(root / "card"), "source_paths": [str(root / "card")],
        "replica_roots": [str(root / "backup1")], "footage_run_name": "R#1", "run_mode": "workflow", "visual_qa": True})
    write_json(folder / "events/datamanager.done.json", {
        "run_id": run_id, "status": "completed", "job_id": "smoke", "replicas_complete": True,
        "replica_project_roots": {"path1": str(project)}, "replica_path_ids": ["vol-1"], "finished_at": "2026-01-01T00:00:00+00:00"})
    write_json(folder / "events/datahelper.done.json", {"run_id": run_id, "status": "completed", "reports": []})
    write_json(folder / "blackmagician/manifest.json", {"job_id": "smoke", "files": [{
        "source_path_id": "src-1", "source_relpath": relpath, "size_bytes": destination.stat().st_size,
        "checksum_source": checksum, "status": "verified",
        "replica_results": [{"path_id": "vol-1", "status": "verified", "checksum": checksum,
                             "dest_relpath": str(Path("001_Footage") / "R#1" / relpath)}]}]})
    write_json(folder / "state.json", {"run_id": run_id, "stage": "done", "status": "completed"})
    return runs_root, run_id


def _encode(path: Path, frames: int, painter) -> Path:
    import av
    import numpy as np

    path.parent.mkdir(parents=True, exist_ok=True)
    width, height = 640, 360
    container = av.open(str(path), "w")
    stream = container.add_stream("libx264", rate=24)
    stream.width, stream.height, stream.pix_fmt = width, height, "yuv420p"
    stream.options = {"crf": "12", "preset": "fast"}
    yy, xx = np.mgrid[0:height, 0:width]
    for index in range(frames):
        image = np.stack([(xx * 255 // width), (yy * 255 // height), np.full_like(xx, 110)], axis=-1).astype(np.uint8)
        image = painter(image, index)
        for packet in stream.encode(av.VideoFrame.from_ndarray(image, format="rgb24")):
            container.mux(packet)
    for packet in stream.encode():
        container.mux(packet)
    container.close()
    return path


def normal_clip(path: Path) -> Path:
    return _encode(path, 12, lambda image, index: image)


def anomalous_clip(path: Path) -> Path:
    def paint(image, index):
        if 4 <= index < 8:
            image[:] = 0  # black frames
        if index >= 8:
            image[0:360, 500:640] = (30, 30, 30)  # dark bar intruding from the right edge
        return image

    return _encode(path, 12, paint)


def run_smoke(backend: VisionBackend, output: Path) -> dict[str, Any]:
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    backend.check_ready()
    report: dict[str, Any] = {"model": backend.describe(), "image_input_check": image_input_check(backend),
                              "clips": {}, "mock": backend.is_mock}
    if not report["image_input_check"]["passed"]:
        write_json_atomic(output / "smoke-result.json", report)
        return report
    from orchestrator.visual_qa import worker

    for name, maker in (("normal", normal_clip), ("anomalous", anomalous_clip)):
        work = output / name
        shutil.rmtree(work, ignore_errors=True)
        runs_root, run_id = build_fixture_run(work, name, maker)
        result = schedule_visual_qa(run_id, trigger="smoke", manual=True, runs_root=runs_root, spawn=lambda *a: 0,
                                    config={"model_max_side": 640})
        qa = QaDir(visual_qa_root(run_id, runs_root) / result["qa_id"])
        state = worker.run(run_id, qa.qa_id, backend=backend, runs_root=runs_root)
        frames = [r for r in read_jsonl(qa.frames)[0] if r.get("type") == "frame"]
        summary = json.loads(qa.summary.read_text()) if qa.summary.is_file() else {}
        report["clips"][name] = {
            "status": state.get("status"), "counts": state.get("counts"), "report": str(qa.report),
            "timings": summary.get("timings"), "peak_memory_bytes": summary.get("peak_memory_bytes_reported_by_backend"),
            "per_frame": [{"frame": f["frame_index"], "assessment": f.get("frame_assessment"),
                           "categories": [x["category"] for x in f.get("findings", [])], "status": f["status"]}
                          for f in frames],
            "ground_truth_for_human_comparison_only": (
                "정상 그라디언트 12프레임" if name == "normal" else "프레임 4-7 완전 검정, 프레임 8-11 오른쪽 가장자리 어두운 띠"),
        }
    report["total_wall_s"] = round(time.monotonic() - started, 1)
    report["note"] = "관측한 검출·오탐·누락을 그대로 기록한 baseline이며 실제 촬영물 정확도가 아닙니다."
    write_json_atomic(output / "smoke-result.json", report)
    return report
