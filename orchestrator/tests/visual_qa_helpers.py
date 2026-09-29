"""Fixtures for visual QA tests: real encoded videos and fake completed runs."""
from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path
from typing import Any, Callable

from orchestrator.jsonio import write_json


def write_video(path: Path, frames: int = 12, size: tuple[int, int] = (320, 180), *, black_from: int | None = None,
                black_to: int | None = None, bright_block_from: int | None = None, rate: int = 24) -> Path:
    """Encode a small H.264 mp4. Frames are gray ramps; optional black or bright-block segments."""
    import av
    import numpy as np

    path.parent.mkdir(parents=True, exist_ok=True)
    container = av.open(str(path), "w")
    stream = container.add_stream("libx264", rate=rate)
    stream.width, stream.height, stream.pix_fmt = size[0], size[1], "yuv420p"
    stream.options = {"crf": "10", "preset": "ultrafast"}
    for index in range(frames):
        image = np.zeros((size[1], size[0], 3), np.uint8)
        image[:, :, :] = 90 + (index * 5) % 100
        image[:, : size[0] // 2, 0] += 40  # left half warmer so the frame is not flat
        if black_from is not None and black_from <= index < (black_to if black_to is not None else frames):
            image[:] = 0
        if bright_block_from is not None and index >= bright_block_from:
            image[20:70, size[0] - 90:size[0] - 30, :] = 255
        frame = av.VideoFrame.from_ndarray(image, format="rgb24")
        for packet in stream.encode(frame):
            container.mux(packet)
    for packet in stream.encode():
        container.mux(packet)
    container.close()
    return path


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def make_run(tmp_path: Path, monkeypatch, *, run_id: str = "run-qa1", clips: dict[str, Callable[[Path], Path] | bytes] | None = None,
             replicas: int = 2, datahelper: bool = True, verified: bool = True, visual_qa: bool = True,
             run_mode: str = "workflow", extra_files: dict[str, bytes] | None = None) -> dict[str, Any]:
    """Create a completed run on disk with per-replica verified files. Returns useful paths."""
    from orchestrator import run_state

    runs_root = tmp_path / "pipeline" / "runs"
    monkeypatch.setattr(run_state, "RUNS_ROOT", runs_root)
    folder = runs_root / run_id
    roots = {f"path{i + 1}": tmp_path / f"backup{i + 1}" / "Project" for i in range(replicas)}
    path_ids = [f"vol-{i + 1}" for i in range(replicas)]
    clips = clips if clips is not None else {"A001/clip1.mp4": lambda p: write_video(p, 8)}
    files = []
    for relpath, maker in {**(clips), **{k: (lambda p, b=v: (p.parent.mkdir(parents=True, exist_ok=True), p.write_bytes(b), p)[2]) for k, v in (extra_files or {}).items()}}.items():
        source = tmp_path / "card" / relpath
        if callable(maker):
            maker(source)
        else:
            source.parent.mkdir(parents=True, exist_ok=True)
            source.write_bytes(maker)
        checksum = sha(source)
        results = []
        for index, (label, root) in enumerate(roots.items()):
            destination = root / "001_Footage" / "R#1" / relpath
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, destination)
            results.append({"path_id": path_ids[index], "status": "verified", "checksum": checksum,
                            "dest_relpath": str(Path("001_Footage") / "R#1" / relpath)})
        files.append({"file_id": f"f-{len(files)}", "job_id": "job-1", "source_path_id": "src-1",
                      "source_relpath": relpath, "size_bytes": source.stat().st_size, "checksum_source": checksum,
                      "status": "verified", "replica_results": results})
    write_json(folder / "request.json", {
        "run_id": run_id, "project_name": "Project", "source_path": str(tmp_path / "card"),
        "source_paths": [str(tmp_path / "card")], "replica_roots": [str(r.parent) for r in roots.values()],
        "footage_run_name": "R#1", "run_mode": run_mode, "flat_card_layout": True,
        **({"visual_qa": True} if visual_qa else {})})
    write_json(folder / "events/datamanager.done.json", {
        "run_id": run_id, "stage": "datamanager", "status": "completed" if verified else "warn",
        "job_id": "job-1", "job_state": "COMPLETED", "replicas_complete": verified,
        "replica_project_roots": {k: str(v) for k, v in roots.items()}, "replica_path_ids": path_ids,
        "card_report_relpath": "00_Master/reports/R#1", "file_count": len(files), "finished_at": "2026-01-01T00:00:00+00:00"})
    write_json(folder / "blackmagician/manifest.json", {"job_id": "job-1", "files": files})
    if datahelper:
        write_json(folder / "events/datahelper.done.json", {"run_id": run_id, "status": "completed", "reports": [],
                                                            "finished_at": "2026-01-01T00:10:00+00:00"})
    write_json(folder / "state.json", {"run_id": run_id, "stage": "done", "status": "completed"})
    return {"runs_root": runs_root, "folder": folder, "roots": roots, "run_id": run_id,
            "replica_files": {rel: [roots[label] / "001_Footage" / "R#1" / rel for label in roots] for rel in clips},
            "no_spawn": lambda run, qa: 4242}


def issue_json(category: str = "black_or_flat_frame", priority: str = "medium", *, bbox=None, temporal: bool = False) -> str:
    return json.dumps({"frame_assessment": "suspect", "findings": [{
        "category": category, "priority": priority, "observation": "화면 전체가 검게 보입니다.",
        "reason_for_review": "검은 프레임은 의도 여부 확인이 필요합니다.", "uncertainty": None, "bbox": bbox,
        "point": None, "needs_temporal_confirmation": temporal, "suggested_human_check": "해당 시점 원본 확인"}]},
        ensure_ascii=False)


CLEAN_JSON = json.dumps({"frame_assessment": "no_issue_observed", "findings": []})


def brightness_responder(images, system, user) -> str:
    """Mock model that looks at real pixels: dark frames are 'suspect'. Proves images arrive."""
    import numpy as np

    assert len(images) == 1 and hasattr(images[0], "size"), "a real PIL image must be passed"
    mean = float(np.asarray(images[0]).mean())
    return issue_json() if mean < 12 else CLEAN_JSON
