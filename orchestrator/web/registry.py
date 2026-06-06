from __future__ import annotations

import json
import re
from contextlib import contextmanager
from pathlib import Path
from typing import Any
from uuid import uuid4

import fcntl

from orchestrator.spec import SpecError
from orchestrator.run_state import utc_now
from orchestrator.web.models import ConsoleProject, ConsoleRunRecord

PROJECT_MANIFEST = ".dit-console-project.json"


class ConsoleRegistry:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.lock_path = path.with_suffix(path.suffix + ".lock")

    @contextmanager
    def _locked(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.lock_path.open("w", encoding="utf-8") as lock_file:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)

    def load(self) -> dict[str, Any]:
        if not self.path.exists():
            return {"projects": [], "runs": []}
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        payload.setdefault("projects", [])
        payload.setdefault("runs", [])
        return payload

    def save(self, payload: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    def add_project(self, project: ConsoleProject) -> None:
        with self._locked():
            payload = self.load()
            payload["projects"].append(project.to_payload())
            self.save(payload)

    def allocate_next_roll(self, project_id: str, shoot_date: str, camera_unit: str) -> str:
        with self._locked():
            payload = self.load()
            project = _find_project_payload(payload, project_id)
            return _next_roll(payload, project, shoot_date, camera_unit)

    def preview_roll(
        self,
        project_id: str,
        shoot_date: str,
        camera_unit: str,
        replica_roots: tuple[Path, ...] | None = None,
    ) -> dict[str, Any]:
        with self._locked():
            payload = self.load()
            project = _find_project_payload(payload, project_id)
            roll_project = _project_with_replica_roots(project, replica_roots)
            roll = _next_roll(payload, roll_project, shoot_date, camera_unit)
            return {
                "project": project,
                "shoot_date": shoot_date,
                "camera_unit": camera_unit,
                "roll": roll,
                "footage_run_name": f"{shoot_date}/{camera_unit}/{roll}",
            }

    def find_project(self, project_id: str) -> dict[str, Any] | None:
        for project in self.load().get("projects", []):
            if isinstance(project, dict) and project.get("id") == project_id:
                return project
        return None

    def record_run(
        self,
        *,
        project_id: str,
        shoot_date: str,
        camera_unit: str,
        roll: str,
        run_id: str,
        source_path: str,
    ) -> ConsoleRunRecord:
        record = ConsoleRunRecord(
            project_id=project_id,
            shoot_date=shoot_date,
            camera_unit=camera_unit,
            roll=roll,
            run_id=run_id,
            source_path=source_path,
            source_paths=(source_path,),
            created_at=utc_now(),
        )
        with self._locked():
            payload = self.load()
            payload["runs"].append(record.to_payload())
            self.save(payload)
            project = _find_project_payload(payload, project_id)
            _write_project_manifest(_project_from_payload(project), payload)
        return record

    def reserve_run(
        self,
        *,
        project_id: str,
        shoot_date: str,
        camera_unit: str,
        run_id: str,
        source_path: str,
        source_paths: tuple[str, ...] | None = None,
        replica_roots: tuple[Path, ...] | None = None,
    ) -> ConsoleRunRecord:
        with self._locked():
            payload = self.load()
            project = _find_project_payload(payload, project_id)
            roll_project = _project_with_replica_roots(project, replica_roots)
            active_source_paths = source_paths or (source_path,)
            roll = _next_roll(payload, roll_project, shoot_date, camera_unit)
            record = ConsoleRunRecord(
                project_id=project_id,
                shoot_date=shoot_date,
                camera_unit=camera_unit,
                roll=roll,
                run_id=run_id,
                source_path=active_source_paths[0],
                source_paths=active_source_paths,
                created_at=utc_now(),
            )
            payload["runs"].append(record.to_payload())
            payload["runs"][-1]["status"] = "reserved"
            self.save(payload)
            _write_project_manifest(_project_from_payload(project), payload)
            return record

    def mark_run_started(self, run_id: str) -> None:
        self._update_run_status(run_id, status="started", error=None)

    def mark_run_failed(self, run_id: str, error: str) -> None:
        self._update_run_status(run_id, status="failed", error=error)

    def sync_run_progress(self, run_id: str, progress: dict[str, Any]) -> None:
        status = _registry_status_from_progress(progress)
        if status is None:
            return
        error = None
        if status == "failed":
            error = str(progress.get("last_error") or progress.get("error") or "")
        self._update_run_status(run_id, status=status, error=error or None)

    def _update_run_status(self, run_id: str, *, status: str, error: str | None) -> None:
        with self._locked():
            payload = self.load()
            project_id: str | None = None
            for run in payload.get("runs", []):
                if isinstance(run, dict) and run.get("run_id") == run_id:
                    run["status"] = status
                    run["updated_at"] = utc_now()
                    if error:
                        run["error"] = error
                    else:
                        run.pop("error", None)
                    project_id = str(run.get("project_id", ""))
                    break
            else:
                return
            self.save(payload)
            if project_id:
                project = _find_project_payload(payload, project_id)
                _write_project_manifest(_project_from_payload(project), payload)

    def _refresh_project_manifest(self, project_id: str) -> None:
        payload = self.load()
        for project_payload in payload["projects"]:
            if project_payload.get("id") == project_id:
                _write_project_manifest(_project_from_payload(project_payload), payload)
                return


def create_project(
    *,
    registry: ConsoleRegistry,
    name: str,
    replica_roots: tuple[Path, ...],
    source_paths: tuple[Path, ...] = (),
    preset_name: str,
    preset_dirs: tuple[str, ...],
) -> ConsoleProject:
    _validate_project_name(name)
    resolved_source_paths = tuple(path.resolve() for path in source_paths)
    if len(set(resolved_source_paths)) != len(resolved_source_paths):
        raise SpecError("source paths must be unique")
    resolved_replica_roots = tuple(path.resolve() for path in replica_roots)
    if not resolved_replica_roots:
        raise SpecError("at least one replica root is required")
    if len(set(resolved_replica_roots)) != len(resolved_replica_roots):
        raise SpecError("replica roots must be unique")
    if set(resolved_source_paths) & set(resolved_replica_roots):
        raise SpecError("source and replica roots must be different")
    project_id = f"proj-{uuid4().hex[:12]}"
    now = utc_now()
    replica_project_roots = tuple((root / name).resolve() for root in resolved_replica_roots)
    for root, project_root in zip(resolved_replica_roots, replica_project_roots, strict=True):
        _ensure_child(root, project_root)

    for root in replica_project_roots:
        root.mkdir(parents=True, exist_ok=True)
        for dirname in preset_dirs:
            (root / dirname).mkdir(parents=True, exist_ok=True)

    project = ConsoleProject(
        id=project_id,
        name=name,
        replica_roots=resolved_replica_roots,
        replica_project_roots=replica_project_roots,
        preset_name=preset_name,
        created_at=now,
        updated_at=now,
        source_paths=resolved_source_paths,
    )
    registry.add_project(project)
    _write_project_manifest(project, registry.load())
    return project


def _project_from_payload(payload: dict[str, Any]) -> ConsoleProject:
    return ConsoleProject(
        id=str(payload["id"]),
        name=str(payload["name"]),
        replica_roots=tuple(Path(str(path)) for path in payload["replica_roots"]),
        replica_project_roots=tuple(
            Path(str(path)) for path in payload["replica_project_roots"]
        ),
        preset_name=str(payload["preset_name"]),
        created_at=str(payload["created_at"]),
        updated_at=str(payload["updated_at"]),
        source_paths=tuple(Path(str(path)) for path in payload.get("source_paths", [])),
    )


def _write_project_manifest(project: ConsoleProject, registry_payload: dict[str, Any]) -> None:
    manifest = {
        "project": project.to_payload(),
        "runs": [run for run in registry_payload.get("runs", []) if run.get("project_id") == project.id],
    }
    for root in project.replica_project_roots:
        root.mkdir(parents=True, exist_ok=True)
        (root / PROJECT_MANIFEST).write_text(
            json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )


def _validate_project_name(name: str) -> None:
    value = name.strip()
    if not value:
        raise SpecError("project name is required")
    if value in {".", ".."} or "/" in value or "\\" in value or "\x00" in value:
        raise SpecError("project name cannot contain path separators")


def _ensure_child(parent: Path, child: Path) -> None:
    if parent != child and parent not in child.parents:
        raise SpecError(f"project root escapes destination root: {child}")


def _find_project_payload(payload: dict[str, Any], project_id: str) -> dict[str, Any]:
    for project in payload.get("projects", []):
        if isinstance(project, dict) and project.get("id") == project_id:
            return project
    raise KeyError(project_id)


def _registry_status_from_progress(progress: dict[str, Any]) -> str | None:
    stage = str(progress.get("stage", "")).lower()
    status = str(progress.get("status", "")).lower()
    if status in {"failed", "error"}:
        return "failed"
    if status in {"warn", "review-needed"}:
        return "review-needed"
    if status in {"completed", "done"} and stage in {"done", "datahelper", "reports"}:
        return "completed"
    return None


def _project_with_replica_roots(
    project: dict[str, Any],
    replica_roots: tuple[Path, ...] | None,
) -> dict[str, Any]:
    if replica_roots is None:
        return project
    copy = dict(project)
    copy["replica_roots"] = [str(path) for path in replica_roots]
    copy["replica_project_roots"] = [
        str((path / str(project["name"])).resolve()) for path in replica_roots
    ]
    return copy


def _next_roll(
    payload: dict[str, Any],
    project: dict[str, Any],
    shoot_date: str,
    camera_unit: str,
) -> str:
    used: list[int] = []
    project_id = str(project["id"])
    for run in payload.get("runs", []):
        if (
            run.get("project_id") == project_id
            and run.get("shoot_date") == shoot_date
            and run.get("camera_unit") == camera_unit
        ):
            match = re.fullmatch(r"R#(\d+)", str(run.get("roll", "")))
            if match:
                used.append(int(match.group(1)))
    for root in project["replica_project_roots"]:
        used.extend(_existing_roll_numbers(Path(str(root)), shoot_date, camera_unit))
    return f"R#{max(used, default=0) + 1}"


def _existing_roll_numbers(project_root: Path, shoot_date: str, camera_unit: str) -> list[int]:
    roll_root = project_root / "01_Footage" / shoot_date / camera_unit
    if not roll_root.is_dir():
        return []
    used: list[int] = []
    for child in roll_root.iterdir():
        if not child.is_dir():
            continue
        match = re.fullmatch(r"R#(\d+)", child.name)
        if match:
            used.append(int(match.group(1)))
    return used
