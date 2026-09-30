"""Idempotent QA scheduling shared by every completion path. Stdlib only.

Called from the DataHelper worker, the CLI continuations, the watcher and the DIT
app. Identity = (upstream run, input revision, analysis config); duplicate calls
find the existing QA directory instead of starting another one.
"""
from __future__ import annotations

import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from orchestrator import run_state
from orchestrator.visual_qa import store
from orchestrator.visual_qa.config import QaConfig, digest
from orchestrator.visual_qa.inputs import InputsBlocked, resolve_inputs
from orchestrator.visual_qa.settings import load_settings, runtime_python
from orchestrator.visual_qa.store import QaDir, file_lock, read_json_safe, utc_now, write_json_atomic

SPAWN_GRACE_S = 45
WORKER_MODULE = "orchestrator.visual_qa.worker"
_QA_ID = re.compile(r"qa-[0-9a-f]{12}(?:-r\d+)?")


class ScheduleError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def visual_qa_root(run_id: str, runs_root: Path | None = None) -> Path:
    return (runs_root or run_state.RUNS_ROOT) / run_id / "visual_qa"


def is_valid_qa_id(value: str) -> bool:
    return bool(_QA_ID.fullmatch(value))


def auto_enabled(request: dict[str, Any]) -> bool:
    option = request.get("visual_qa")
    return option is True or (isinstance(option, dict) and option.get("enabled") is True)


def build_config(overrides: dict[str, Any] | None = None) -> QaConfig:
    payload = {**(load_settings().get("config") or {}), **(overrides or {})}
    return QaConfig.from_payload(payload)


def _revisions(root: Path, identity: str) -> list[Path]:
    def number(path: Path) -> int:
        match = re.fullmatch(rf"{identity}(?:-r(\d+))?", path.name)
        return int(match.group(1) or 1) if match else 0

    found = [p for p in root.glob(f"{identity}*") if p.is_dir() and number(p)]
    return sorted(found, key=number)


def _spawn(run_id: str, qa_id: str) -> int:
    from orchestrator.processes import spawn_python_module

    return spawn_python_module(run_id, WORKER_MODULE, run_id, qa_id, python=runtime_python())


def _is_pending(state: dict[str, Any], qa: QaDir) -> bool:
    """A worker is running, or was spawned moments ago and hasn't taken its lock yet."""
    if qa.worker_alive():
        return True
    spawned = state.get("spawned_at")
    if state.get("status") in store.ACTIVE and spawned:
        try:
            age = (datetime.now(timezone.utc) - datetime.fromisoformat(spawned)).total_seconds()
        except ValueError:
            return False
        return age < SPAWN_GRACE_S
    return False


def _start_worker(run_id: str, qa: QaDir, spawn: Callable[[str, str], int] | None, action: str) -> dict[str, Any]:
    qa.write_state(status=store.QUEUED, reason=None, message="검사 대기 중", spawned_at=utc_now(), phase="queued")
    try:
        pid = (spawn or _spawn)(run_id, qa.qa_id)
    except Exception as exc:
        qa.write_state(status=store.FAILED, reason="spawn_failed", message=f"{type(exc).__name__}: {exc}")
        return {"status": store.FAILED, "action": "spawn_failed", "qa_id": qa.qa_id, "message": str(exc)}
    qa.write_state(worker_pid=pid)
    return {"status": store.QUEUED, "action": action, "qa_id": qa.qa_id, "pid": pid}


def _write_blocked_marker(root: Path, code: str, message: str, trigger: str) -> None:
    write_json_atomic(root / "blocked.json", {"status": store.BLOCKED, "reason": code, "message": message,
                                              "trigger": trigger, "at": utc_now()})


def schedule_visual_qa(run_id: str, *, trigger: str, manual: bool = False, new_revision: bool = False,
                       config: dict[str, Any] | None = None, runs_root: Path | None = None,
                       spawn: Callable[[str, str], int] | None = None,
                       registry_path: Path | None = None) -> dict[str, Any]:
    """Queue (or find) the visual QA for a finished run. Safe to call repeatedly."""
    root_runs = runs_root or run_state.RUNS_ROOT
    folder = root_runs / run_id
    request = read_json_safe(folder / "request.json")
    if not request:
        if manual:
            raise ScheduleError("run_missing", "작업 기록을 찾을 수 없습니다.")
        return {"status": "skipped", "action": "run_missing"}
    if not manual and not auto_enabled(request):
        return {"status": store.DISABLED, "action": "disabled"}
    qa_root = folder / "visual_qa"
    with file_lock(qa_root / "schedule.lock"):
        try:
            resolved = resolve_inputs(run_id, root_runs, registry_path)
        except InputsBlocked as exc:
            if manual:
                raise ScheduleError(exc.code, str(exc)) from exc
            if exc.code == "existing_processing_not_finished":
                return {"status": "waiting", "action": "waiting", "reason": exc.code}
            _write_blocked_marker(qa_root, exc.code, str(exc), trigger)
            return {"status": store.BLOCKED, "action": "blocked", "reason": exc.code, "message": str(exc)}
        try:
            cfg = build_config(config)
        except (TypeError, ValueError) as exc:
            raise ScheduleError("invalid_config", str(exc)) from exc
        identity = "qa-" + digest([run_id, resolved["input_revision"], cfg.fingerprint()])[:12]
        existing = _revisions(qa_root, identity)
        latest = QaDir(existing[-1]) if existing else None
        if latest is not None:
            state = latest.read_state()
            status = state.get("status")
            if _is_pending(state, latest):
                return {"status": status, "action": "already_running", "qa_id": latest.qa_id}
            if status in store.ACTIVE:
                return _start_worker(run_id, latest, spawn, "recovered")
            if not (new_revision and manual):
                if status in {store.PARTIAL, store.FAILED, store.BLOCKED, store.CANCELLED} and manual:
                    (latest.path / "cancel.requested").unlink(missing_ok=True)
                    return _start_worker(run_id, latest, spawn, "retry")
                return {"status": status, "action": "already_completed" if status == store.COMPLETED else "existing",
                        "qa_id": latest.qa_id}
        revision = len(existing) + 1
        qa_id = identity if revision == 1 else f"{identity}-r{revision}"
        qa = QaDir(qa_root / qa_id)
        qa.path.mkdir(parents=True, exist_ok=False)
        write_json_atomic(qa.manifest, {
            "qa_id": qa_id, "run_id": run_id, "revision": revision, "created_at": utc_now(), "trigger": trigger,
            "manual": manual, "input_revision": resolved["input_revision"], "config": cfg.to_payload(),
            "config_fingerprint": cfg.fingerprint(), "upstream": resolved["upstream"],
            "clips": resolved["clips"], "ignored_files": resolved["ignored_files"], "model": None,
        })
        (qa_root / "blocked.json").unlink(missing_ok=True)
        qa.write_state(status=store.QUEUED, created_at=utc_now(), trigger=trigger, revision=revision)
        return _start_worker(run_id, qa, spawn, "spawned")


def schedule_after_completion(run_id: str, trigger: str) -> None:
    """Best-effort hook for completion paths; never raises into the caller."""
    try:
        schedule_visual_qa(run_id, trigger=trigger)
    except Exception:  # QA scheduling must never change the backup/report outcome
        import logging

        logging.getLogger(__name__).exception("visual QA scheduling failed for %s", run_id)


def list_qa_dirs(run_id: str, runs_root: Path | None = None) -> list[Path]:
    root = visual_qa_root(run_id, runs_root)
    if not root.is_dir():
        return []
    dirs = [p for p in root.iterdir() if p.is_dir() and is_valid_qa_id(p.name)]
    return sorted(dirs, key=lambda p: (read_json_safe(p / "manifest.json").get("created_at") or "", p.name))


def qa_summary(run_id: str, runs_root: Path | None = None) -> dict[str, Any]:
    """Compact, cheap status for the UI (stat/read a few small files)."""
    root = runs_root or run_state.RUNS_ROOT
    request = read_json_safe(root / run_id / "request.json")
    summary: dict[str, Any] = {"auto_enabled": auto_enabled(request), "qa_id": None, "status": None,
                               "runs": [], "blocked": None}
    dirs = list_qa_dirs(run_id, root)
    blocked = read_json_safe(visual_qa_root(run_id, root) / "blocked.json")
    if blocked and not dirs:
        summary["blocked"] = blocked
        summary["status"] = store.BLOCKED
    for path in dirs:
        qa = QaDir(path)
        state = qa.read_state()
        manifest = store.read_json_safe(qa.manifest)
        alive = qa.worker_alive()
        pending = _is_pending(state, qa)
        interrupted = state.get("status") in store.ACTIVE and not pending
        summary["runs"].append({
            "qa_id": qa.qa_id, "revision": state.get("revision") or manifest.get("revision"),
            "status": state.get("status"), "reason": state.get("reason"), "message": state.get("message"),
            "phase": state.get("phase"), "counts": state.get("counts") or {}, "coverage": state.get("coverage"),
            "events_total": state.get("events_total"), "worker_alive": alive, "interrupted": interrupted,
            "report_ready": qa.report.is_file(), "report_error": state.get("report_error"),
            "mock_backend": bool(state.get("mock_backend")), "updated_at": state.get("updated_at"),
            "created_at": manifest.get("created_at"), "current_clip": state.get("current_clip"),
            "current_frame": state.get("current_frame"),
            "limits": QaConfig.from_payload(manifest["config"]).limits_text() if manifest.get("config") else "",
            "limited": bool(manifest.get("config") and QaConfig.from_payload(manifest["config"]).is_limited),
        })
    if summary["runs"]:
        summary.update({k: summary["runs"][-1][k] for k in ("qa_id", "status")})
    return summary


def recover_orphans(runs_root: Path | None = None, spawn: Callable[[str, str], int] | None = None) -> list[str]:
    """Restart QA workers that died mid-run. Never starts new inspections."""
    root = runs_root or run_state.RUNS_ROOT
    revived: list[str] = []
    for state_path in root.glob("*/visual_qa/qa-*/state.json"):
        qa = QaDir(state_path.parent)
        run_id = qa.path.parents[1].name
        state = qa.read_state()
        if state.get("status") not in store.ACTIVE or _is_pending(state, qa):
            continue
        with file_lock(qa.path.parent / "schedule.lock"):
            state = qa.read_state()
            if state.get("status") in store.ACTIVE and not _is_pending(state, qa):
                if _start_worker(run_id, qa, spawn, "recovered").get("action") == "recovered":
                    revived.append(f"{run_id}/{qa.qa_id}")
    return revived


def request_cancel(run_id: str, qa_id: str, runs_root: Path | None = None) -> bool:
    if not is_valid_qa_id(qa_id):
        return False
    qa = QaDir(visual_qa_root(run_id, runs_root) / qa_id)
    if not qa.path.is_dir():
        return False
    (qa.path / "cancel.requested").write_text(utc_now())
    return True
