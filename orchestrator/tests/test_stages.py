from __future__ import annotations

import json
from pathlib import Path

import pytest

from orchestrator import run_state, stages
from orchestrator.jsonio import write_json
from orchestrator.media_preflight import (
    DependencyCheck,
    MediaDependencyPreflightError,
    MediaPreflightReport,
)


def test_datahelper_stage_preflights_actual_replica_inputs_before_spawn(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    run_id = "run-datahelper-preflight"
    monkeypatch.setattr(run_state, "RUNS_ROOT", tmp_path / "runs")
    project1 = tmp_path / "replica1" / "Project"
    project2 = tmp_path / "replica2" / "Project"
    footage1 = project1 / "01_Footage" / "260814" / "A" / "R#2"
    footage2 = project2 / "01_Footage"
    footage1.mkdir(parents=True)
    footage2.mkdir(parents=True)
    write_json(
        run_state.events_dir(run_id) / "datamanager.done.json",
        {
            "run_id": run_id,
            "status": "completed",
            "replica_project_roots": {
                "path2": str(project2),
                "path1": str(project1),
            },
            "replica_footage_roots": {"path1": str(footage1)},
        },
    )
    report = MediaPreflightReport(
        source_paths=(str(footage1), str(footage2)),
        file_counts={"standard": 1, "braw": 0, "r3d": 0, "arriraw": 0},
        checks=(),
    )
    checked_paths: list[tuple[str, ...]] = []
    starts: list[tuple[str, str, tuple[str, ...]]] = []
    monkeypatch.setattr(
        stages,
        "validate_media_dependencies",
        lambda paths: checked_paths.append(tuple(paths)) or report,
    )
    monkeypatch.setattr(
        stages,
        "spawn_python_module",
        lambda active_run_id, module, *args: starts.append(
            (active_run_id, module, args)
        )
        or 4321,
    )

    pid = stages.start_datahelper_stage(run_id, trigger="datamanager_worker")

    assert pid == 4321
    assert checked_paths == [(str(footage1), str(footage2))]
    assert starts == [(run_id, "orchestrator.datahelper_worker", (run_id,))]
    assert (run_state.events_dir(run_id) / "datahelper.started.json").is_file()
    event = json.loads(
        (run_state.events_dir(run_id) / "datahelper-preflight.done.json").read_text(
            encoding="utf-8"
        )
    )
    assert event["stage"] == "datahelper-preflight"
    assert event["status"] == "completed"
    assert event["report"]["source_paths"] == [str(footage1), str(footage2)]


def test_datahelper_stage_dependency_failure_is_durable_and_does_not_spawn(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    run_id = "run-dependency-disappeared"
    monkeypatch.setattr(run_state, "RUNS_ROOT", tmp_path / "runs")
    project = tmp_path / "replica" / "Project"
    footage = project / "01_Footage" / "260814" / "A" / "R#2"
    footage.mkdir(parents=True)
    write_json(
        run_state.events_dir(run_id) / "datamanager.done.json",
        {
            "run_id": run_id,
            "status": "completed",
            "replica_project_roots": {"path1": str(project)},
            "replica_footage_roots": {"path1": str(footage)},
        },
    )
    original_preflight = {"stage": "media-preflight", "status": "completed"}
    write_json(
        run_state.events_dir(run_id) / "media-preflight.done.json",
        original_preflight,
    )
    report = MediaPreflightReport(
        source_paths=(str(footage),),
        file_counts={"standard": 0, "braw": 0, "r3d": 1, "arriraw": 0},
        checks=(
            DependencyCheck(
                family="r3d",
                dependency="r3d_adapter",
                state="dependency_missing",
                resolved_path="/DataHelper/tools/r3d_adapter",
                message="REDR3D.dylib disappeared after copy started.",
            ),
        ),
    )
    expected_error = MediaDependencyPreflightError(report)
    starts: list[str] = []

    def fail_preflight(paths: tuple[str, ...]) -> MediaPreflightReport:
        assert tuple(paths) == (str(footage),)
        raise expected_error

    monkeypatch.setattr(stages, "validate_media_dependencies", fail_preflight)
    monkeypatch.setattr(
        stages,
        "spawn_python_module",
        lambda _run_id, module, *_args: starts.append(module) or 4321,
    )

    with pytest.raises(MediaDependencyPreflightError) as raised:
        stages.start_datahelper_stage(run_id, trigger="datahandler_api")

    assert raised.value is expected_error
    assert starts == []
    assert not (run_state.events_dir(run_id) / "datahelper.started.json").exists()
    assert json.loads(
        (run_state.events_dir(run_id) / "media-preflight.done.json").read_text(
            encoding="utf-8"
        )
    ) == original_preflight
    event = json.loads(
        (run_state.events_dir(run_id) / "datahelper-preflight.done.json").read_text(
            encoding="utf-8"
        )
    )
    assert event["stage"] == "datahelper-preflight"
    assert event["status"] == "failed"
    assert event["report"]["checks"][0]["state"] == "dependency_missing"
    assert "REDR3D.dylib" in event["error"]
    state = run_state.load_state(run_id)
    assert state["stage"] == "datahelper-preflight"
    assert state["status"] == "failed"
    assert "REDR3D.dylib" in state["last_error"]


def test_datahelper_stage_offline_replica_is_durable_and_does_not_spawn(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    run_id = "run-offline-replica"
    monkeypatch.setattr(run_state, "RUNS_ROOT", tmp_path / "runs")
    offline_project = tmp_path / "offline-replica" / "Project"
    write_json(
        run_state.events_dir(run_id) / "datamanager.done.json",
        {
            "run_id": run_id,
            "status": "completed",
            "replica_project_roots": {"path1": str(offline_project)},
        },
    )
    starts: list[str] = []
    monkeypatch.setattr(
        stages,
        "spawn_python_module",
        lambda _run_id, module, *_args: starts.append(module) or 4321,
    )

    with pytest.raises(MediaDependencyPreflightError) as raised:
        stages.start_datahelper_stage(run_id, trigger="datahandler_api")

    assert starts == []
    assert raised.value.report.failures[0].state == "source_unavailable"
    assert not (run_state.events_dir(run_id) / "datahelper.started.json").exists()
    event = json.loads(
        (
            run_state.events_dir(run_id) / "datahelper-preflight.done.json"
        ).read_text(encoding="utf-8")
    )
    assert event["status"] == "failed"
    assert event["report"]["checks"][0]["state"] == "source_unavailable"
    state = run_state.load_state(run_id)
    assert state["stage"] == "datahelper-preflight"
    assert state["status"] == "failed"
