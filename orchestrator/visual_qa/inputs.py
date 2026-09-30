"""Resolve QA inputs from trusted completion evidence only. Stdlib only.

Clips come from the DataManager manifest (verified replica results); no path or
file name is guessed from disk contents.
"""
from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any

from orchestrator import run_state
from orchestrator.visual_qa.config import digest
from orchestrator.visual_qa.decode import classify_path
from orchestrator.visual_qa.store import read_json_safe


class InputsBlocked(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def runs_root_default() -> Path:
    return run_state.RUNS_ROOT


def _label_for(index: int) -> str:
    return f"path{index + 1}"


def _card_info(run_id: str, request: dict[str, Any], registry_path: Path) -> dict[str, Any]:
    info: dict[str, Any] = {"project_name": request.get("project_name"), "run_id": run_id,
                            "shoot_date": None, "camera_unit": None, "roll": None, "card": None}
    registry = read_json_safe(registry_path)
    for record in registry.get("runs", []) if isinstance(registry.get("runs"), list) else []:
        if isinstance(record, dict) and record.get("run_id") == run_id:
            info.update(shoot_date=record.get("shoot_date"), camera_unit=record.get("camera_unit"),
                        roll=record.get("roll"), project_id=record.get("project_id"))
            break
    name = request.get("footage_run_name")
    if name:
        info["card"] = Path(str(name)).name
        info["roll"] = info["roll"] or info["card"]
        match = re.fullmatch(r"([^/]+)/([^/]+)/(.+)", str(name))
        if match:
            info["shoot_date"] = info["shoot_date"] or match.group(1)
            info["camera_unit"] = info["camera_unit"] or match.group(2)
    return info


def resolve_inputs(run_id: str, runs_root: Path | None = None, registry_path: Path | None = None) -> dict[str, Any]:
    """Return clips + upstream evidence for a finished run, or raise InputsBlocked."""
    runs_dir = runs_root or runs_root_default()
    folder = runs_dir / run_id
    request = read_json_safe(folder / "request.json")
    if not request:
        raise InputsBlocked("request_missing", "작업 요청 기록(request.json)을 찾을 수 없습니다.")
    copy = read_json_safe(folder / "events/datamanager.done.json")
    if not copy:
        raise InputsBlocked("existing_processing_not_finished", "복제 작업이 아직 끝나지 않았습니다.")
    if copy.get("status") != "completed" or copy.get("replicas_complete") is not True:
        raise InputsBlocked("backup_not_verified", "복제본 체크섬 검증이 완료되지 않아 영상 QA를 시작하지 않습니다.")
    report = read_json_safe(folder / "events/datahelper.done.json")
    mode = request.get("run_mode") or "workflow"
    if mode != "datamanager" and not report:
        raise InputsBlocked("existing_processing_not_finished", "기존 보고서 작업(DataHelper)이 아직 끝나지 않았습니다.")
    roots = copy.get("replica_project_roots")
    path_ids = copy.get("replica_path_ids")
    if not isinstance(roots, dict) or not roots or not isinstance(path_ids, list):
        raise InputsBlocked("replica_links_missing", "복제본 위치 기록(replica_project_roots/replica_path_ids)이 없습니다.")
    manifest = read_json_safe(folder / "blackmagician/manifest.json")
    if not manifest:
        rel = copy.get("card_report_relpath")
        first = roots.get("path1")
        if rel and first:
            manifest = read_json_safe(Path(str(first)) / str(rel) / "manifest.json")
    files = manifest.get("files")
    if not isinstance(files, list) or not files:
        raise InputsBlocked("manifest_missing", "복제 manifest를 찾을 수 없어 검사할 클립을 확정할 수 없습니다.")
    if manifest.get("job_id") and copy.get("job_id") and manifest["job_id"] != copy["job_id"]:
        raise InputsBlocked("manifest_mismatch", "manifest의 job_id가 완료 기록과 다릅니다.")
    labels = {_label_for(i): pid for i, pid in enumerate(path_ids)}
    clips: list[dict[str, Any]] = []
    ignored = 0
    identity: list[Any] = []
    for entry in sorted((f for f in files if isinstance(f, dict)), key=lambda f: str(f.get("source_relpath"))):
        relpath = str(entry.get("source_relpath") or "")
        kind, label = classify_path(Path(relpath))
        if kind == "ignored":
            ignored += 1
            continue
        clip_id = "c" + hashlib.sha1(f"{entry.get('source_path_id')}|{relpath}".encode()).hexdigest()[:12]
        candidates = []
        for replica_label, path_id in sorted(labels.items()):
            root = roots.get(replica_label)
            for replica in entry.get("replica_results") or []:
                if (root and isinstance(replica, dict) and replica.get("path_id") == path_id
                        and replica.get("status") == "verified" and entry.get("checksum_source")
                        and replica.get("checksum") == entry.get("checksum_source") and replica.get("dest_relpath")):
                    candidates.append({"label": replica_label, "path": str(Path(str(root)) / str(replica["dest_relpath"])),
                                       "expected_size": entry.get("size_bytes")})
        clip = {"clip_id": clip_id, "display_name": Path(relpath).name, "source_relpath": relpath,
                "size_bytes": entry.get("size_bytes"), "checksum_source": entry.get("checksum_source"),
                "kind": kind, "format_label": label, "candidates": candidates}
        if kind == "raw":
            clip["unsupported_reason"] = (f"{label}은 연속 프레임 디코딩 어댑터가 없어 이번 버전에서 검사하지 않습니다. "
                                          "기존 대표 프레임 추출은 전체 검사로 취급하지 않습니다.")
        clips.append(clip)
        identity.append([entry.get("source_path_id"), relpath, entry.get("size_bytes"), entry.get("checksum_source")])
    if not clips:
        raise InputsBlocked("no_video_files", "이 카드의 복제 manifest에 검사할 영상 파일이 없습니다.")
    return {
        "clips": clips, "ignored_files": ignored,
        "upstream": {**_card_info(run_id, request, registry_path or runs_dir.parent / "console-registry.json"),
                     "datamanager": {"status": copy.get("status"), "job_id": copy.get("job_id"),
                                     "replicas_complete": copy.get("replicas_complete"),
                                     "finished_at": copy.get("finished_at")},
                     "datahelper": {"status": report.get("status") if report else None,
                                    "finished_at": report.get("finished_at") if report else None},
                     "backup_verified": True, "run_mode": mode,
                     "replica_labels": sorted(labels)},
        "input_revision": digest([copy.get("job_id"), copy.get("finished_at"), identity]),
    }
