from __future__ import annotations

from pathlib import Path
from typing import Any

from orchestrator.jsonio import read_json, write_json
from orchestrator.media_preflight import (
    MediaDependencyPreflightError,
    MediaPreflightReport,
    validate_media_dependencies,
)
from orchestrator.processes import spawn_python_module
from orchestrator.run_state import events_dir, run_dir, update_state, utc_now
from orchestrator.web.progress import write_progress


def validate_datahelper_input(run_id: str) -> None:
    done_path = events_dir(run_id) / "datamanager.done.json"
    if not done_path.is_file():
        raise ValueError("DataManager completion artifact is required before DataHandler can run")
    done = read_json(done_path)
    if done.get("status") == "failed":
        raise ValueError("DataManager failed; DataHandler cannot run")
    replica_project_roots = done.get("replica_project_roots")
    if not isinstance(replica_project_roots, dict) or not replica_project_roots:
        raise ValueError("DataManager output is missing replica project roots")


def start_datahelper_stage(run_id: str, *, trigger: str) -> int | None:
    validate_datahelper_input(run_id)
    event_dir = events_dir(run_id)
    if (event_dir / "datahelper.done.json").exists():
        return None
    started_path = event_dir / "datahelper.started.json"
    if started_path.exists():
        return None
    replica_input_paths = _replica_footage_input_paths(run_id)
    update_state(run_id, stage="datahelper-preflight", status="running")
    try:
        preflight = validate_media_dependencies(replica_input_paths)
    except MediaDependencyPreflightError as exc:
        _write_datahelper_preflight_event(
            run_id,
            status="failed",
            report=exc.report,
            trigger=trigger,
            error=str(exc),
        )
        update_state(
            run_id,
            stage="datahelper-preflight",
            status="failed",
            error=str(exc),
        )
        raise
    _write_datahelper_preflight_event(
        run_id,
        status="completed",
        report=preflight,
        trigger=trigger,
    )
    write_json(
        started_path,
        {
            "run_id": run_id,
            "stage": "datahelper",
            "status": "starting",
            "started_at": utc_now(),
            "trigger": trigger,
        },
    )
    pid = spawn_python_module(run_id, "orchestrator.datahelper_worker", run_id)
    write_json(
        started_path,
        {
            "run_id": run_id,
            "stage": "datahelper",
            "status": "spawned",
            "pid": pid,
            "started_at": utc_now(),
            "trigger": trigger,
        },
    )
    update_state(run_id, stage="datahelper", status=f"spawned pid={pid}")
    write_progress(
        run_dir(run_id),
        {"stage": "datahelper", "status": "spawned", "step": "reports", "pid": pid},
    )
    return pid


def _replica_footage_input_paths(run_id: str) -> tuple[str, ...]:
    done = read_json(events_dir(run_id) / "datamanager.done.json")
    project_roots = done["replica_project_roots"]
    footage_roots = done.get("replica_footage_roots", {})
    return tuple(
        str(footage_roots[label])
        if isinstance(footage_roots, dict) and footage_roots.get(label)
        else str(Path(str(project_roots[label])) / "01_Footage")
        for label in sorted(project_roots)
    )


def _write_datahelper_preflight_event(
    run_id: str,
    *,
    status: str,
    report: MediaPreflightReport,
    trigger: str,
    error: str | None = None,
) -> None:
    payload: dict[str, object] = {
        "run_id": run_id,
        "stage": "datahelper-preflight",
        "status": status,
        "report": report.to_dict(),
        "trigger": trigger,
        "finished_at": utc_now(),
    }
    if error is not None:
        payload["error"] = error
    write_json(events_dir(run_id) / "datahelper-preflight.done.json", payload)


def datahelper_start_status(run_id: str) -> dict[str, Any]:
    event_dir = events_dir(run_id)
    ready = True
    reason = ""
    try:
        validate_datahelper_input(run_id)
    except ValueError as exc:
        ready = False
        reason = str(exc)
    return {
        "ready": ready,
        "reason": reason,
        "datamanager_done": (event_dir / "datamanager.done.json").exists(),
        "datahelper_started": (event_dir / "datahelper.started.json").exists(),
        "datahelper_done": (event_dir / "datahelper.done.json").exists(),
    }
