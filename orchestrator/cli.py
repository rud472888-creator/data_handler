from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any
from uuid import uuid4

from orchestrator.delivery import deliver_via_hermes_gateway, read_markdown
from orchestrator.jsonio import read_json, write_json
from orchestrator.paths import DEFAULT_HERMES_PROFILE
from orchestrator.processes import spawn_python_module
from orchestrator.reporting import datamanager_message, final_message, write_final_report
from orchestrator.run_state import events_dir, load_spec, save_spec, update_state, utc_now
from orchestrator.spec import RunSpec
from orchestrator.watcher import watch_once


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m orchestrator.cli")
    subparsers = parser.add_subparsers(dest="command", required=True)

    start = subparsers.add_parser(
        "start",
        help="Create an approved run spec and start DataManager.",
    )
    start.add_argument("--source", action="append", required=True)
    start.add_argument("--replica-path", action="append", required=True)
    start.add_argument("--project-name", required=True)
    start.add_argument("--profile", default=DEFAULT_HERMES_PROFILE)
    start.add_argument("--run-id")

    dm = subparsers.add_parser("continue-datamanager", help="Handle DataManager completion.")
    dm.add_argument("--run-id", required=True)

    dh = subparsers.add_parser("continue-datahelper", help="Handle DataHelper completion.")
    dh.add_argument("--run-id", required=True)

    watch = subparsers.add_parser("watch-once", help="Process new completion artifacts once.")
    watch.add_argument(
        "--direct",
        action="store_true",
        help="Run continuations directly instead of launching Hermes.",
    )

    console = subparsers.add_parser("console", help="Serve the Data Handler API and UI.")
    console.add_argument("--host", default="127.0.0.1")
    console.add_argument("--port", type=int, default=8765)

    app = subparsers.add_parser("app", help="Serve the Data Handler app.")
    app.add_argument("--host", default="127.0.0.1")
    app.add_argument("--port", type=int, default=8750)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "start":
        run_id = start_run(
            source_paths=tuple(Path(path) for path in args.source),
            replica_paths=tuple(Path(path) for path in args.replica_path),
            project_name=args.project_name,
            profile=args.profile,
            run_id=args.run_id,
        )
        print(run_id)
        return 0
    if args.command == "continue-datamanager":
        continue_datamanager(args.run_id)
        return 0
    if args.command == "continue-datahelper":
        continue_datahelper(args.run_id)
        return 0
    if args.command == "watch-once":
        for action in watch_once(direct=args.direct):
            print(action)
        return 0
    if args.command == "console":
        import uvicorn

        uvicorn.run(
            "orchestrator.web.server:create_app",
            host=args.host,
            port=args.port,
            factory=True,
        )
        return 0
    if args.command == "app":
        import uvicorn

        uvicorn.run(
            "orchestrator.app_front.server:create_app",
            host=args.host,
            port=args.port,
            factory=True,
        )
        return 0
    raise AssertionError(f"unhandled command: {args.command}")


def start_run(
    *,
    source: Path | None = None,
    source_paths: tuple[Path, ...] | None = None,
    replica_paths: tuple[Path, ...],
    project_name: str,
    profile: str,
    run_id: str | None = None,
    footage_run_name: str | None = None,
) -> str:
    active_run_id = run_id or f"run-{uuid4().hex[:12]}"
    active_source_paths = source_paths or ((source,) if source is not None else ())
    if not active_source_paths:
        raise ValueError("at least one source path is required")
    spec = RunSpec(
        run_id=active_run_id,
        project_name=project_name,
        source_path=active_source_paths[0],
        extra_source_paths=active_source_paths[1:],
        replica_roots=replica_paths,
        hermes_profile=profile,
        footage_run_name=footage_run_name,
    )
    save_spec(spec)
    update_state(active_run_id, stage="datamanager", status="queued")
    try:
        spawn_python_module(active_run_id, "orchestrator.datamanager_worker", active_run_id)
    except Exception as exc:
        update_state(active_run_id, stage="datamanager", status="failed", error=str(exc))
        raise
    update_state(active_run_id, stage="datamanager", status="spawned")
    return active_run_id


def continue_datamanager(run_id: str) -> None:
    spec = load_spec(run_id)
    done_path = events_dir(run_id) / "datamanager.done.json"
    done = read_json(done_path)
    deliver_via_hermes_gateway(
        run_id=run_id,
        phase="datamanager",
        message=datamanager_message(run_id),
        profile=spec.hermes_profile,
    )
    if done.get("status") == "failed":
        update_state(
            run_id,
            stage="datamanager",
            status="failed",
            error="DataManager failed; DataHelper not started",
        )
        return
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
            "trigger": "continue_datamanager",
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
            "trigger": "continue_datamanager",
        },
    )
    update_state(run_id, stage="datahelper", status=f"spawned pid={pid}")


def continue_datahelper(run_id: str) -> None:
    spec = load_spec(run_id)
    done = read_json(events_dir(run_id) / "datahelper.done.json")
    report_path = write_final_report(run_id)
    message = final_message(run_id, report_path) + "\n\n" + read_markdown(report_path)
    deliver_via_hermes_gateway(
        run_id=run_id,
        phase="final",
        message=message,
        profile=spec.hermes_profile,
    )
    if _datahelper_failed(done):
        update_state(
            run_id,
            stage="done",
            status="failed",
            error="DataHelper failed; final report was generated for review",
        )
        return
    update_state(run_id, stage="done", status="completed")


def _datahelper_failed(done: dict[str, Any]) -> bool:
    if done.get("status") != "completed":
        return True
    reports = done.get("reports", [])
    if isinstance(reports, dict):
        report_values = [report for report in reports.values() if isinstance(report, dict)]
    elif isinstance(reports, list):
        report_values = [report for report in reports if isinstance(report, dict)]
    else:
        report_values = []
    for report in report_values:
        exit_code = report.get("exit_code")
        if exit_code is not None and exit_code != 0:
            return True
        for key in ("pdf_path", "csv_path", "json_path"):
            path = Path(str(report.get(key, "")))
            if not path.is_file() or path.stat().st_size == 0:
                return True
    return False


if __name__ == "__main__":
    raise SystemExit(main())
