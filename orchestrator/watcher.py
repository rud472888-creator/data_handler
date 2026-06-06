from __future__ import annotations

from pathlib import Path
from typing import Any

from orchestrator.hermes_bridge import launch_wakeup_session
from orchestrator.jsonio import read_json, write_json
from orchestrator.paths import WATCH_STATE_PATH
from orchestrator.run_state import RUNS_ROOT, load_spec


def watch_once(*, direct: bool = False) -> list[dict[str, Any]]:
    state = _load_watch_state()
    processed = state.setdefault("processed", {})
    actions: list[dict[str, Any]] = []
    for artifact in sorted(RUNS_ROOT.glob("*/events/*.done.json")):
        signature = _signature(artifact)
        key = str(artifact)
        if processed.get(key) == signature:
            continue
        action = _handle_artifact(artifact, direct=direct)
        processed[key] = signature
        actions.append(action)
    write_json(WATCH_STATE_PATH, state)
    return actions


def _handle_artifact(artifact: Path, *, direct: bool) -> dict[str, Any]:
    run_id = artifact.parents[1].name
    spec = load_spec(run_id)
    if artifact.name == "datamanager.done.json":
        if direct:
            from orchestrator.cli import continue_datamanager

            continue_datamanager(run_id)
            return {"run_id": run_id, "artifact": str(artifact), "action": "continue_datamanager"}
        result = launch_wakeup_session(run_id, "datamanager", spec.hermes_profile)
        return {
            "run_id": run_id,
            "artifact": str(artifact),
            "action": "launch_hermes",
            "result": result,
        }
    if artifact.name == "datahelper.done.json":
        if direct:
            from orchestrator.cli import continue_datahelper

            continue_datahelper(run_id)
            return {"run_id": run_id, "artifact": str(artifact), "action": "continue_datahelper"}
        result = launch_wakeup_session(run_id, "datahelper", spec.hermes_profile)
        return {
            "run_id": run_id,
            "artifact": str(artifact),
            "action": "launch_hermes",
            "result": result,
        }
    return {"run_id": run_id, "artifact": str(artifact), "action": "ignored"}


def _load_watch_state() -> dict[str, Any]:
    if not WATCH_STATE_PATH.exists():
        return {"processed": {}}
    return read_json(WATCH_STATE_PATH)


def _signature(path: Path) -> str:
    stat = path.stat()
    return f"{stat.st_size}:{stat.st_mtime_ns}"
