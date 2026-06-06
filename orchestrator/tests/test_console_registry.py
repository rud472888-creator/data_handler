from __future__ import annotations

from pathlib import Path

import pytest

from orchestrator.spec import SpecError
from orchestrator.web.registry import ConsoleRegistry, create_project


def _replica_paths(tmp_path: Path) -> tuple[Path, Path]:
    path1 = tmp_path / "path1"
    path2 = tmp_path / "path2"
    path1.mkdir()
    path2.mkdir()
    return path1, path2


def _create_project(registry: ConsoleRegistry, path1: Path, path2: Path):
    return create_project(
        registry=registry,
        name="Project",
        replica_roots=(path1, path2),
        preset_name="default",
        preset_dirs=("01_Footage",),
    )


def test_create_project_records_registry_and_writes_manifests(tmp_path: Path) -> None:
    registry_path = tmp_path / "console-registry.json"
    path1, path2 = _replica_paths(tmp_path)

    project = create_project(
        registry=ConsoleRegistry(registry_path),
        name="No Perfect Movie",
        replica_roots=(path1, path2),
        preset_name="default",
        preset_dirs=("00_Master", "01_Footage", "02_Comp", "07_ETC_DATA"),
    )

    assert project.name == "No Perfect Movie"
    assert (path1 / "No Perfect Movie" / "00_Master").is_dir()
    assert (path2 / "No Perfect Movie" / "01_Footage").is_dir()
    assert (path1 / "No Perfect Movie" / ".dit-console-project.json").is_file()
    assert (path2 / "No Perfect Movie" / ".dit-console-project.json").is_file()

    loaded = ConsoleRegistry(registry_path).load()
    assert loaded["projects"][0]["id"] == project.id
    assert loaded["projects"][0]["replica_project_roots"] == [
        str(path1 / "No Perfect Movie"),
        str(path2 / "No Perfect Movie"),
    ]


def test_allocate_next_roll_uses_registry_runs(tmp_path: Path) -> None:
    registry = ConsoleRegistry(tmp_path / "console-registry.json")
    path1, path2 = _replica_paths(tmp_path)
    project = _create_project(registry, path1, path2)

    first = registry.allocate_next_roll(project.id, "260528", "A-cam")
    registry.record_run(
        project_id=project.id,
        shoot_date="260528",
        camera_unit="A-cam",
        roll=first,
        run_id="run-1",
        source_path="/Volumes/CARD_A",
    )
    second = registry.allocate_next_roll(project.id, "260528", "A-cam")

    assert first == "R#1"
    assert second == "R#2"


def test_allocate_next_roll_uses_existing_project_folders(tmp_path: Path) -> None:
    registry = ConsoleRegistry(tmp_path / "console-registry.json")
    path1, path2 = _replica_paths(tmp_path)
    project = _create_project(registry, path1, path2)
    (path1 / "Project" / "01_Footage" / "260528" / "A-cam" / "R#1").mkdir(parents=True)
    (path2 / "Project" / "01_Footage" / "260528" / "A-cam" / "R#2").mkdir(parents=True)

    assert registry.allocate_next_roll(project.id, "260528", "A-cam") == "R#3"


def test_reserve_run_allocates_and_records_once(tmp_path: Path) -> None:
    registry = ConsoleRegistry(tmp_path / "console-registry.json")
    path1, path2 = _replica_paths(tmp_path)
    project = _create_project(registry, path1, path2)

    first = registry.reserve_run(
        project_id=project.id,
        shoot_date="260528",
        camera_unit="A-cam",
        run_id="run-1",
        source_path="/Volumes/CARD_A",
    )
    second = registry.reserve_run(
        project_id=project.id,
        shoot_date="260528",
        camera_unit="A-cam",
        run_id="run-2",
        source_path="/Volumes/CARD_B",
    )

    payload = registry.load()
    assert first.roll == "R#1"
    assert second.roll == "R#2"
    assert [run["run_id"] for run in payload["runs"]] == ["run-1", "run-2"]
    assert [run["status"] for run in payload["runs"]] == ["reserved", "reserved"]
    assert registry.allocate_next_roll(project.id, "260528", "A-cam") == "R#3"


def test_registry_can_mark_reserved_run_failed(tmp_path: Path) -> None:
    registry = ConsoleRegistry(tmp_path / "console-registry.json")
    path1, path2 = _replica_paths(tmp_path)
    project = _create_project(registry, path1, path2)
    registry.reserve_run(
        project_id=project.id,
        shoot_date="260528",
        camera_unit="A-cam",
        run_id="run-1",
        source_path="/Volumes/CARD_A",
    )

    registry.mark_run_failed("run-1", "spawn failed")

    payload = registry.load()
    assert payload["runs"][0]["status"] == "failed"
    assert payload["runs"][0]["error"] == "spawn failed"


def test_create_project_rejects_path_traversal_name(tmp_path: Path) -> None:
    registry = ConsoleRegistry(tmp_path / "console-registry.json")
    path1, path2 = _replica_paths(tmp_path)

    with pytest.raises(SpecError):
        create_project(
            registry=registry,
            name="../outside",
            replica_roots=(path1, path2),
            preset_name="default",
            preset_dirs=("01_Footage",),
        )

    assert not (tmp_path / "outside").exists()
