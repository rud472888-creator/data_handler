from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from orchestrator.jsonio import read_json, write_json
from orchestrator.paths import RUNS_ROOT
from orchestrator.spec import RunSpec


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def run_dir(run_id: str) -> Path:
    return RUNS_ROOT / run_id


def events_dir(run_id: str) -> Path:
    return run_dir(run_id) / "events"


def request_path(run_id: str) -> Path:
    return run_dir(run_id) / "request.json"


def state_path(run_id: str) -> Path:
    return run_dir(run_id) / "state.json"


def load_spec(run_id: str) -> RunSpec:
    return RunSpec.from_payload(read_json(request_path(run_id)))


def save_spec(spec: RunSpec) -> None:
    spec.validate()
    write_json(request_path(spec.run_id), spec.to_payload())


def update_state(run_id: str, *, stage: str, status: str, error: str | None = None) -> None:
    payload: dict[str, Any] = {
        "run_id": run_id,
        "stage": stage,
        "status": status,
        "updated_at": utc_now(),
    }
    if error:
        payload["last_error"] = error
    write_json(state_path(run_id), payload)


def load_state(run_id: str) -> dict[str, Any]:
    path = state_path(run_id)
    if not path.exists():
        return {"run_id": run_id, "stage": "new", "status": "unknown"}
    return read_json(path)
