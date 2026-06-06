from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Callable
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, StrictInt, StrictStr

from orchestrator import paths
from orchestrator.disks import DiskUnmountError, MOUNT_ROOT, list_mounted_disks, unmount_disk
from orchestrator.app_front.settings import AppSettings, SettingsError, SettingsStore
from orchestrator.cli import start_run
from orchestrator.spec import SpecError
from orchestrator.web.progress import list_artifacts, load_run_progress
from orchestrator.web.registry import ConsoleRegistry, create_project
from orchestrator.web.server import (
    DEFAULT_PRESET_DIRS,
    RollPreviewPayload,
    RunCreatePayload,
    ProjectCreatePayload,
    _artifact_payload,
    _find_project,
    _path_within,
    _progress_with_steps,
    _safe_artifacts,
    _safe_run_dir,
    _selected_replica_roots,
    _destination_roots_from_env,
    _source_roots_from_env,
    _validate_replica_roots,
    _validated_source_path,
    _validated_source_paths,
    _runtime_payload,
)
from orchestrator.web.sources import list_source_candidates

STATIC_DIR = Path(__file__).resolve().parent / "static"


class SettingsPayload(BaseModel):
    bind_host: StrictStr = "127.0.0.1"
    preferred_port: StrictInt


class DiskUnmountPayload(BaseModel):
    path: StrictStr


def create_app(
    settings_store: SettingsStore | None = None,
    disk_root: Path | None = None,
    disk_classifier: Callable[[Path], str] | None = None,
    registry_path: Path | None = None,
    source_roots: tuple[Path, ...] | None = None,
    destination_roots: tuple[Path, ...] | None = None,
    runs_root: Path | None = None,
) -> FastAPI:
    active_settings_store = settings_store or SettingsStore()
    active_disk_root = disk_root or MOUNT_ROOT
    active_disk_classifier = disk_classifier
    active_registry_path = registry_path or paths.PIPELINE_ROOT / "console-registry.json"
    active_source_roots = source_roots or _source_roots_from_env()
    active_destination_roots = destination_roots or source_roots or _destination_roots_from_env()
    active_runs_root = runs_root or paths.RUNS_ROOT
    registry = ConsoleRegistry(active_registry_path)

    app = FastAPI(title="Data Handler", version="0.1.0")
    app.mount("/static", StaticFiles(directory=STATIC_DIR, check_dir=False), name="static")

    @app.get("/", include_in_schema=False)
    def home() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")

    @app.get("/api/app/state")
    def state(request: Request) -> dict[str, Any]:
        payload = _state_payload(active_settings_store, request)
        settings_error = str(payload.get("settings_error") or "")
        return {
            **payload,
            "runtime": _runtime_payload(
                registry_path=active_registry_path,
                runs_root=active_runs_root,
                settings_store=active_settings_store,
                settings_error=settings_error,
            ),
        }

    @app.get("/api/projects")
    def projects() -> dict[str, Any]:
        return registry.load()

    @app.get("/api/projects/{project_id}")
    def project_detail(project_id: str) -> dict[str, Any]:
        payload = registry.load()
        project = _find_project(payload, project_id)
        return {
            "project": project,
            "runs": [run for run in payload.get("runs", []) if run.get("project_id") == project_id],
        }

    @app.post("/api/projects")
    def create_project_route(payload: ProjectCreatePayload) -> dict[str, Any]:
        try:
            source_paths = tuple(
                _validated_source_path(path, active_source_roots)
                for path in (payload.source_paths or [])
            )
            project = create_project(
                registry=registry,
                name=payload.name,
                replica_roots=tuple(Path(path).expanduser() for path in payload.replica_roots),
                source_paths=source_paths,
                preset_name=payload.preset_name,
                preset_dirs=DEFAULT_PRESET_DIRS,
            )
        except SpecError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"project": project.to_payload()}

    @app.get("/api/sources")
    def sources() -> dict[str, Any]:
        return {"sources": list_source_candidates(active_source_roots)}

    @app.get("/api/destinations")
    def destinations() -> dict[str, Any]:
        return {"destinations": list_source_candidates(active_destination_roots)}

    @app.get("/api/disks")
    def disks_compat() -> dict[str, Any]:
        return {"disks": list_mounted_disks(active_disk_root, disk_classifier=active_disk_classifier)}

    @app.post("/api/disks/unmount")
    def unmount_disk_compat(payload: DiskUnmountPayload) -> dict[str, Any]:
        return _unmount_disk_payload(payload, active_disk_root, active_disk_classifier)

    @app.post("/api/roll-preview")
    def roll_preview(payload: RollPreviewPayload) -> dict[str, Any]:
        try:
            project = registry.find_project(payload.project_id)
            if project is None:
                raise KeyError(payload.project_id)
            replica_roots = _selected_replica_roots(project, payload.replica_roots)
            preview = registry.preview_roll(
                payload.project_id,
                payload.shoot_date,
                payload.camera_unit,
                replica_roots=replica_roots,
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=f"project not found: {payload.project_id}") from exc
        project = preview["project"]
        replica_project_roots = [root / str(project["name"]) for root in replica_roots]
        return {
            "project_id": payload.project_id,
            "project_name": project["name"],
            "shoot_date": payload.shoot_date,
            "camera_unit": payload.camera_unit,
            "roll": preview["roll"],
            "footage_run_name": preview["footage_run_name"],
            "replica_destinations": [
                str(Path(str(root)) / "01_Footage" / preview["footage_run_name"])
                for root in replica_project_roots
            ],
        }

    @app.post("/api/runs")
    def create_run(payload: RunCreatePayload) -> dict[str, str]:
        registry_payload = registry.load()
        project = _find_project(registry_payload, payload.project_id)
        sources = _validated_source_paths(payload, active_source_roots)
        replica_roots = _selected_replica_roots(project, payload.replica_roots)
        _validate_replica_roots(replica_roots, sources)
        run_id = f"run-{uuid4().hex[:12]}"
        record = registry.reserve_run(
            project_id=payload.project_id,
            shoot_date=payload.shoot_date,
            camera_unit=payload.camera_unit,
            run_id=run_id,
            source_path=str(sources[0]),
            source_paths=tuple(str(source) for source in sources),
            replica_roots=replica_roots,
        )
        try:
            start_run(
                source_paths=sources,
                replica_paths=replica_roots,
                project_name=str(project["name"]),
                profile=payload.profile,
                run_id=run_id,
                footage_run_name=f"{payload.shoot_date}/{payload.camera_unit}/{record.roll}",
            )
        except Exception as exc:
            registry.mark_run_failed(run_id, str(exc))
            raise HTTPException(status_code=500, detail=f"failed to start run: {exc}") from exc
        registry.mark_run_started(run_id)
        return {"run_id": run_id, "roll": record.roll}

    @app.get("/api/runs/{run_id}")
    def run_detail(run_id: str) -> dict[str, Any]:
        run_dir = _safe_run_dir(active_runs_root, run_id)
        progress = _progress_with_steps(load_run_progress(run_dir))
        registry.sync_run_progress(run_id, progress)
        payload = registry.load()
        for run in payload.get("runs", []):
            if isinstance(run, dict) and run.get("run_id") == run_id:
                project = _find_project(payload, str(run["project_id"]))
                return {
                    "run": run,
                    "project": project,
                    "progress": progress,
                    "artifacts": [_artifact_payload(run_id, artifact) for artifact in _safe_artifacts(run_dir)],
                }
        raise HTTPException(status_code=404, detail=f"run not found: {run_id}")

    @app.get("/api/runs/{run_id}/progress")
    def run_progress(run_id: str) -> dict[str, Any]:
        progress = _progress_with_steps(load_run_progress(_safe_run_dir(active_runs_root, run_id)))
        registry.sync_run_progress(run_id, progress)
        return progress

    @app.get("/api/runs/{run_id}/artifacts")
    def run_artifacts(run_id: str) -> dict[str, Any]:
        run_dir = _safe_run_dir(active_runs_root, run_id)
        return {"artifacts": [_artifact_payload(run_id, artifact) for artifact in _safe_artifacts(run_dir)]}

    @app.get("/artifacts/{run_id}/{artifact_name}", include_in_schema=False)
    def artifact_file(run_id: str, artifact_name: str) -> FileResponse:
        if "/" in artifact_name or "\\" in artifact_name:
            raise HTTPException(status_code=404, detail="artifact not found")
        run_dir = _safe_run_dir(active_runs_root, run_id)
        direct_path = (run_dir / artifact_name).resolve()
        if direct_path.is_file() and _path_within(direct_path, run_dir.resolve()):
            return FileResponse(direct_path, filename=artifact_name)
        for artifact in _safe_artifacts(run_dir):
            artifact_path = Path(artifact["path"])
            if artifact_path.name == artifact_name and artifact_path.is_file():
                return FileResponse(artifact_path, filename=artifact_name)
        raise HTTPException(status_code=404, detail="artifact not found")

    @app.get("/api/app/settings")
    def settings() -> dict[str, Any]:
        return _settings_response(active_settings_store)

    @app.get("/api/app/disks")
    def disks() -> dict[str, Any]:
        return {"disks": list_mounted_disks(active_disk_root, disk_classifier=active_disk_classifier)}

    @app.post("/api/app/disks/unmount")
    def unmount_app_disk(payload: DiskUnmountPayload) -> dict[str, Any]:
        return _unmount_disk_payload(payload, active_disk_root, active_disk_classifier)

    @app.put("/api/app/settings")
    def update_settings(payload: SettingsPayload) -> dict[str, Any]:
        try:
            active_settings_store.save(
                AppSettings(
                    bind_host=payload.bind_host,
                    preferred_port=payload.preferred_port,
                )
            )
        except SettingsError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return _settings_response(active_settings_store)

    return app


def _state_payload(settings_store: SettingsStore, request: Request) -> dict[str, Any]:
    payload = {
        **_settings_response(settings_store),
        "server": {
            "state": "running",
            "host": request.url.hostname,
            "url": str(request.base_url).rstrip("/"),
            "port": request.url.port,
            "pid": os.getpid(),
            "error": None,
        },
    }
    return payload


def _settings_response(settings_store: SettingsStore) -> dict[str, Any]:
    try:
        settings = settings_store.load()
    except SettingsError as exc:
        return {
            "settings": _settings_payload(AppSettings()),
            "settings_error": str(exc),
        }
    return {"settings": _settings_payload(settings)}


def _unmount_disk_payload(
    payload: DiskUnmountPayload,
    disk_root: Path,
    disk_classifier: Callable[[Path], str] | None,
) -> dict[str, Any]:
    try:
        result = unmount_disk(payload.path, mount_root=disk_root, disk_classifier=disk_classifier)
    except DiskUnmountError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {
        **result,
        "disks": list_mounted_disks(disk_root, disk_classifier=disk_classifier),
    }


def _settings_payload(settings: AppSettings) -> dict[str, Any]:
    return {
        "bind_host": settings.bind_host,
        "preferred_port": settings.preferred_port,
    }
