"""QA worker process: python -m orchestrator.visual_qa.worker RUN_ID QA_ID."""
from __future__ import annotations

import signal
import sys
import threading
import time
from pathlib import Path

from orchestrator import run_state
from orchestrator.visual_qa import store
from orchestrator.visual_qa.backend import BackendUnavailable, VisionBackend, make_backend
from orchestrator.visual_qa.runner import run_qa
from orchestrator.visual_qa.scheduler import visual_qa_root
from orchestrator.visual_qa.settings import load_settings
from orchestrator.visual_qa.store import QaDir, file_lock


def run(run_id: str, qa_id: str, *, backend: VisionBackend | None = None, runs_root: Path | None = None,
        stop: threading.Event | None = None, reader_factory=None) -> dict:
    """Run one QA under its worker lock and the global one-at-a-time slot."""
    root = runs_root or run_state.RUNS_ROOT
    qa = QaDir(visual_qa_root(run_id, root) / qa_id)
    if not qa.manifest.is_file():
        raise SystemExit(f"unknown QA run: {run_id}/{qa_id}")
    stop = stop or threading.Event()
    with file_lock(qa.worker_lock, blocking=False) as owned:
        if not owned:
            return qa.read_state()  # another worker already owns this QA
        qa.write_state(status=store.QUEUED, phase="waiting_for_slot", pid=None, message="다른 영상 QA가 끝나기를 기다리는 중")
        slot = root.parent / "visual_qa.slot.lock"
        while True:
            if stop.is_set() or (qa.path / "cancel.requested").exists():
                return qa.write_state(status=store.CANCELLED, reason="cancel_requested", phase="done")
            with file_lock(slot, blocking=False) as got:
                if got:
                    return _execute(run_id, qa, backend, stop, reader_factory)
            time.sleep(2.0)


def _execute(run_id: str, qa: QaDir, backend: VisionBackend | None, stop: threading.Event, reader_factory) -> dict:
    try:
        active = backend or make_backend(load_settings().get("backend") or "mlx_vlm")
    except BackendUnavailable as exc:
        return qa.write_state(status=store.BLOCKED, reason=exc.code, message=str(exc))
    kwargs = {"reader_factory": reader_factory} if reader_factory else {}
    try:
        return run_qa(qa.path, active, stop=stop, **kwargs)
    except Exception as exc:  # unexpected crash: keep the journal, report failure honestly
        return qa.write_state(status=store.FAILED, reason="worker_crashed", message=f"{type(exc).__name__}: {exc}")
    finally:
        active.close()


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    if len(args) != 2:
        print("usage: python -m orchestrator.visual_qa.worker RUN_ID QA_ID", file=sys.stderr)
        return 2
    stop = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    run(args[0], args[1], stop=stop)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
