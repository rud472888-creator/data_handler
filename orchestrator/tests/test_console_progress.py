from __future__ import annotations

from pathlib import Path

from orchestrator.jsonio import write_json
from orchestrator.web.server import _progress_with_steps
from orchestrator.web.progress import list_artifacts, load_run_progress, write_progress


def test_write_and_load_run_progress_prefers_progress_snapshot(tmp_path: Path) -> None:
    run_dir = tmp_path / "run-1"

    write_progress(run_dir, {"stage": "copy", "current": 3, "total": 10})
    progress = load_run_progress(run_dir)

    assert progress["stage"] == "copy"
    assert progress["current"] == 3
    assert progress["total"] == 10
    assert "updated_at" in progress


def test_load_run_progress_falls_back_to_state(tmp_path: Path) -> None:
    run_dir = tmp_path / "run-1"
    run_dir.mkdir()
    write_json(run_dir / "state.json", {"stage": "datamanager", "status": "running"})

    progress = load_run_progress(run_dir)

    assert progress["stage"] == "datamanager"
    assert progress["status"] == "running"


def test_load_run_progress_prefers_done_state_over_snapshot(tmp_path: Path) -> None:
    run_dir = tmp_path / "run-1"
    write_progress(run_dir, {"stage": "datahelper", "status": "completed"})
    write_json(run_dir / "state.json", {"stage": "done", "status": "completed"})

    progress = load_run_progress(run_dir)

    assert progress["stage"] == "done"
    assert progress["status"] == "completed"


def test_load_run_progress_keeps_snapshot_metrics_for_done_state(tmp_path: Path) -> None:
    run_dir = tmp_path / "run-1"
    write_progress(run_dir, {"stage": "datahelper", "status": "completed", "current": 2, "total": 2})
    write_json(run_dir / "state.json", {"stage": "done", "status": "completed"})

    progress = load_run_progress(run_dir)

    assert progress["stage"] == "done"
    assert progress["status"] == "completed"
    assert progress["current"] == 2
    assert progress["total"] == 2


def test_load_run_progress_prefers_failed_state_over_stale_snapshot(tmp_path: Path) -> None:
    run_dir = tmp_path / "run-1"
    write_progress(run_dir, {"stage": "datamanager", "status": "running"})
    write_json(run_dir / "state.json", {"stage": "datamanager", "status": "failed"})

    progress = load_run_progress(run_dir)

    assert progress["stage"] == "datamanager"
    assert progress["status"] == "failed"


def test_failed_progress_step_fallback_does_not_claim_copy_progress() -> None:
    progress = _progress_with_steps({"stage": "datamanager", "status": "failed"})

    assert progress["percent"] == 0
    assert all(step["status"] != "done" for step in progress["steps"])
    assert {"name": "copy", "status": "failed"} in progress["steps"]


def test_load_run_progress_observes_copy_progress_from_replica_paths(tmp_path: Path) -> None:
    run_dir = tmp_path / "run-1"
    source = tmp_path / "source"
    replica1 = tmp_path / "replica1"
    replica2 = tmp_path / "replica2"
    source.mkdir()
    replica1.mkdir()
    replica2.mkdir()
    (source / "A001_C001.braw").write_bytes(b"clip")
    (source / "A001_C002.braw").write_bytes(b"0123456789")
    (source / "notes.txt").write_text("not copied by DataManager", encoding="utf-8")
    write_json(
        run_dir / "request.json",
        {
            "run_id": "run-1",
            "project_name": "Project",
            "source_path": str(source),
            "source_paths": [str(source)],
            "replica_roots": [str(replica1), str(replica2)],
            "footage_run_name": "260528/A-cam/R#1",
        },
    )
    write_progress(run_dir, {"stage": "datamanager", "status": "running"})
    target1 = replica1 / "Project/01_Footage/260528/A-cam/R#1/source-path-1/A001_C001.braw"
    target2 = replica2 / "Project/01_Footage/260528/A-cam/R#1/source-path-1/A001_C001.braw"
    partial = replica1 / "Project/01_Footage/260528/A-cam/R#1/source-path-1/.A001_C002.braw.partial-abc"
    target1.parent.mkdir(parents=True)
    target2.parent.mkdir(parents=True)
    target1.write_bytes(b"clip")
    target2.write_bytes(b"clip")
    partial.write_bytes(b"01234")

    progress = load_run_progress(run_dir)

    assert progress["current"] == 13
    assert progress["total"] == 28
    assert progress["percent"] == 46
    assert progress["copied_files"] == 1
    assert progress["total_files"] == 2
    assert progress["file_count"] == 2
    assert progress["replica_count"] == 2
    assert progress["active_files"] == 1
    assert progress["program"] == "DataManager"
    assert progress["phase"] == "datamanager_copy"
    assert progress["phase_label"] == "DataManager copying and verifying footage"
    assert "1 of 2 source files copied" in progress["phase_detail"]
    assert "2 replica paths" in progress["phase_detail"]
    assert progress["activity_state"] == "running"
    assert progress["progress_observed"] is True


def test_load_run_progress_explains_datahelper_handler_reports(tmp_path: Path) -> None:
    run_dir = tmp_path / "run-1"

    write_progress(
        run_dir,
        {
            "stage": "datahelper",
            "status": "running",
            "current": 1,
            "total": 2,
            "report_completed": 1,
            "report_total": 2,
            "report_count": 5,
        },
    )

    progress = load_run_progress(run_dir)
    with_steps = _progress_with_steps(progress)

    assert progress["program"] == "DataHelper (Handler)"
    assert progress["phase"] == "datahelper_reports"
    assert progress["phase_label"] == "DataHelper generating reports"
    assert "1 of 2 replica report jobs complete" in progress["phase_detail"]
    assert "5 report artifacts available" in progress["phase_detail"]
    assert progress["activity_state"] == "running"
    assert progress["progress_observed"] is True
    assert with_steps["percent"] == 50


def test_load_run_progress_explains_worker_start_without_claiming_output(tmp_path: Path) -> None:
    run_dir = tmp_path / "run-1"
    run_dir.mkdir()
    write_json(run_dir / "state.json", {"stage": "datahelper", "status": "spawned pid=123"})

    progress = load_run_progress(run_dir)

    assert progress["program"] == "DataHelper (Handler)"
    assert progress["phase"] == "datahelper_starting"
    assert progress["phase_label"] == "DataHelper starting"
    assert progress["activity_state"] == "waiting"
    assert progress["progress_observed"] is False


def test_list_artifacts_reads_done_events_and_final_report(tmp_path: Path) -> None:
    run_dir = tmp_path / "run-1"
    events = run_dir / "events"
    events.mkdir(parents=True)
    pdf = tmp_path / "report.pdf"
    pdf.write_bytes(b"%PDF")
    final = run_dir / "final-report.md"
    final.write_text("# Final\n", encoding="utf-8")
    write_json(events / "datahelper.done.json", {"reports": [{"label": "path1", "pdf_path": str(pdf)}]})

    artifacts = list_artifacts(run_dir)

    assert {artifact["name"] for artifact in artifacts} == {"datahelper-path1 pdf", "final report"}


def test_list_artifacts_accepts_legacy_datahelper_report_map(tmp_path: Path) -> None:
    run_dir = tmp_path / "run-1"
    events = run_dir / "events"
    events.mkdir(parents=True)
    pdf = tmp_path / "report.pdf"
    pdf.write_bytes(b"%PDF")
    write_json(
        events / "datahelper.done.json",
        {"reports": {"path1": {"pdf": {"path": str(pdf), "exists": True}}}},
    )

    artifacts = list_artifacts(run_dir)

    assert artifacts == [{"name": "datahelper-path1 pdf", "path": str(pdf), "kind": "pdf"}]


def test_list_artifacts_includes_manifest_and_each_datahelper_replica(tmp_path: Path) -> None:
    run_dir = tmp_path / "run-1"
    events = run_dir / "events"
    events.mkdir(parents=True)
    report_root = tmp_path / "path1" / "Project" / "00_Master" / "reports"
    report_root.mkdir(parents=True)
    checksum = report_root / "checksum.pdf"
    manifest = report_root / "manifest.json"
    path1_pdf = report_root / "datahelper-path1.pdf"
    path2_root = tmp_path / "path2" / "Project" / "00_Master" / "reports"
    path2_root.mkdir(parents=True)
    path2_pdf = path2_root / "datahelper-path2.pdf"
    for path in (checksum, manifest, path1_pdf, path2_pdf):
        path.write_bytes(b"artifact")
    write_json(
        events / "datamanager.done.json",
        {"reports": {"checksum_pdf": str(checksum), "manifest_json": str(manifest)}},
    )
    write_json(
        events / "datahelper.done.json",
        {
            "reports": [
                {"label": "path1", "pdf_path": str(path1_pdf)},
                {"label": "path2", "pdf_path": str(path2_pdf)},
            ]
        },
    )

    artifacts = list_artifacts(run_dir)

    assert {artifact["name"] for artifact in artifacts} == {
        "checksum pdf",
        "manifest json",
        "datahelper-path1 pdf",
        "datahelper-path2 pdf",
    }
