from __future__ import annotations

from pathlib import Path

from orchestrator import datamanager_worker, run_state
from orchestrator.spec import RunSpec


def _patch_state(monkeypatch, tmp_path: Path) -> list[tuple[str, str, tuple[str, ...]]]:
    monkeypatch.setattr(run_state, "RUNS_ROOT", tmp_path / "runs")
    monkeypatch.setattr(datamanager_worker, "run_dir", run_state.run_dir)
    monkeypatch.setattr(datamanager_worker, "events_dir", run_state.events_dir)
    monkeypatch.setattr(datamanager_worker, "load_spec", run_state.load_spec)
    monkeypatch.setattr(datamanager_worker, "update_state", run_state.update_state)
    starts: list[tuple[str, str, tuple[str, ...]]] = []
    monkeypatch.setattr(
        datamanager_worker,
        "spawn_python_module",
        lambda run_id, module, *args: starts.append((run_id, module, args)) or 1234,
        raising=False,
    )
    return starts


def test_datamanager_worker_creates_replica_paths_and_reports(monkeypatch, tmp_path: Path) -> None:
    starts = _patch_state(monkeypatch, tmp_path)
    source = tmp_path / "source"
    path1 = tmp_path / "path1"
    path2 = tmp_path / "path2"
    source.mkdir()
    path1.mkdir()
    path2.mkdir()
    (source / "A001_C001.braw").write_bytes(b"clip")
    run_state.save_spec(
        RunSpec(
            run_id="run-test",
            project_name="Project",
            source_path=source,
            replica_roots=(path1, path2),
        )
    )

    payload = datamanager_worker.run_datamanager("run-test")

    assert payload["status"] == "completed"
    assert payload["replicas_complete"] is True
    assert payload["replica_footage_roots"] == {
        "path1": str(path1 / "Project/01_Footage/R#1"),
        "path2": str(path2 / "Project/01_Footage/R#1"),
    }
    assert payload["source_path_ids"] == ["source-path-1"]
    assert payload["replica_path_ids"] == ["destination-path-1", "destination-path-2"]
    assert (path1 / "Project/01_Footage/R#1/source-path-1/A001_C001.braw").is_file()
    assert (path2 / "Project/01_Footage/R#1/source-path-1/A001_C001.braw").is_file()
    assert (path1 / "Project/02_Comp").is_dir()
    assert (path2 / "Project/07_ETC_DATA").is_dir()
    assert Path(payload["reports"]["checksum_pdf"]).is_file()
    assert Path(payload["reports"]["manifest_json"]).is_file()
    assert starts == [("run-test", "orchestrator.datahelper_worker", ("run-test",))]
    assert (run_state.events_dir("run-test") / "datahelper.started.json").is_file()


def test_datamanager_worker_uses_nested_footage_run_name(monkeypatch, tmp_path: Path) -> None:
    _patch_state(monkeypatch, tmp_path)
    source = tmp_path / "source"
    path1 = tmp_path / "path1"
    path2 = tmp_path / "path2"
    source.mkdir()
    path1.mkdir()
    path2.mkdir()
    (source / "A001_C001.braw").write_bytes(b"clip")
    run_state.save_spec(
        RunSpec(
            run_id="run-nested",
            project_name="Project",
            source_path=source,
            replica_roots=(path1, path2),
            footage_run_name="260528/A-cam/R#1",
        )
    )

    payload = datamanager_worker.run_datamanager("run-nested")

    assert payload["status"] == "completed"
    assert payload["replica_footage_roots"] == {
        "path1": str(path1 / "Project/01_Footage/260528/A-cam/R#1"),
        "path2": str(path2 / "Project/01_Footage/260528/A-cam/R#1"),
    }
    assert (path1 / "Project/01_Footage/260528/A-cam/R#1/source-path-1/A001_C001.braw").is_file()
    assert (path2 / "Project/01_Footage/260528/A-cam/R#1/source-path-1/A001_C001.braw").is_file()


def test_datamanager_worker_accepts_multiple_sources(monkeypatch, tmp_path: Path) -> None:
    _patch_state(monkeypatch, tmp_path)
    source1 = tmp_path / "source1"
    source2 = tmp_path / "source2"
    path1 = tmp_path / "path1"
    path2 = tmp_path / "path2"
    source1.mkdir()
    source2.mkdir()
    path1.mkdir()
    path2.mkdir()
    (source1 / "A001_C001.braw").write_bytes(b"clip-a")
    (source2 / "B001_C001.braw").write_bytes(b"clip-b")
    run_state.save_spec(
        RunSpec(
            run_id="run-multi-source",
            project_name="Project",
            source_path=source1,
            extra_source_paths=(source2,),
            replica_roots=(path1, path2),
            footage_run_name="260528/A-cam/R#1",
        )
    )

    payload = datamanager_worker.run_datamanager("run-multi-source")

    assert payload["status"] == "completed"
    assert payload["source_path_ids"] == ["source-path-1", "source-path-2"]
    assert (path1 / "Project/01_Footage/260528/A-cam/R#1/source-path-1/A001_C001.braw").is_file()
    assert (path1 / "Project/01_Footage/260528/A-cam/R#1/source-path-2/B001_C001.braw").is_file()
    assert (path2 / "Project/01_Footage/260528/A-cam/R#1/source-path-1/A001_C001.braw").is_file()
    assert (path2 / "Project/01_Footage/260528/A-cam/R#1/source-path-2/B001_C001.braw").is_file()
