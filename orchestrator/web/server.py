from __future__ import annotations

import os
import json
from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, StrictInt, StrictStr

from orchestrator import paths
from orchestrator.app_front.settings import AppSettings, SettingsError, SettingsStore
from orchestrator.cli import start_run
from orchestrator.disks import DiskUnmountError, MOUNT_ROOT, list_mounted_disks, unmount_disk
from orchestrator.spec import SpecError
from orchestrator.web.progress import list_artifacts, load_run_progress
from orchestrator.web.registry import ConsoleRegistry, create_project
from orchestrator.web.sources import list_source_candidates

STATIC_DIR = Path(__file__).resolve().parents[1] / "app_front" / "static"
DEFAULT_PRESET_DIRS = ("00_Master", "01_Footage", "02_Comp", "07_ETC_DATA")


class ProjectCreatePayload(BaseModel):
    name: str
    replica_roots: list[str]
    source_paths: list[str] | None = None
    preset_name: str = "default"


class RunCreatePayload(BaseModel):
    project_id: str
    shoot_date: str
    camera_unit: str
    source_path: str | None = None
    source_paths: list[str] | None = None
    replica_roots: list[str] | None = None
    profile: str = paths.DEFAULT_HERMES_PROFILE


class RollPreviewPayload(BaseModel):
    project_id: str
    shoot_date: str
    camera_unit: str
    replica_roots: list[str] | None = None


class ConsoleSettingsPayload(BaseModel):
    preferred_port: StrictInt


class AppSettingsPayload(BaseModel):
    bind_host: str = "127.0.0.1"
    preferred_port: StrictInt


class DiskUnmountPayload(BaseModel):
    path: StrictStr


def create_app(
    *,
    registry_path: Path | None = None,
    source_roots: tuple[Path, ...] | None = None,
    destination_roots: tuple[Path, ...] | None = None,
    runs_root: Path | None = None,
    settings_store: SettingsStore | None = None,
    disk_root: Path | None = None,
) -> FastAPI:
    active_registry_path = registry_path or paths.PIPELINE_ROOT / "console-registry.json"
    active_source_roots = source_roots or _source_roots_from_env()
    active_destination_roots = destination_roots or source_roots or _destination_roots_from_env()
    active_runs_root = runs_root or paths.RUNS_ROOT
    active_settings_store = settings_store or SettingsStore()
    active_disk_root = disk_root or MOUNT_ROOT
    registry = ConsoleRegistry(active_registry_path)

    app = FastAPI(title="Data Handler", version="0.1.0")
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    @app.get("/", include_in_schema=False)
    def home() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")

    @app.get("/api/console/health")
    def health() -> dict[str, str]:
        return {
            "status": "ok",
            "registry_path": str(active_registry_path),
            "runs_root": str(active_runs_root),
        }

    @app.get("/api/app/state")
    def app_state(request: Request) -> dict[str, Any]:
        payload = _app_settings_payload(active_settings_store, request)
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

    @app.get("/api/app/settings")
    def app_settings(request: Request) -> dict[str, Any]:
        return _app_settings_payload(active_settings_store, request)

    @app.put("/api/app/settings")
    def update_app_settings(payload: AppSettingsPayload, request: Request) -> dict[str, Any]:
        try:
            active_settings_store.save(
                AppSettings(
                    bind_host=payload.bind_host,
                    preferred_port=payload.preferred_port,
                )
            )
        except SettingsError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return _app_settings_payload(active_settings_store, request)

    @app.get("/api/console/settings")
    def console_settings(request: Request) -> dict[str, Any]:
        return _console_settings_payload(active_settings_store, request)

    @app.put("/api/console/settings")
    def update_console_settings(payload: ConsoleSettingsPayload, request: Request) -> dict[str, Any]:
        try:
            active_settings_store.save(
                AppSettings(
                    preferred_port=payload.preferred_port,
                )
            )
        except SettingsError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return _console_settings_payload(active_settings_store, request)

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
    def disks() -> dict[str, Any]:
        return {"disks": list_mounted_disks(active_disk_root)}

    @app.post("/api/disks/unmount")
    def unmount_disk_compat(payload: DiskUnmountPayload) -> dict[str, Any]:
        return _unmount_disk_payload(payload, active_disk_root)

    @app.get("/api/app/disks")
    def app_disks() -> dict[str, Any]:
        return {"disks": list_mounted_disks(active_disk_root)}

    @app.post("/api/app/disks/unmount")
    def unmount_app_disk(payload: DiskUnmountPayload) -> dict[str, Any]:
        return _unmount_disk_payload(payload, active_disk_root)

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
        progress = _progress_with_steps(load_run_progress(_safe_run_dir(active_runs_root, run_id)))
        registry.sync_run_progress(run_id, progress)
        payload = registry.load()
        for run in payload.get("runs", []):
            if isinstance(run, dict) and run.get("run_id") == run_id:
                project = _find_project(payload, str(run["project_id"]))
                return {
                    "run": run,
                    "project": project,
                    "progress": progress,
                    "artifacts": [
                        _artifact_payload(run_id, artifact)
                        for artifact in _safe_artifacts(_safe_run_dir(active_runs_root, run_id))
                    ],
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
        return {
            "artifacts": [
                _artifact_payload(run_id, artifact)
                for artifact in _safe_artifacts(run_dir)
            ]
        }

    @app.get("/artifacts/{run_id}/{artifact_name}", include_in_schema=False)
    def artifact_file(run_id: str, artifact_name: str) -> FileResponse:
        if "/" in artifact_name or "\\" in artifact_name:
            raise HTTPException(status_code=404, detail="artifact not found")
        run_dir = _safe_run_dir(active_runs_root, run_id)
        direct = run_dir / artifact_name
        direct_path = direct.resolve()
        if direct_path.is_file() and _path_within(direct_path, run_dir.resolve()):
            return FileResponse(direct_path, filename=artifact_name)
        for artifact in _safe_artifacts(run_dir):
            artifact_path = Path(artifact["path"])
            if artifact_path.name == artifact_name and artifact_path.is_file():
                return FileResponse(artifact_path, filename=artifact_name)
        raise HTTPException(status_code=404, detail="artifact not found")

    return app


def _console_settings_payload(settings_store: SettingsStore, request: Request) -> dict[str, Any]:
    settings_error = ""
    try:
        settings = settings_store.load()
    except SettingsError as exc:
        settings = AppSettings()
        settings_error = str(exc)
    current_port = request.url.port
    return {
        "settings": _settings_payload(settings),
        "settings_error": settings_error,
        "settings_path": str(settings_store.path),
        "server": {
            "state": "running",
            "url": str(request.base_url).rstrip("/"),
            "port": current_port,
            "pid": os.getpid(),
            "restart_required": current_port != settings.preferred_port,
        },
    }


def _app_settings_payload(settings_store: SettingsStore, request: Request) -> dict[str, Any]:
    payload = _console_settings_payload(settings_store, request)
    settings = payload["settings"]
    return {
        "settings": {
            "bind_host": "127.0.0.1",
            "preferred_port": settings["preferred_port"],
        },
        "settings_error": payload["settings_error"],
        "server": payload["server"],
    }


def _settings_payload(settings: AppSettings) -> dict[str, Any]:
    return {
        "preferred_port": settings.preferred_port,
    }


def _source_roots_from_env() -> tuple[Path, ...]:
    configured = os.environ.get("DIT_CONSOLE_SOURCE_ROOTS")
    if configured:
        return tuple(Path(value).expanduser() for value in configured.split(os.pathsep) if value)
    return (Path("/Volumes"), Path.home())


def _destination_roots_from_env() -> tuple[Path, ...]:
    configured = os.environ.get("DIT_CONSOLE_DESTINATION_ROOTS")
    if configured:
        return tuple(Path(value).expanduser() for value in configured.split(os.pathsep) if value)
    return _source_roots_from_env()


def _runtime_payload(
    *,
    registry_path: Path,
    runs_root: Path,
    settings_store: SettingsStore,
    settings_error: str,
) -> dict[str, Any]:
    checks: list[dict[str, str]] = []
    errors: list[str] = []

    _append_check(
        checks,
        errors,
        "registry_path",
        str(registry_path),
        lambda: _validate_registry_path(registry_path),
    )
    _append_check(
        checks,
        errors,
        "runs_root",
        str(runs_root),
        lambda: _validate_writable_directory(runs_root),
    )
    _append_check(
        checks,
        errors,
        "settings",
        str(settings_store.path),
        lambda: _validate_settings_path(settings_store.path, settings_error),
    )
    return {
        "status": "error" if errors else "ok",
        "registry_path": str(registry_path),
        "runs_root": str(runs_root),
        "settings_path": str(settings_store.path),
        "pid": os.getpid(),
        "checks": checks,
        "errors": errors,
    }


def _append_check(
    checks: list[dict[str, str]],
    errors: list[str],
    name: str,
    path: str,
    validator: Any,
) -> None:
    try:
        validator()
    except Exception as exc:
        message = f"{name} unavailable: {exc}"
        errors.append(message)
        checks.append({"name": name, "path": path, "status": "error", "error": str(exc)})
    else:
        checks.append({"name": name, "path": path, "status": "ok"})


def _validate_registry_path(registry_path: Path) -> None:
    _validate_writable_directory(registry_path.parent)
    if registry_path.exists():
        payload = json.loads(registry_path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("registry file must contain a JSON object")


def _validate_settings_path(settings_path: Path, settings_error: str) -> None:
    _validate_writable_directory(settings_path.parent)
    if settings_error:
        raise ValueError(settings_error)


def _validate_writable_directory(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    if not path.is_dir():
        raise ValueError(f"not a directory: {path}")
    probe = path / ".data-handler-write-test"
    probe.write_text("", encoding="utf-8")
    probe.unlink(missing_ok=True)


def _find_project(payload: dict[str, Any], project_id: str) -> dict[str, Any]:
    for project in payload.get("projects", []):
        if isinstance(project, dict) and project.get("id") == project_id:
            return project
    raise HTTPException(status_code=404, detail=f"project not found: {project_id}")


def _validated_source_path(source_path: str, source_roots: tuple[Path, ...]) -> Path:
    source = Path(source_path).expanduser().resolve()
    if not source.is_dir():
        raise HTTPException(status_code=400, detail=f"source is unavailable: {source}")
    roots = tuple(root.expanduser().resolve() for root in source_roots)
    if not any(_path_within(source, root) for root in roots):
        raise HTTPException(status_code=400, detail=f"source is outside allowed roots: {source}")
    return source


def _validated_source_paths(payload: RunCreatePayload, source_roots: tuple[Path, ...]) -> tuple[Path, ...]:
    values = payload.source_paths or ([payload.source_path] if payload.source_path else [])
    sources = tuple(_validated_source_path(value, source_roots) for value in values if value)
    if not sources:
        raise HTTPException(status_code=400, detail="at least one source is required")
    if len(set(sources)) != len(sources):
        raise HTTPException(status_code=400, detail="source paths must be unique")
    return sources


def _selected_replica_roots(
    project: dict[str, Any],
    requested_roots: list[str] | None,
) -> tuple[Path, ...]:
    values = requested_roots or [str(path) for path in project["replica_roots"]]
    roots = tuple(Path(value).expanduser().resolve() for value in values if value)
    if not roots:
        raise HTTPException(status_code=400, detail="at least one destination is required")
    if len(set(roots)) != len(roots):
        raise HTTPException(status_code=400, detail="destination paths must be unique")
    return roots


def _validate_replica_roots(replica_roots: tuple[Path, ...], sources: tuple[Path, ...]) -> None:
    for root in replica_roots:
        if not root.is_dir():
            raise HTTPException(status_code=400, detail=f"destination is unavailable: {root}")
    if set(replica_roots) & set(sources):
        raise HTTPException(status_code=400, detail="source and destination paths must be different")


def _unmount_disk_payload(payload: DiskUnmountPayload, disk_root: Path) -> dict[str, Any]:
    try:
        result = unmount_disk(payload.path, mount_root=disk_root)
    except DiskUnmountError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {
        **result,
        "disks": list_mounted_disks(disk_root),
    }


def _safe_run_dir(runs_root: Path, run_id: str) -> Path:
    if not run_id or run_id in {".", ".."} or "/" in run_id or "\\" in run_id:
        raise HTTPException(status_code=404, detail=f"run not found: {run_id}")
    root = runs_root.resolve()
    run_dir = (root / run_id).resolve()
    if root != run_dir and root not in run_dir.parents:
        raise HTTPException(status_code=404, detail=f"run not found: {run_id}")
    return run_dir


def _artifact_payload(run_id: str, artifact: dict[str, str]) -> dict[str, str]:
    path = Path(artifact["path"])
    return {
        **artifact,
        "url": f"/artifacts/{run_id}/{path.name}",
    }


def _safe_artifacts(run_dir: Path) -> list[dict[str, str]]:
    allowed_roots = _artifact_allowed_roots(run_dir)
    safe: list[dict[str, str]] = []
    for artifact in list_artifacts(run_dir):
        artifact_path = Path(artifact["path"]).resolve()
        if not artifact_path.is_file():
            continue
        if not any(_path_within(artifact_path, root) for root in allowed_roots):
            continue
        safe.append({**artifact, "path": str(artifact_path)})
    return safe


def _artifact_allowed_roots(run_dir: Path) -> list[Path]:
    roots = [run_dir.resolve()]
    done_path = run_dir / "events" / "datamanager.done.json"
    if done_path.exists():
        import json

        done = json.loads(done_path.read_text(encoding="utf-8"))
        replica_roots = done.get("replica_project_roots", {})
        if isinstance(replica_roots, dict):
            for root in replica_roots.values():
                roots.append(Path(str(root)).resolve())
    return roots


def _path_within(path: Path, root: Path) -> bool:
    return root == path or root in path.parents


def _progress_with_steps(progress: dict[str, Any]) -> dict[str, Any]:
    if "steps" in progress:
        return progress
    status = str(progress.get("status", ""))
    payload = {
        **progress,
        "steps": _steps_for_stage(str(progress.get("stage", "")), status),
    }
    if "percent" not in payload:
        percent = _percent_from_progress(progress)
        if percent is not None:
            payload["percent"] = percent
    if status in {"failed", "error", "review-needed"} and "percent" not in payload:
        payload["percent"] = 0
    return payload


def _percent_from_progress(progress: dict[str, Any]) -> int | None:
    current = _number(progress.get("current"))
    total = _number(progress.get("total"))
    if current is not None and total and total > 0:
        return max(0, min(100, round((current / total) * 100)))
    completed = _number(progress.get("completed") or progress.get("report_completed"))
    report_total = _number(progress.get("report_total"))
    if completed is not None and report_total and report_total > 0:
        return max(0, min(100, round((completed / report_total) * 100)))
    return None


def _number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return None


def _steps_for_stage(stage: str, status: str) -> list[dict[str, str]]:
    names = ("setup", "copy", "checksum", "reports", "finalization", "done")
    if stage in {"datahelper", "reports"}:
        active = "reports"
    elif stage in {"datamanager", "copy", "copy-checksum"}:
        active = "copy"
    elif stage == "finalization":
        active = "finalization"
    elif stage == "done":
        active = "done"
    else:
        active = "setup"
    completed = status in {"completed", "done"}
    failed = status in {"failed", "error", "review-needed"}
    steps: list[dict[str, str]] = []
    active_seen = False
    for name in names:
        if failed:
            state = "failed" if name == active else "pending"
        elif completed:
            state = "done"
        elif name == active:
            state = "current"
            active_seen = True
        elif active_seen:
            state = "pending"
        else:
            state = "done"
        steps.append({"name": name, "status": state})
    return steps
