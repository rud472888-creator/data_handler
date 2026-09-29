"""Durable QA run storage: atomic JSON, crash-tolerant JSONL, worker liveness. Stdlib only."""
from __future__ import annotations

import fcntl
import json
import os
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

# Statuses that describe the QA *execution*; detection results are separate.
QUEUED, RUNNING, COMPLETED, PARTIAL = "queued", "running", "completed", "partial"
FAILED, BLOCKED, CANCELLED, DISABLED = "failed", "blocked", "cancelled", "disabled"
TERMINAL = {COMPLETED, PARTIAL, FAILED, BLOCKED, CANCELLED, DISABLED}
ACTIVE = {QUEUED, RUNNING}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def write_json_atomic(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + f".{os.getpid()}.tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
        handle.flush()
        os.fsync(handle.fileno())
    temporary.replace(path)


def read_json_safe(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return payload if isinstance(payload, dict) else {}


def read_jsonl(path: Path) -> tuple[list[dict[str, Any]], int]:
    """Valid records plus the number of unreadable lines (e.g. a torn last write)."""
    records: list[dict[str, Any]] = []
    bad = 0
    try:
        data = path.read_bytes()
    except OSError:
        return records, 0
    for line in data.split(b"\n"):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except ValueError:
            bad += 1
            continue
        if isinstance(record, dict):
            records.append(record)
        else:
            bad += 1
    return records, bad


def repair_jsonl(path: Path) -> int:
    """Drop a torn trailing record so appends start on a clean line. Returns bytes cut."""
    try:
        data = path.read_bytes()
    except OSError:
        return 0
    if not data or data.endswith(b"\n"):
        # Complete lines only. A garbage complete line is left for read_jsonl to skip.
        return 0
    cut = data.rfind(b"\n") + 1
    with path.open("r+b") as handle:
        handle.truncate(cut)
    return len(data) - cut


class JsonlWriter:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        repair_jsonl(path)
        self._handle = path.open("ab")

    def append(self, record: dict[str, Any]) -> None:
        self._handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True).encode() + b"\n")
        self._handle.flush()
        os.fsync(self._handle.fileno())

    def close(self) -> None:
        self._handle.close()


@contextmanager
def file_lock(path: Path, *, blocking: bool = True) -> Iterator[bool]:
    """Advisory flock. Yields False (without holding) when non-blocking and busy."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | (0 if blocking else fcntl.LOCK_NB))
        except BlockingIOError:
            yield False
            return
        try:
            yield True
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def lock_is_held(path: Path) -> bool:
    if not path.exists():
        return False
    with file_lock(path, blocking=False) as acquired:
        return not acquired


class QaDir:
    """Paths of one QA run: ``<run>/visual_qa/<qa_id>/``."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self.manifest = self.path / "manifest.json"
        self.state = self.path / "state.json"
        self.frames = self.path / "frames.jsonl"
        self.clips = self.path / "clips.jsonl"
        self.errors = self.path / "errors.jsonl"
        self.findings = self.path / "findings.json"
        self.summary = self.path / "summary.json"
        self.report = self.path / "report.html"
        self.evidence = self.path / "evidence"
        self.worker_lock = self.path / "worker.lock"

    @property
    def qa_id(self) -> str:
        return self.path.name

    def read_state(self) -> dict[str, Any]:
        return read_json_safe(self.state)

    def write_state(self, **fields: Any) -> dict[str, Any]:
        state = {**self.read_state(), **fields, "updated_at": utc_now()}
        write_json_atomic(self.state, state)
        return state

    def worker_alive(self) -> bool:
        return lock_is_held(self.worker_lock)
