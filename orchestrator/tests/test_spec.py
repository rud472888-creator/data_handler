from __future__ import annotations

from pathlib import Path

import pytest

from orchestrator.spec import RunSpec, SpecError


def _paths(tmp_path: Path) -> tuple[Path, Path, Path]:
    source = tmp_path / "source"
    path1 = tmp_path / "path1"
    path2 = tmp_path / "path2"
    source.mkdir()
    path1.mkdir()
    path2.mkdir()
    return source, path1, path2


def test_run_spec_validation_accepts_distinct_existing_replica_paths(tmp_path: Path) -> None:
    source, path1, path2 = _paths(tmp_path)

    spec = RunSpec(
        run_id="run-test",
        project_name="Project",
        source_path=source,
        replica_roots=(path1, path2),
    )

    spec.validate()


def test_run_spec_validation_accepts_multiple_sources(tmp_path: Path) -> None:
    source, path1, path2 = _paths(tmp_path)
    source2 = tmp_path / "source2"
    source2.mkdir()

    spec = RunSpec(
        run_id="run-test",
        project_name="Project",
        source_path=source,
        extra_source_paths=(source2,),
        replica_roots=(path1, path2),
    )

    spec.validate()
    loaded = RunSpec.from_payload(spec.to_payload())
    assert loaded.source_paths == (source, source2)


def test_run_spec_rejects_path_separator_in_project_name(tmp_path: Path) -> None:
    source, path1, path2 = _paths(tmp_path)

    spec = RunSpec(
        run_id="run-test",
        project_name="../Project",
        source_path=source,
        replica_roots=(path1, path2),
    )

    with pytest.raises(SpecError, match="path separators"):
        spec.validate()


def test_run_spec_rejects_duplicate_replica_paths(tmp_path: Path) -> None:
    source = tmp_path / "source"
    path1 = tmp_path / "path1"
    source.mkdir()
    path1.mkdir()

    spec = RunSpec(
        run_id="run-test",
        project_name="Project",
        source_path=source,
        replica_roots=(path1, path1),
    )

    with pytest.raises(SpecError, match="unique"):
        spec.validate()


def test_run_spec_rejects_duplicate_sources(tmp_path: Path) -> None:
    source, path1, path2 = _paths(tmp_path)

    spec = RunSpec(
        run_id="run-test",
        project_name="Project",
        source_path=source,
        extra_source_paths=(source,),
        replica_roots=(path1, path2),
    )

    with pytest.raises(SpecError, match="source paths must be unique"):
        spec.validate()


def test_run_spec_accepts_relative_nested_footage_run_name(tmp_path: Path) -> None:
    source, path1, path2 = _paths(tmp_path)

    spec = RunSpec(
        run_id="run-test",
        project_name="Project",
        source_path=source,
        replica_roots=(path1, path2),
        footage_run_name="260528/A-cam/R#1",
    )

    spec.validate()
    assert RunSpec.from_payload(spec.to_payload()).footage_run_name == "260528/A-cam/R#1"


def test_run_spec_rejects_unsafe_footage_run_name(tmp_path: Path) -> None:
    source, path1, path2 = _paths(tmp_path)

    spec = RunSpec(
        run_id="run-test",
        project_name="Project",
        source_path=source,
        replica_roots=(path1, path2),
        footage_run_name="../R#1",
    )

    with pytest.raises(SpecError, match="footage_run_name"):
        spec.validate()
