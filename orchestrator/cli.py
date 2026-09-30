from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any
from uuid import uuid4

from orchestrator.delivery import deliver_via_hermes_gateway, read_markdown
from orchestrator.jsonio import read_json, write_json
from orchestrator.media_preflight import (
    MediaDependencyPreflightError,
    validate_media_dependencies,
)
from orchestrator.paths import DEFAULT_HERMES_PROFILE
from orchestrator.processes import spawn_python_module
from orchestrator.reporting import datamanager_message, final_message, write_final_report
from orchestrator.run_state import events_dir, load_spec, save_spec, update_state, utc_now
from orchestrator.spec import RUN_MODE_DATAMANAGER, RUN_MODE_WORKFLOW, RunSpec
from orchestrator.stages import start_datahelper_stage
from orchestrator.visual_qa.scheduler import schedule_after_completion
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
    start.add_argument("--mode", choices=(RUN_MODE_WORKFLOW, RUN_MODE_DATAMANAGER), default=RUN_MODE_WORKFLOW)
    start.add_argument(
        "--visual-qa",
        action="store_true",
        help="Queue the post-completion visual QA once backup verification and reports finish.",
    )

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

    _add_visual_qa_parser(subparsers)
    return parser


def _add_visual_qa_parser(subparsers: Any) -> None:
    qa = subparsers.add_parser("visual-qa", help="Post-completion visual QA (separate from agent reviews).")
    sub = qa.add_subparsers(dest="qa_command", required=True)
    start = sub.add_parser("start", help="Start or resume the visual QA of a finished run.")
    start.add_argument("--run-id", required=True)
    start.add_argument("--new-revision", action="store_true", help="Inspect again into a new revision directory.")
    start.add_argument("--foreground", action="store_true", help="Run in this process instead of a background worker.")
    start.add_argument("--start-frame", type=int)
    start.add_argument("--end-frame", type=int)
    start.add_argument("--max-frames-per-clip", type=int)
    start.add_argument("--max-clips", type=int)
    start.add_argument("--model-max-side", type=int)
    status = sub.add_parser("status", help="Print the visual QA status of a run.")
    status.add_argument("--run-id", required=True)
    report = sub.add_parser("report", help="Regenerate findings.json and report.html from the stored journal.")
    report.add_argument("--run-id", required=True)
    report.add_argument("--qa-id", required=True)
    install = sub.add_parser("install-model", help="Download or register the Qwen3.5-4B weights (explicit step).")
    install.add_argument("--source-repo", default="Qwen/Qwen3.5-4B")
    install.add_argument("--revision")
    install.add_argument("--quantization")
    install.add_argument("--derived-from")
    install.add_argument("--local-path", help="Register an already-downloaded model folder without network access.")
    smoke = sub.add_parser("smoke", help="Real-model smoke test on normal and anomalous synthetic clips.")
    smoke.add_argument("--output", required=True)


def _visual_qa_command(args: argparse.Namespace) -> int:
    import json

    from orchestrator.visual_qa import scheduler

    if args.qa_command == "start":
        overrides = {key: value for key, value in {
            "start_frame": args.start_frame, "end_frame": args.end_frame,
            "max_frames_per_clip": args.max_frames_per_clip, "max_clips": args.max_clips,
            "model_max_side": args.model_max_side}.items() if value is not None}
        try:
            result = scheduler.schedule_visual_qa(
                args.run_id, trigger="cli", manual=True, new_revision=args.new_revision, config=overrides or None,
                spawn=(lambda run_id, qa_id: 0) if args.foreground else None)
        except scheduler.ScheduleError as exc:
            print(f"blocked ({exc.code}): {exc}")
            return 2
        print(json.dumps(result, ensure_ascii=False))
        if args.foreground and result.get("action") in {"spawned", "retry", "recovered"}:
            from orchestrator.visual_qa import worker

            state = worker.run(args.run_id, result["qa_id"])
            print(json.dumps({"status": state.get("status"), "reason": state.get("reason"), "counts": state.get("counts")},
                             ensure_ascii=False))
        return 0
    if args.qa_command == "status":
        print(json.dumps(scheduler.qa_summary(args.run_id), ensure_ascii=False, indent=2))
        return 0
    if args.qa_command == "report":
        from orchestrator.visual_qa.runner import rebuild_outputs

        if not scheduler.is_valid_qa_id(args.qa_id):
            print("invalid qa id")
            return 2
        error = rebuild_outputs(scheduler.visual_qa_root(args.run_id) / args.qa_id)
        print(error or str(scheduler.visual_qa_root(args.run_id) / args.qa_id / "report.html"))
        return 1 if error else 0
    if args.qa_command == "install-model":
        from orchestrator.visual_qa.install import install_model

        record = install_model(source_repo=args.source_repo, revision=args.revision, quantization=args.quantization,
                               derived_from=args.derived_from, local_path=Path(args.local_path) if args.local_path else None)
        print(json.dumps(record, ensure_ascii=False, indent=2))
        return 0
    if args.qa_command == "smoke":
        from orchestrator.visual_qa.backend import BackendUnavailable, MlxVlmBackend
        from orchestrator.visual_qa.smoke import run_smoke

        try:
            result = run_smoke(MlxVlmBackend(), Path(args.output))
        except BackendUnavailable as exc:
            print(f"blocked ({exc.code}): {exc}")
            return 2
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if (result["image_input_check"]["passed"] and result["clips"]
                     and all(clip.get("status") == "completed" for clip in result["clips"].values())) else 1
    raise AssertionError(args.qa_command)


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "start":
        run_id = start_run(
            source_paths=tuple(Path(path) for path in args.source),
            replica_paths=tuple(Path(path) for path in args.replica_path),
            project_name=args.project_name,
            profile=args.profile,
            run_id=args.run_id,
            run_mode=args.mode,
            visual_qa=args.visual_qa,
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
    if args.command == "visual-qa":
        return _visual_qa_command(args)
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
            "orchestrator.dit_app.server:create_app",
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
    run_mode: str = RUN_MODE_WORKFLOW,
    flat_card_layout: bool = False,
    visual_qa: bool = False,
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
        run_mode=run_mode,
        flat_card_layout=flat_card_layout,
        visual_qa=visual_qa,
    )
    save_spec(spec)
    update_state(active_run_id, stage="media-preflight", status="running")
    try:
        preflight = validate_media_dependencies(
            spec.source_paths,
            check_processing_dependencies=spec.run_mode != RUN_MODE_DATAMANAGER,
        )
    except MediaDependencyPreflightError as exc:
        _write_media_preflight_event(active_run_id, "failed", exc.report.to_dict())
        update_state(
            active_run_id,
            stage="media-preflight",
            status="failed",
            error=str(exc),
        )
        raise
    _write_media_preflight_event(active_run_id, "completed", preflight.to_dict())
    update_state(active_run_id, stage="datamanager", status="queued")
    try:
        spawn_python_module(active_run_id, "orchestrator.datamanager_worker", active_run_id)
    except Exception as exc:
        update_state(active_run_id, stage="datamanager", status="failed", error=str(exc))
        raise
    update_state(active_run_id, stage="datamanager", status="spawned")
    return active_run_id


def _write_media_preflight_event(
    run_id: str,
    status: str,
    report: dict[str, object],
) -> None:
    write_json(
        events_dir(run_id) / "media-preflight.done.json",
        {
            "run_id": run_id,
            "stage": "media-preflight",
            "status": status,
            "report": report,
            "finished_at": utc_now(),
        },
    )


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
    if spec.run_mode == RUN_MODE_DATAMANAGER:
        update_state(run_id, stage="datamanager", status=str(done.get("status") or "completed"))
        schedule_after_completion(run_id, "continue_datamanager")
        return
    event_dir = events_dir(run_id)
    if (event_dir / "datahelper.done.json").exists():
        return
    started_path = event_dir / "datahelper.started.json"
    if started_path.exists():
        return
    start_datahelper_stage(run_id, trigger="continue_datamanager")


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
    else:
        update_state(run_id, stage="done", status="completed")
    schedule_after_completion(run_id, "continue_datahelper")


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
