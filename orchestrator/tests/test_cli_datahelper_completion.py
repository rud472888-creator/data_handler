from __future__ import annotations

from pathlib import Path

import pytest

from orchestrator import cli, run_state
from orchestrator.jsonio import read_json, write_json
from orchestrator.spec import RunSpec


def _write_spec(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
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
        {"run_id": "run-test", "status": "completed", "reports": {}},
    )


@pytest.mark.parametrize(
    ("datahelper_status", "exit_code"),
    [
        ("failed", 0),
        ("completed", 1),
    ],
)
def test_continue_datahelper_does_not_mark_failed_reports_completed(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    datahelper_status: str,
    exit_code: int,
) -> None:
    _write_spec(monkeypatch, tmp_path)
    delivered: list[dict[str, str]] = []
    monkeypatch.setattr(
        cli,
        "deliver_via_hermes_gateway",
        lambda **kwargs: delivered.append(kwargs),
    )
    write_json(
        run_state.events_dir("run-test") / "datahelper.done.json",
        {
            "run_id": "run-test",
            "status": datahelper_status,
            "reports": [
                {
                    "label": "path1",
                    "input_path": str(tmp_path / "path1" / "Project" / "01_Footage"),
                    "exit_code": exit_code,
                    "pdf_path": str(tmp_path / "path1.pdf"),
                    "csv_path": str(tmp_path / "path1.csv"),
                    "json_path": str(tmp_path / "path1.json"),
                }
            ],
        },
    )

    cli.continue_datahelper("run-test")

    state = read_json(run_state.state_path("run-test"))
    assert state["stage"] == "done"
    assert state["status"] == "failed"
    assert "DataHelper" in state["last_error"]
    assert (run_state.run_dir("run-test") / "final-report.md").is_file()
    assert delivered and delivered[0]["phase"] == "final"


def test_continue_datahelper_fails_completed_event_with_missing_report_artifacts(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _write_spec(monkeypatch, tmp_path)
    delivered: list[dict[str, str]] = []
    monkeypatch.setattr(
        cli,
        "deliver_via_hermes_gateway",
        lambda **kwargs: delivered.append(kwargs),
    )
    pdf = tmp_path / "path1.pdf"
    csv = tmp_path / "path1.csv"
    json_path = tmp_path / "path1.json"
    pdf.write_bytes(b"%PDF")
    csv.write_text("", encoding="utf-8")
    json_path.write_text("{}", encoding="utf-8")
    write_json(
        run_state.events_dir("run-test") / "datahelper.done.json",
        {
            "run_id": "run-test",
            "status": "completed",
            "reports": [
                {
                    "label": "path1",
                    "input_path": str(tmp_path / "path1" / "Project" / "01_Footage"),
                    "exit_code": 0,
                    "pdf_path": str(pdf),
                    "csv_path": str(csv),
                    "json_path": str(json_path),
                }
            ],
        },
    )

    cli.continue_datahelper("run-test")

    state = read_json(run_state.state_path("run-test"))
    assert state["stage"] == "done"
    assert state["status"] == "failed"
    assert "DataHelper" in state["last_error"]
    assert delivered and delivered[0]["phase"] == "final"
