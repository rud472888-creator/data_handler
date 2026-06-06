from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from orchestrator.jsonio import write_json
from orchestrator.paths import DATA_MANAGER_ROOT
from orchestrator.processes import spawn_python_module
from orchestrator.run_state import events_dir, load_spec, run_dir, update_state, utc_now
from orchestrator.web.progress import write_progress


def run_datamanager(run_id: str) -> dict[str, Any]:
    spec = load_spec(run_id)
    spec.validate()
    update_state(run_id, stage="datamanager", status="running")
    write_progress(
        run_dir(run_id),
        {"stage": "datamanager", "status": "running", "step": "copy-checksum"},
    )
    try:
        payload = _run(spec.run_id)
    except Exception as exc:
        payload = {
            "run_id": run_id,
            "stage": "datamanager",
            "status": "failed",
            "error": str(exc),
            "finished_at": utc_now(),
        }
        update_state(run_id, stage="datamanager", status="failed", error=str(exc))
        write_progress(
            run_dir(run_id),
            {
                "stage": "datamanager",
                "status": "failed",
                "step": "copy-checksum",
                "last_error": str(exc),
            },
        )
    write_json(events_dir(run_id) / "datamanager.done.json", payload)
    if payload.get("status") != "failed":
        write_progress(
            run_dir(run_id),
            {
                "stage": "datamanager",
                "status": str(payload.get("status", "completed")),
                "step": "copy-checksum",
                "file_count": payload.get("file_count"),
                "replica_count": payload.get("replica_count"),
                "report_count": _ready_report_count(payload.get("reports", {})),
                "source_path_ids": payload.get("source_path_ids"),
                "replica_path_ids": payload.get("replica_path_ids"),
                "replicas_complete": payload.get("replicas_complete"),
                "manifest_ready": payload.get("manifest_ready"),
                "checksum_ready": payload.get("checksum_ready"),
            },
        )
        _start_datahelper_once(run_id)
    return payload


def _run(run_id: str) -> dict[str, Any]:
    spec = load_spec(run_id)
    if str(DATA_MANAGER_ROOT) not in sys.path:
        sys.path.insert(0, str(DATA_MANAGER_ROOT))

    from app.config import Settings
    from app.persistence.db import Database
    from app.persistence.repositories import JobFileRepository, JobRepository, ReportRepository
    from app.runtime.agent import RuntimeAgent
    from app.runtime.lifecycle import JobCreateRequest
    from app.runtime.volume_monitor import ConfiguredPathVolumeProvider

    dm_data_dir = run_dir(run_id) / "datamanager"
    source_roots = tuple(path.resolve() for path in spec.source_paths)
    replica_roots = tuple(path.resolve() for path in spec.replica_roots)
    settings = Settings(
        data_dir=dm_data_dir,
        database_path=dm_data_dir / "fdm.sqlite3",
        dev_source_root=source_roots[0],
        allowed_dest_roots=replica_roots,
    )
    agent = RuntimeAgent(settings=settings, database=Database(settings.database_path))
    provider = ConfiguredPathVolumeProvider(source_roots, replica_roots)
    agent.volume_provider = provider
    agent.runner.volume_provider = provider
    agent.initialize()
    snapshot = provider.scan()
    source_path_ids = _path_ids_for(snapshot.sources, source_roots, "source")
    replica_path_ids = _path_ids_for(snapshot.destinations, replica_roots, "destination")
    write_progress(
        run_dir(run_id),
        {
            "stage": "datamanager",
            "status": "running",
            "step": "copy-checksum",
            "source_path_ids": list(source_path_ids),
            "replica_path_ids": list(replica_path_ids),
            "file_count": None,
            "replica_count": len(replica_roots),
        },
    )
    job = agent.lifecycle.create_job(
        JobCreateRequest(
            project_name=spec.project_name,
            source_path_ids=source_path_ids,
            replica_path_ids=replica_path_ids,
            operator_origin="hermes_orchestrator",
            policy={"run_id": run_id, "footage_run_name": spec.footage_run_name},
        )
    )
    agent.run_job(job.job_id)

    with agent.database.session() as connection:
        completed_job = JobRepository(connection).get(job.job_id)
        files = JobFileRepository(connection).list_for_job(job.job_id)
        reports = ReportRepository(connection).list_for_job(job.job_id)
    if completed_job is None:
        raise RuntimeError(f"DataManager job disappeared: {job.job_id}")

    replica_project_roots = {
        _replica_label(index): root / spec.project_name for index, root in enumerate(replica_roots)
    }
    data_manager_path_ids = {
        _replica_label(index): path_id for index, path_id in enumerate(replica_path_ids)
    }
    report_root = replica_project_roots["path1"]
    report_paths = _report_paths(report_root, reports)
    replicas_complete = _replicas_complete(files, replica_project_roots, data_manager_path_ids)
    manifest_ready = Path(report_paths.get("manifest_json", "")).is_file()
    checksum_ready = Path(report_paths.get("checksum_pdf", "")).is_file()
    status = "completed" if completed_job.state == "COMPLETED" and replicas_complete else "warn"
    if completed_job.state == "FAILED":
        status = "failed"
    payload: dict[str, Any] = {
        "run_id": run_id,
        "stage": "datamanager",
        "status": status,
        "job_id": job.job_id,
        "job_state": completed_job.state,
        "replica_project_roots": {
            label: str(root) for label, root in replica_project_roots.items()
        },
        "replica_footage_roots": {
            label: str(_footage_root(replica_project_roots[label], files, path_id))
            for label, path_id in data_manager_path_ids.items()
        },
        "replicas_complete": replicas_complete,
        "manifest_ready": manifest_ready,
        "checksum_ready": checksum_ready,
        "reports": report_paths,
        "file_count": len(files),
        "replica_count": len(replica_roots),
        "source_path_ids": list(source_path_ids),
        "replica_path_ids": list(replica_path_ids),
        "failed_files": [file.source_relpath for file in files if file.status == "failed"],
        "warn_files": [file.source_relpath for file in files if file.status == "warn"],
        "finished_at": utc_now(),
    }
    update_state(run_id, stage="datamanager", status=status)
    return payload


def _replica_label(index: int) -> str:
    return f"path{index + 1}"


def _path_ids_for(volumes: list[Any], roots: tuple[Path, ...], kind: str) -> tuple[str, ...]:
    ids: list[str] = []
    for root in roots:
        root_resolved = root.resolve()
        for volume in volumes:
            if volume.kind == kind and Path(volume.display_path).resolve() == root_resolved:
                ids.append(volume.volume_id)
                break
        else:
            raise RuntimeError(f"{kind} path was not discovered by DataManager runtime: {root}")
    return tuple(ids)


def _report_paths(report_root: Path, reports: list[Any]) -> dict[str, str]:
    paths: dict[str, str] = {}
    for report in reports:
        paths[report.report_type] = str(report_root / report.artifact_relpath)
    return paths


def _ready_report_count(reports: Any) -> int:
    if not isinstance(reports, dict):
        return 0
    return sum(1 for path in reports.values() if Path(str(path)).is_file())


def _replicas_complete(
    files: list[Any],
    project_roots: dict[str, Path],
    data_manager_path_ids: dict[str, str],
) -> bool:
    if not files:
        return False
    for file in files:
        if not file.checksum_source:
            return False
        for label, project_root in project_roots.items():
            path_id = data_manager_path_ids[label]
            replica = _replica_for(file, path_id)
            if replica is None:
                return False
            if replica.status != "verified":
                return False
            if not replica.checksum or replica.checksum != file.checksum_source:
                return False
            if not replica.dest_relpath or not (project_root / replica.dest_relpath).exists():
                return False
    return True


def _replica_for(file: Any, path_id: str) -> Any | None:
    for replica in file.replica_results:
        if replica.path_id == path_id:
            return replica
    return None


def _footage_root(project_root: Path, files: list[Any], path_id: str) -> Path:
    for file in files:
        replica = _replica_for(file, path_id)
        if replica is None or not replica.dest_relpath:
            continue
        parts = Path(replica.dest_relpath).parts
        for index, part in enumerate(parts):
            if part.startswith("R#"):
                return project_root.joinpath(*parts[: index + 1])
    return project_root / "01_Footage"


def _start_datahelper_once(run_id: str) -> None:
    event_dir = events_dir(run_id)
    if (event_dir / "datahelper.done.json").exists():
        return
    started_path = event_dir / "datahelper.started.json"
    if started_path.exists():
        return
    write_json(
        started_path,
        {
            "run_id": run_id,
            "stage": "datahelper",
            "status": "starting",
            "started_at": utc_now(),
            "trigger": "datamanager_worker",
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
            "trigger": "datamanager_worker",
        },
    )
    update_state(run_id, stage="datahelper", status=f"spawned pid={pid}")
    write_progress(
        run_dir(run_id),
        {"stage": "datahelper", "status": "spawned", "step": "reports", "pid": pid},
    )


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    if len(args) != 1:
        print("usage: python -m orchestrator.datamanager_worker RUN_ID", file=sys.stderr)
        return 2
    run_datamanager(args[0])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
