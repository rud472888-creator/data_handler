from __future__ import annotations

from pathlib import Path

from orchestrator import reporting, run_state
from orchestrator.jsonio import write_json
from orchestrator.spec import RunSpec


def test_write_final_report_accepts_legacy_datahelper_report_map(
    monkeypatch, tmp_path: Path
) -> None:
    runs_root = tmp_path / "runs"
    monkeypatch.setattr(run_state, "RUNS_ROOT", runs_root)
    monkeypatch.setattr(reporting, "events_dir", run_state.events_dir)
    monkeypatch.setattr(reporting, "load_spec", run_state.load_spec)
    monkeypatch.setattr(reporting, "run_dir", run_state.run_dir)
    source = tmp_path / "source"
    source2 = tmp_path / "source2"
    path1 = tmp_path / "path1"
    path2 = tmp_path / "path2"
    source.mkdir()
    source2.mkdir()
    path1.mkdir()
    path2.mkdir()
    run_state.save_spec(
        RunSpec(
            run_id="run-test",
            project_name="Project",
            source_path=source,
            extra_source_paths=(source2,),
            replica_roots=(path1, path2),
        )
    )
    write_json(
        run_state.events_dir("run-test") / "datamanager.done.json",
        {"run_id": "run-test", "status": "completed", "reports": {}},
    )
    write_json(
        run_state.events_dir("run-test") / "datahelper.done.json",
        {
            "run_id": "run-test",
            "status": "completed",
            "reports": {
                "path1": {
                    "pdf": {"path": "/tmp/path1.pdf", "exists": True},
                    "csv": "/tmp/path1.csv",
                    "json": "/tmp/path1.json",
                }
            },
        },
    )

    report_path = reporting.write_final_report("run-test")

    text = report_path.read_text(encoding="utf-8")
    assert f"- `{source}`" in text
    assert f"- `{source2}`" in text
    assert "### path1" in text
    assert "/tmp/path1.pdf" in text
    assert "/tmp/path1.csv" in text
