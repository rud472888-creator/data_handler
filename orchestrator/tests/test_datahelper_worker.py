from __future__ import annotations

from pathlib import Path

import pytest

from orchestrator import datahelper_worker, run_state
from orchestrator.datahelper_worker import (
    _footage_input_path,
    _report_output_root,
    _run_one,
    build_frameproof_command,
    run_datahelper,
)
from orchestrator.jsonio import read_json, write_json
from orchestrator.spec import RunSpec


def test_frameproof_command_targets_replica_artifacts(tmp_path: Path) -> None:
    command = build_frameproof_command(
        input_path=tmp_path / "input",
        pdf_path=tmp_path / "datahelper-path1.pdf",
        csv_path=tmp_path / "datahelper-path1.csv",
        json_path=tmp_path / "datahelper-path1.json",
        project_name="Project path1 replica",
    )

    assert "-m" in command
    assert "frameproof" in command
    assert str(tmp_path / "datahelper-path1.pdf") in command
    assert str(tmp_path / "datahelper-path1.csv") in command
    assert str(tmp_path / "datahelper-path1.json") in command
    assert command[command.index("--middle-count") + 1] == "1"


def test_footage_input_path_prefers_datamanager_run_folder(tmp_path: Path) -> None:
    dm_done = {
        "replica_project_roots": {"path1": str(tmp_path / "path1" / "Project")},
        "replica_footage_roots": {
            "path1": str(tmp_path / "path1" / "Project" / "01_Footage" / "R#2")
        },
    }

    assert _footage_input_path(dm_done, "path1") == (
        tmp_path / "path1" / "Project" / "01_Footage" / "R#2"
    )


def test_report_output_root_uses_project_master_reports(tmp_path: Path) -> None:
    dm_done = {
        "replica_project_roots": {"path2": str(tmp_path / "path2" / "Project")},
        "replica_footage_roots": {
            "path2": str(tmp_path / "path2" / "Project" / "01_Footage" / "R#1")
        },
    }

    assert _report_output_root(dm_done, "path2") == (
        tmp_path / "path2" / "Project" / "00_Master" / "reports"
    )


def test_run_datahelper_fails_when_datamanager_has_no_replica_project_roots(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    runs_root = tmp_path / "runs"
    monkeypatch.setattr(run_state, "RUNS_ROOT", runs_root)
    source = tmp_path / "source"
    path1 = tmp_path / "path1"
    path2 = tmp_path / "path2"
    source.mkdir()
    path1.mkdir()
    path2.mkdir()
    run_state.save_spec(
        RunSpec(
            run_id="run-test",
            project_name="Project",
            source_path=source,
            replica_roots=(path1, path2),
        )
    )
    write_json(
        run_state.events_dir("run-test") / "datamanager.done.json",
        {
            "run_id": "run-test",
            "status": "completed",
            "replica_project_roots": {},
        },
    )

    def fail_if_frameproof_runs(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("Frame Proof should not run without replica_project_roots")

    monkeypatch.setattr(datahelper_worker.subprocess, "run", fail_if_frameproof_runs)

    payload = run_datahelper("run-test")

    assert payload["status"] == "failed"
    assert payload["reports"] == []
    assert "replica_project_roots" in payload["error"]
    assert read_json(run_state.events_dir("run-test") / "datahelper.done.json")["status"] == "failed"
    state = read_json(run_state.state_path("run-test"))
    assert state["stage"] == "datahelper"
    assert state["status"] == "failed"


def test_run_one_requires_non_empty_pdf_csv_and_json(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    input_path = tmp_path / "footage"
    input_path.mkdir()

    def fake_frameproof(command: list[str], **_kwargs: object) -> object:
        Path(command[command.index("--output") + 1]).write_bytes(b"%PDF")
        Path(command[command.index("--csv") + 1]).write_text("", encoding="utf-8")
        Path(command[command.index("--json") + 1]).write_text("{}", encoding="utf-8")
        return datahelper_worker.subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr(datahelper_worker.subprocess, "run", fake_frameproof)

    result = _run_one(
        label="path1",
        input_path=input_path,
        output_root=tmp_path / "reports",
        project_name="Project path1 replica",
    )

    assert result["exit_code"] == 0
    assert result["status"] == "review-needed"
    assert result["pdf_ready"] is True
    assert result["csv_ready"] is False
    assert result["json_ready"] is True
    assert result["missing_artifacts"] == ["csv"]
