from __future__ import annotations

from pathlib import Path

from orchestrator import cli, run_state, watcher
from orchestrator.jsonio import write_json
from orchestrator.spec import RunSpec


def test_watcher_processes_done_artifact_once(monkeypatch, tmp_path: Path) -> None:
    runs_root = tmp_path / "runs"
    watch_state = tmp_path / "watch-state.json"
    monkeypatch.setattr(run_state, "RUNS_ROOT", runs_root)
    monkeypatch.setattr(watcher, "RUNS_ROOT", runs_root)
    monkeypatch.setattr(watcher, "WATCH_STATE_PATH", watch_state)

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
        {"run_id": "run-test", "status": "completed"},
    )
    calls: list[str] = []
    monkeypatch.setattr(cli, "continue_datamanager", lambda run_id: calls.append(run_id))

    first = watcher.watch_once(direct=True)
    second = watcher.watch_once(direct=True)

    assert len(first) == 1
    assert second == []
    assert calls == ["run-test"]


def test_continue_datamanager_skips_already_started_datahelper(
    monkeypatch, tmp_path: Path
) -> None:
    runs_root = tmp_path / "runs"
    monkeypatch.setattr(run_state, "RUNS_ROOT", runs_root)
    monkeypatch.setattr(cli, "events_dir", run_state.events_dir)
    monkeypatch.setattr(cli, "load_spec", run_state.load_spec)
    monkeypatch.setattr(cli, "update_state", run_state.update_state)
    monkeypatch.setattr(cli, "deliver_via_hermes_gateway", lambda **kwargs: None)

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
        {"run_id": "run-test", "status": "completed"},
    )
    write_json(
        run_state.events_dir("run-test") / "datahelper.started.json",
        {"run_id": "run-test", "stage": "datahelper", "status": "spawned"},
    )
    starts: list[tuple[str, str, tuple[str, ...]]] = []
    monkeypatch.setattr(
        cli,
        "spawn_python_module",
        lambda run_id, module, *args: starts.append((run_id, module, args)) or 1234,
    )

    cli.continue_datamanager("run-test")

    assert starts == []
