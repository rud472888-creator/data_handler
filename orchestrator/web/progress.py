from __future__ import annotations

from pathlib import Path
from typing import Any

from orchestrator.jsonio import read_json, write_json
from orchestrator.run_state import utc_now
from orchestrator.spec import RunSpec


SUPPORTED_SOURCE_SUFFIXES = frozenset({".ari", ".braw", ".mov", ".mp4", ".mxf", ".r3d"})


def write_progress(run_dir: Path, payload: dict[str, Any]) -> None:
    write_json(run_dir / "progress.json", {"updated_at": utc_now(), **payload})


def load_run_progress(run_dir: Path) -> dict[str, Any]:
    progress_path = run_dir / "progress.json"
    state_path = run_dir / "state.json"
    progress = read_json(progress_path) if progress_path.exists() else None
    if state_path.exists():
        state = read_json(state_path)
        if state.get("stage") == "done" or state.get("status") in {
            "completed",
            "done",
            "failed",
            "warn",
            "review-needed",
        }:
            if progress is not None:
                return _with_run_context(run_dir, {**progress, **state})
            return _with_run_context(run_dir, state)
        if progress is None:
            return _with_run_context(run_dir, state)
    if progress is not None:
        return _with_run_context(run_dir, progress)
    return _with_run_context(run_dir, {"stage": "new", "status": "unknown"})


def list_artifacts(run_dir: Path) -> list[dict[str, str]]:
    return [
        artifact
        for artifact in list_declared_artifacts(run_dir)
        if _artifact_file_ready(Path(artifact["path"]))
    ]


def list_declared_artifacts(run_dir: Path) -> list[dict[str, str]]:
    artifacts: list[dict[str, str]] = []
    final_report = run_dir / "final-report.md"
    if final_report.is_file():
        artifacts.append({"name": "final report", "path": str(final_report), "kind": "markdown"})

    datahelper_done = run_dir / "events" / "datahelper.done.json"
    if datahelper_done.exists():
        done = read_json(datahelper_done)
        for report in _iter_datahelper_reports(done.get("reports", [])):
            label = str(report.get("label", "report"))
            artifact_label = (
                label if label.lower().startswith("datahelper") else f"datahelper-{label}"
            )
            for key, kind in (("pdf_path", "pdf"), ("csv_path", "csv"), ("json_path", "json")):
                path = Path(str(report.get(key, "")))
                if str(path) not in {"", "."}:
                    artifacts.append(
                        {"name": f"{artifact_label} {kind}", "path": str(path), "kind": kind}
                    )

    datamanager_done = run_dir / "events" / "datamanager.done.json"
    if datamanager_done.exists():
        done = read_json(datamanager_done)
        for report_type, path_value in done.get("reports", {}).items():
            path = Path(str(path_value))
            if str(path) not in {"", "."}:
                artifacts.append(
                    {
                        "name": str(report_type).replace("_", " "),
                        "path": str(path),
                        "kind": str(report_type),
                    }
                )
    return artifacts


def _artifact_file_ready(path: Path) -> bool:
    return path.is_file() and path.stat().st_size > 0


def _iter_datahelper_reports(reports: Any) -> list[dict[str, Any]]:
    if isinstance(reports, list):
        return [report for report in reports if isinstance(report, dict)]
    if not isinstance(reports, dict):
        return []
    normalized: list[dict[str, Any]] = []
    for label, payload in reports.items():
        if not isinstance(payload, dict):
            continue
        normalized.append(
            {
                "label": label,
                "pdf_path": _legacy_report_path(payload.get("pdf")),
                "csv_path": _legacy_report_path(payload.get("csv")),
                "json_path": _legacy_report_path(payload.get("json")),
            }
        )
    return normalized


def _legacy_report_path(value: Any) -> Any:
    if isinstance(value, dict):
        return value.get("path")
    return value


def _with_run_context(run_dir: Path, progress: dict[str, Any]) -> dict[str, Any]:
    payload = _with_phase_context(
        run_dir,
        _with_observed_copy_progress(run_dir, _with_request_context(run_dir, progress)),
    )
    quality = _quality_summary(run_dir)
    failure = _failure_summary(run_dir)
    if quality:
        payload["quality"] = quality
        if quality["status"] == "needs_review":
            payload["process_status"] = payload.get("status")
            payload["status"] = "review-needed"
            payload["activity_state"] = "needs_review"
            payload["phase_label"] = "Backup complete, review needed"
            payload["phase_detail"] = _quality_detail(quality)
            payload["overall_progress"] = {
                **payload.get("overall_progress", {}),
                "percent": 100,
                "title": payload["phase_label"],
                "subtitle": payload["phase_detail"],
            }
        elif quality["status"] == "failed":
            payload["process_status"] = payload.get("status")
            payload["status"] = "failed"
            payload["activity_state"] = "failed"
            payload["phase_label"] = "Media inspection failed"
            payload["phase_detail"] = _quality_detail(quality)
    if failure:
        payload["failure"] = failure
        if str(payload.get("status", "")).lower() in {"failed", "error"}:
            payload["phase_detail"] = _failure_detail(failure)
            if isinstance(payload.get("overall_progress"), dict):
                payload["overall_progress"] = {
                    **payload["overall_progress"],
                    "subtitle": payload["phase_detail"],
                }
    return payload


def _quality_summary(run_dir: Path) -> dict[str, Any] | None:
    done_path = run_dir / "events" / "datahelper.done.json"
    if not done_path.exists():
        return None
    done = read_json(done_path)
    reports = _iter_datahelper_reports(done.get("reports", []))
    if not reports:
        return None

    observed_statuses: set[str] = set()
    counters: dict[str, int] = {
        "total_clips": 0,
        "success_count": 0,
        "partial_success_count": 0,
        "probe_failed_count": 0,
        "decode_failed_count": 0,
        "skipped_count": 0,
    }
    for report in reports:
        report_status = str(report.get("status", "")).strip().lower()
        if report_status:
            observed_statuses.add(report_status)
        stdout_values = _stdout_values(report.get("stdout"))
        stdout_status = str(stdout_values.get("status", "")).strip().lower()
        if stdout_status:
            observed_statuses.add(stdout_status)
        for key in counters:
            value = _int_from_text(stdout_values.get(key))
            if value is not None:
                counters[key] = max(counters[key], value)

    issue_count = (
        counters["partial_success_count"]
        + counters["probe_failed_count"]
        + counters["decode_failed_count"]
    )
    if "failed" in observed_statuses or "error" in observed_statuses:
        status = "failed"
    elif issue_count > 0 or "partial_success" in observed_statuses:
        status = "needs_review"
    else:
        status = "passed"
    return {"status": status, "issue_count": issue_count, **counters}


def _stdout_values(value: Any) -> dict[str, str]:
    if not isinstance(value, str):
        return {}
    parsed: dict[str, str] = {}
    for line in value.splitlines():
        key, separator, raw_value = line.partition(":")
        if separator:
            parsed[key.strip()] = raw_value.strip()
    return parsed


def _int_from_text(value: Any) -> int | None:
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return None


def _quality_detail(quality: dict[str, Any]) -> str:
    issue_count = int(quality.get("issue_count", 0))
    total_clips = int(quality.get("total_clips", 0))
    if quality.get("status") == "failed":
        return "Media inspection did not complete. Review the generated log before handoff."
    if total_clips:
        return f"{issue_count} of {total_clips} clips need review; report files were generated."
    return f"{issue_count} clips need review; report files were generated."


def _failure_summary(run_dir: Path) -> dict[str, Any] | None:
    done_path = run_dir / "events" / "datamanager.done.json"
    if not done_path.exists():
        return None
    done = read_json(done_path)
    failed_files = [str(value) for value in done.get("failed_files", []) if str(value)]
    if not failed_files and str(done.get("status", "")).lower() not in {"failed", "error"}:
        return None
    return {
        "failed_files": failed_files,
        "failed_count": len(failed_files),
        "job_state": str(done.get("job_state", done.get("status", "failed"))),
    }


def _failure_detail(failure: dict[str, Any]) -> str:
    failed_files = failure.get("failed_files", [])
    if failed_files:
        return f"{len(failed_files)} file failed: {failed_files[0]}"
    return "The backup worker failed before a safe handoff was recorded."


def _with_request_context(run_dir: Path, progress: dict[str, Any]) -> dict[str, Any]:
    request_path = run_dir / "request.json"
    if not request_path.exists():
        return progress
    request = read_json(request_path)
    run_mode = request.get("run_mode")
    if run_mode is None:
        return progress
    return {"run_mode": str(run_mode), **progress}


def _with_observed_copy_progress(run_dir: Path, progress: dict[str, Any]) -> dict[str, Any]:
    stage = str(progress.get("stage", ""))
    if stage not in {"copy", "datamanager", "copy-checksum", "done"}:
        return progress
    request_path = run_dir / "request.json"
    if not request_path.exists():
        return progress
    spec = RunSpec.from_payload(read_json(request_path))
    if spec.footage_run_name is None:
        return progress

    source_files = _source_files(spec.source_paths)
    if not source_files or not spec.replica_roots:
        return progress

    total_bytes = sum(size for _, _, size in source_files) * len(spec.replica_roots)
    observed_bytes = 0
    copied_files = 0
    active_files = 0
    source_path_ids = _source_path_ids(progress, len(spec.source_paths))
    for source_index, relpath, size_bytes in source_files:
        source_id = source_path_ids[source_index]
        file_complete = True
        file_active = False
        for replica_root in spec.replica_roots:
            target = (
                replica_root
                / spec.project_name
                / "01_Footage"
                / spec.footage_run_name
                / source_id
                / relpath
            )
            observed = _observed_target_bytes(target, size_bytes)
            observed_bytes += observed
            file_complete = file_complete and observed >= size_bytes
            file_active = file_active or (0 < observed < size_bytes)
        if file_complete:
            copied_files += 1
        if file_active:
            active_files += 1

    copy_progress: dict[str, Any] = {
        "available": True,
        "unit": "bytes",
        "bytes_observed": observed_bytes,
        "bytes_total": total_bytes,
        "byte_percent": round((observed_bytes / total_bytes) * 100) if total_bytes > 0 else 0,
        "copied_files": copied_files,
        "total_files": len(source_files),
        "file_count": progress.get("file_count") or len(source_files),
        "replica_count": len(spec.replica_roots),
        "active_files": active_files,
    }
    observed: dict[str, Any] = {
        "copy_progress": copy_progress,
        "copied_files": copied_files,
        "total_files": len(source_files),
        "file_count": progress.get("file_count") or len(source_files),
        "replica_count": len(spec.replica_roots),
        "active_files": active_files,
    }
    if stage in {"copy", "datamanager", "copy-checksum"}:
        observed.update(
            {
                "current": observed_bytes,
                "total": total_bytes,
                "percent": copy_progress["byte_percent"],
            }
        )
    return {**progress, **observed}


def _source_files(source_paths: tuple[Path, ...]) -> list[tuple[int, Path, int]]:
    files: list[tuple[int, Path, int]] = []
    for source_index, source_root in enumerate(source_paths):
        if not source_root.is_dir():
            continue
        for path in sorted(source_root.rglob("*")):
            if _is_supported_source(path):
                files.append((source_index, path.relative_to(source_root), path.stat().st_size))
    return files


def _is_supported_source(path: Path) -> bool:
    return (
        path.is_file()
        and path.suffix.lower() in SUPPORTED_SOURCE_SUFFIXES
        and path.name != ".DS_Store"
        and not path.name.startswith("._")
    )


def _observed_target_bytes(target: Path, expected_bytes: int) -> int:
    if target.is_file():
        return min(target.stat().st_size, expected_bytes)
    if not target.parent.exists():
        return 0
    partials = target.parent.glob(f".{target.name}.partial-*")
    return min(sum(path.stat().st_size for path in partials if path.is_file()), expected_bytes)


def _source_path_ids(progress: dict[str, Any], count: int) -> tuple[str, ...]:
    raw_ids = progress.get("source_path_ids")
    if isinstance(raw_ids, list) and len(raw_ids) >= count and all(isinstance(value, str) for value in raw_ids[:count]):
        return tuple(raw_ids[:count])
    return tuple(f"source-path-{index + 1}" for index in range(count))


def _with_phase_context(run_dir: Path, progress: dict[str, Any]) -> dict[str, Any]:
    stage = str(progress.get("stage", ""))
    status = str(progress.get("status", ""))
    normalized_status = status.lower()
    datamanager_done = (run_dir / "events" / "datamanager.done.json").exists()
    datahelper_started = (run_dir / "events" / "datahelper.started.json").exists()
    datahelper_done = (run_dir / "events" / "datahelper.done.json").exists()
    context: dict[str, Any]

    if stage in {"datamanager", "copy", "copy-checksum"}:
        context = _datamanager_context(progress, normalized_status, datamanager_done, datahelper_started)
    elif stage in {"datahelper", "reports"}:
        context = _datahelper_context(progress, normalized_status, datahelper_done)
    elif stage == "done":
        context = {
            "program": "Orchestrator",
            "phase": "done",
            "phase_label": "Pipeline complete",
            "phase_detail": _terminal_detail(progress, "Final workflow state has been written."),
            "activity_state": _activity_state(normalized_status),
        }
    elif stage == "new":
        context = {
            "program": "Orchestrator",
            "phase": "unknown",
            "phase_label": "Run not started",
            "phase_detail": "No run state or progress artifact has been written yet.",
            "activity_state": "unknown",
        }
    else:
        context = {
            "program": "Orchestrator",
            "phase": stage or "setup",
            "phase_label": "Preparing run",
            "phase_detail": f"Status: {status or 'unknown'}.",
            "activity_state": _activity_state(normalized_status),
        }

    payload = {
        **progress,
        **context,
        "datamanager_done": datamanager_done,
        "datahelper_started": datahelper_started,
        "datahelper_done": datahelper_done,
        "last_progress_at": progress.get("updated_at"),
        "progress_observed": _progress_observed(progress),
    }
    copy_progress = _copy_progress(payload)
    report_progress = _report_progress_payload(payload)
    clip_progress = _clip_progress(payload)
    payload.update(
        {
            "copy_progress": copy_progress,
            "report_progress": report_progress,
            "clip_progress": clip_progress,
        }
    )
    payload["overall_progress"] = _overall_progress(payload, copy_progress, report_progress)
    return payload


def _datamanager_context(
    progress: dict[str, Any],
    status: str,
    datamanager_done: bool,
    datahelper_started: bool,
) -> dict[str, Any]:
    if status in {"failed", "error"}:
        return {
            "program": "DataManager",
            "phase": "datamanager_failed",
            "phase_label": "DataManager failed",
            "phase_detail": _error_detail(progress),
            "activity_state": "failed",
        }
    if status in {"queued", "spawned"} or status.startswith("spawned"):
        return {
            "program": "DataManager",
            "phase": "datamanager_starting",
            "phase_label": "DataManager starting",
            "phase_detail": "DataManager worker has been queued or spawned; waiting for copy output.",
            "activity_state": "waiting",
        }
    if status in {"completed", "done", "warn", "review-needed"} or datamanager_done:
        if progress.get("run_mode") == "datamanager" and not datahelper_started:
            detail = "DataManager-only copy/checksum finished; DataHandler has not been started for this run."
        elif datahelper_started:
            detail = "DataManager copy/checksum finished; DataHelper report generation has started."
        else:
            detail = "DataManager copy/checksum finished; waiting for DataHelper report generation."
        return {
            "program": "DataManager",
            "phase": "datamanager_complete",
            "phase_label": "DataManager complete",
            "phase_detail": _terminal_detail(progress, detail),
            "activity_state": _activity_state(status),
        }
    return {
        "program": "DataManager",
        "phase": "datamanager_copy",
        "phase_label": "DataManager copying and verifying footage",
        "phase_detail": _copy_detail(progress),
        "activity_state": "running",
    }


def _datahelper_context(progress: dict[str, Any], status: str, datahelper_done: bool) -> dict[str, Any]:
    if status in {"failed", "error"}:
        return {
            "program": "DataHelper (Handler)",
            "phase": "datahelper_failed",
            "phase_label": "DataHelper failed",
            "phase_detail": _error_detail(progress),
            "activity_state": "failed",
        }
    if status in {"spawned", "starting"} or status.startswith("spawned"):
        return {
            "program": "DataHelper (Handler)",
            "phase": "datahelper_starting",
            "phase_label": "DataHelper starting",
            "phase_detail": "DataHelper worker has been spawned; waiting for report output.",
            "activity_state": "waiting",
        }
    if status in {"completed", "done", "warn", "review-needed"} or datahelper_done:
        return {
            "program": "DataHelper (Handler)",
            "phase": "datahelper_complete",
            "phase_label": "DataHelper reports complete",
            "phase_detail": _terminal_detail(progress, _report_detail(progress)),
            "activity_state": _activity_state(status),
        }
    return {
        "program": "DataHelper (Handler)",
        "phase": "datahelper_reports",
        "phase_label": "DataHelper generating reports",
        "phase_detail": _report_detail(progress),
        "activity_state": "running",
    }


def _copy_detail(progress: dict[str, Any]) -> str:
    copied = _int_value(progress.get("copied_files"))
    total_files = _int_value(progress.get("total_files") or progress.get("file_count"))
    active = _int_value(progress.get("active_files"))
    replicas = _int_value(progress.get("replica_count"))
    current = _int_value(progress.get("current"))
    total = _int_value(progress.get("total"))
    parts: list[str] = []
    if copied is not None and total_files:
        parts.append(f"{copied} of {total_files} source files copied")
    elif total_files:
        parts.append(f"{total_files} source files discovered")
    if replicas:
        parts.append(f"{replicas} replica paths")
    if current is not None and total:
        parts.append(f"{current} of {total} bytes observed")
    if active is not None:
        parts.append(f"{active} files actively changing")
    if not parts:
        return "DataManager is running; waiting for observable copy/checksum output."
    return "; ".join(parts) + "."


def _report_detail(progress: dict[str, Any]) -> str:
    completed = _int_value(progress.get("report_completed") or progress.get("completed"))
    total = _int_value(progress.get("report_total") or progress.get("total"))
    count = _int_value(progress.get("report_count"))
    parts: list[str] = []
    if completed is not None and total:
        parts.append(f"{completed} of {total} replica report jobs complete")
    elif total:
        parts.append(f"{total} replica report jobs queued")
    if count is not None:
        parts.append(f"{count} report artifacts available")
    if not parts:
        return "DataHelper is running Frame Proof reports for replica outputs."
    return "; ".join(parts) + "."


def _copy_progress(progress: dict[str, Any]) -> dict[str, Any]:
    raw = progress.get("copy_progress")
    if isinstance(raw, dict):
        payload = dict(raw)
        payload.setdefault("available", True)
        payload.setdefault("unit", "bytes")
        return payload
    if str(progress.get("stage", "")) not in {"copy", "datamanager", "copy-checksum"}:
        return {"available": False, "unit": "bytes"}
    current = _int_value(progress.get("current"))
    total = _int_value(progress.get("total"))
    percent = _int_value(progress.get("percent"))
    if percent is None and current is not None and total and total > 0:
        percent = round((current / total) * 100)
    payload = {
        "available": any(
            value is not None
            for value in (
                current,
                total,
                percent,
                _int_value(progress.get("copied_files")),
                _int_value(progress.get("total_files") or progress.get("file_count")),
            )
        ),
        "unit": "bytes",
        "bytes_observed": current,
        "bytes_total": total,
        "byte_percent": percent,
        "copied_files": _int_value(progress.get("copied_files")),
        "total_files": _int_value(progress.get("total_files") or progress.get("file_count")),
        "file_count": _int_value(progress.get("file_count") or progress.get("total_files")),
        "replica_count": _int_value(progress.get("replica_count")),
        "active_files": _int_value(progress.get("active_files")),
    }
    return payload


def _report_progress_payload(progress: dict[str, Any]) -> dict[str, Any]:
    raw = progress.get("report_progress")
    if isinstance(raw, dict):
        payload = dict(raw)
        payload.setdefault("available", True)
        return payload
    stage = str(progress.get("stage", ""))
    completed = _int_value(progress.get("report_completed"))
    total = _int_value(progress.get("report_total"))
    if stage in {"datahelper", "reports"}:
        if completed is None:
            completed = _int_value(progress.get("completed"))
        if total is None:
            total = _int_value(progress.get("total"))
    percent = round((completed / total) * 100) if completed is not None and total and total > 0 else None
    artifact_count = _int_value(progress.get("report_count"))
    payload = {
        "available": any(value is not None for value in (completed, total, artifact_count)),
        "completed": completed,
        "total": total,
        "percent": percent,
        "artifact_count": artifact_count,
        "artifacts_ready": progress.get("artifacts_ready") if isinstance(progress.get("artifacts_ready"), bool) else None,
    }
    return payload


def _clip_progress(progress: dict[str, Any]) -> dict[str, Any]:
    raw = progress.get("clip_progress")
    if isinstance(raw, dict):
        payload = dict(raw)
        payload.setdefault("available", True)
        return payload
    return {
        "available": False,
        "title": "No active clip-level telemetry",
        "subtitle": "Current file or clip-level progress has not been reported for this run.",
        "percent": None,
    }


def _overall_progress(
    progress: dict[str, Any],
    copy_progress: dict[str, Any],
    report_progress: dict[str, Any],
) -> dict[str, Any]:
    stage = str(progress.get("stage", ""))
    status = str(progress.get("status", "")).lower()
    title = str(progress.get("phase_label") or "Pipeline status")
    subtitle = str(progress.get("phase_detail") or "Waiting for progress telemetry.")
    if status in {"completed", "done"} and stage == "done":
        return {"kind": "terminal", "percent": 100, "title": title, "subtitle": subtitle}
    if stage in {"datahelper", "reports"}:
        return {
            "kind": "report_jobs",
            "percent": report_progress.get("percent"),
            "title": title,
            "subtitle": subtitle,
        }
    if stage in {"copy", "datamanager", "copy-checksum"}:
        return {
            "kind": "copy_bytes",
            "percent": copy_progress.get("byte_percent"),
            "title": title,
            "subtitle": subtitle,
        }
    if status in {"completed", "done"}:
        return {"kind": "terminal", "percent": 100, "title": title, "subtitle": subtitle}
    return {"kind": "pipeline_state", "percent": None, "title": title, "subtitle": subtitle}


def _terminal_detail(progress: dict[str, Any], fallback: str) -> str:
    if str(progress.get("status", "")).lower() in {"warn", "review-needed"}:
        return fallback + " Review generated artifacts before handoff."
    return fallback


def _error_detail(progress: dict[str, Any]) -> str:
    error = progress.get("last_error") or progress.get("error")
    if error:
        return str(error)
    return "The current worker reported a failure."


def _activity_state(status: str) -> str:
    if status in {"completed", "done"}:
        return "complete"
    if status in {"failed", "error"}:
        return "failed"
    if status in {"warn", "review-needed"}:
        return "needs_review"
    if status in {"queued", "spawned", "starting"} or status.startswith("spawned"):
        return "waiting"
    if status in {"running"}:
        return "running"
    return "unknown"


def _progress_observed(progress: dict[str, Any]) -> bool:
    current = _int_value(progress.get("current"))
    completed = _int_value(progress.get("completed") or progress.get("report_completed"))
    copied = _int_value(progress.get("copied_files"))
    report_count = _int_value(progress.get("report_count"))
    copy_progress = progress.get("copy_progress")
    if isinstance(copy_progress, dict):
        current = _int_value(copy_progress.get("bytes_observed"))
        copied = _int_value(copy_progress.get("copied_files"))
    return any(value is not None and value > 0 for value in (current, completed, copied, report_count))


def _int_value(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return None
