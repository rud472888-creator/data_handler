from __future__ import annotations

import json
from pathlib import Path

import pytest

from orchestrator import cli, run_state
from orchestrator.media_preflight import (
    DependencyCheck,
    MediaDependencyPreflightError,
    MediaPreflightReport,
    validate_media_dependencies,
)
from orchestrator.spec import RUN_MODE_DATAMANAGER


def test_mov_preflight_passes_with_callable_ffmpeg_tools(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "A001.MOV").touch()
    tool_dir = tmp_path / "bin"
    tool_dir.mkdir()
    for name in ("ffmpeg", "ffprobe"):
        _write_executable(tool_dir / name, "#!/bin/sh\nexit 0\n")
    monkeypatch.setenv("PATH", str(tool_dir))

    report = validate_media_dependencies(
        source,
        data_helper_root=tmp_path / "missing-data-helper",
    )

    assert report.ok is True
    assert report.detected_families == ("standard",)
    assert report.file_counts["standard"] == 1
    assert {check.dependency for check in report.checks} == {"ffmpeg", "ffprobe"}


def test_missing_source_path_is_a_structured_preflight_failure(tmp_path: Path) -> None:
    missing = tmp_path / "offline-replica" / "01_Footage"

    with pytest.raises(MediaDependencyPreflightError) as raised:
        validate_media_dependencies(missing)

    report = raised.value.report
    assert report.detected_families == ()
    assert report.failures[0].dependency == "source_path"
    assert report.failures[0].state == "source_unavailable"
    assert str(missing) in str(raised.value)


def test_braw_preflight_uses_bundled_adapter_version_check(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "A001.braw").touch()
    helper_root = tmp_path / "DataHelper"
    adapter = helper_root / "tools" / "braw_adapter"
    response = {
        "ok": True,
        "status": "success",
        "adapter_name": "braw_adapter",
        "adapter_version": "test-native-sdk",
        "metadata_raw": {"native_no_proxy": True},
    }
    _write_json_adapter(adapter, response, exit_code=0)

    report = validate_media_dependencies(source, data_helper_root=helper_root)

    assert report.ok is True
    assert report.detected_families == ("braw",)
    assert report.checks[0].dependency == "braw_adapter"
    assert report.checks[0].detail["adapter_version"] == "test-native-sdk"


def test_r3d_preflight_fails_before_copy_when_sdk_is_missing(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "DSC_0156.R3D").touch()
    helper_root = tmp_path / "DataHelper"
    adapter = helper_root / "tools" / "r3d_adapter"
    sdk_path = tmp_path / "REDSDK" / "Redistributable" / "mac"
    response = {
        "ok": False,
        "status": "dependency_missing",
        "errors": [
            {
                "code": "dependency_missing",
                "message": f"REDR3D.dylib not found under SDK libraries path: {sdk_path}",
            }
        ],
    }
    _write_json_adapter(adapter, response, exit_code=2)

    with pytest.raises(MediaDependencyPreflightError) as raised:
        validate_media_dependencies(source, data_helper_root=helper_root)

    report = raised.value.report
    assert report.ok is False
    assert report.detected_families == ("r3d",)
    assert report.failures[0].state == "dependency_missing"
    assert "REDR3D.dylib" in str(raised.value)
    assert "RED_R3D_SDK_LIBRARIES" in str(raised.value)


def test_arriraw_preflight_checks_real_art_cmd_backend(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "A001.0000001.ari").touch()
    helper_root = tmp_path / "DataHelper"
    launcher = helper_root / "tools" / "art-cmd"
    _write_executable(
        launcher,
        "#!/bin/sh\necho 'art-cmd backend not found' >&2\nexit 127\n",
    )

    with pytest.raises(MediaDependencyPreflightError) as raised:
        validate_media_dependencies(source, data_helper_root=helper_root)

    assert raised.value.report.failures[0].dependency == "arri_art_cmd"
    assert "backend not found" in str(raised.value)
    assert "FRAMEPROOF_ARRI_ART_CMD" in str(raised.value)


def test_mxf_without_recognized_arriraw_picture_coding_ul_is_standard(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source = tmp_path / "source"
    nested = source / "card"
    nested.mkdir(parents=True)
    (nested / "A001.mxf").write_bytes(b"regular MXF header metadata")
    (nested / "._A002.MXF").touch()
    tool_dir = tmp_path / "bin"
    tool_dir.mkdir()
    for name in ("ffmpeg", "ffprobe"):
        _write_executable(tool_dir / name, "#!/bin/sh\nexit 0\n")
    monkeypatch.setenv("PATH", str(tool_dir))

    report = validate_media_dependencies(source, data_helper_root=tmp_path)

    assert report.file_counts["standard"] == 1
    assert report.file_counts["arriraw"] == 0
    assert len(report.warnings) == 1
    assert "recognized ARRIRAW picture coding UL" in report.warnings[0]


def test_mxf_with_recognized_arriraw_picture_coding_ul_requires_art_cmd(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source"
    source.mkdir()
    arriraw_ul = bytes.fromhex("060e2b340401010d0401020102010202")
    boundary_prefix = b"x" * ((64 * 1024) - 8)
    (source / "A001.mxf").write_bytes(boundary_prefix + arriraw_ul + b"payload")
    helper_root = tmp_path / "DataHelper"
    _write_executable(helper_root / "tools" / "art-cmd", "#!/bin/sh\nexit 0\n")

    report = validate_media_dependencies(source, data_helper_root=helper_root)

    assert report.detected_families == ("arriraw",)
    assert report.file_counts["standard"] == 0
    assert report.file_counts["arriraw"] == 1
    assert [check.dependency for check in report.checks] == ["arri_art_cmd"]
    assert not any("Classified 1 .mxf" in warning for warning in report.warnings)


@pytest.mark.parametrize(
    "arriraw_ul",
    (
        bytes.fromhex("060e2b340401010d0f01020101010100"),
        bytes.fromhex("060e2b340401010d0f01020101010200"),
    ),
)
def test_mxf_with_legacy_arriraw_picture_coding_ul_requires_art_cmd(
    tmp_path: Path,
    arriraw_ul: bytes,
) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "A001.mxf").write_bytes(b"MXF header" + arriraw_ul + b"payload")
    helper_root = tmp_path / "DataHelper"
    _write_executable(helper_root / "tools" / "art-cmd", "#!/bin/sh\nexit 0\n")

    report = validate_media_dependencies(source, data_helper_root=helper_root)

    assert report.detected_families == ("arriraw",)
    assert report.file_counts["standard"] == 0
    assert report.file_counts["arriraw"] == 1
    assert [check.dependency for check in report.checks] == ["arri_art_cmd"]


def test_only_dependencies_for_detected_families_are_required(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "A001.braw").touch()
    helper_root = tmp_path / "DataHelper"
    _write_json_adapter(
        helper_root / "tools" / "braw_adapter",
        {"ok": True, "status": "success"},
        exit_code=0,
    )

    report = validate_media_dependencies(source, data_helper_root=helper_root)

    assert [check.dependency for check in report.checks] == ["braw_adapter"]


def test_zero_byte_arx_fails_as_unsupported_source_transport(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "A001.0000001.arx").touch()

    with pytest.raises(MediaDependencyPreflightError) as raised:
        validate_media_dependencies(
            source,
            data_helper_root=tmp_path / "missing-data-helper",
        )

    report = raised.value.report
    assert report.detected_families == ("arriraw",)
    assert report.file_counts["arriraw"] == 1
    assert [check.dependency for check in report.checks] == ["arx_source_transport"]
    assert report.failures[0].state == "unsupported_source_transport"
    assert "zero-byte .arx" in str(raised.value)
    assert "HDE-aware offload tool" in str(raised.value)


def test_materialized_arx_fails_as_unsupported_processing(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "A001.0000001.arx").write_bytes(b"materialized ARRIRAW data")

    with pytest.raises(MediaDependencyPreflightError) as raised:
        validate_media_dependencies(
            source,
            data_helper_root=tmp_path / "missing-data-helper",
        )

    report = raised.value.report
    assert report.detected_families == ("arriraw",)
    assert report.file_counts["arriraw"] == 1
    assert [check.dependency for check in report.checks] == ["arx_processing"]
    assert report.failures[0].state == "unsupported_processing"
    assert "materialized .arx" in str(raised.value)
    assert "DataHelper does not support .arx processing" in str(raised.value)


def test_arx_workflow_is_recorded_as_failed_before_copy_starts(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source, replica = _run_paths(tmp_path)
    (source / "A001.0000001.arx").touch()
    starts: list[str] = []
    monkeypatch.setattr(run_state, "RUNS_ROOT", tmp_path / "runs")
    monkeypatch.setattr(
        cli,
        "spawn_python_module",
        lambda run_id, module, *args: starts.append(module) or 1234,
    )

    with pytest.raises(MediaDependencyPreflightError) as raised:
        cli.start_run(
            source_paths=(source,),
            replica_paths=(replica,),
            project_name="Project",
            profile="test-profile",
            run_id="run-arx-preflight-failed",
        )

    assert starts == []
    assert raised.value.report.failures[0].dependency == "arx_source_transport"
    event = json.loads(
        (
            run_state.events_dir("run-arx-preflight-failed")
            / "media-preflight.done.json"
        ).read_text(encoding="utf-8")
    )
    assert event["status"] == "failed"
    assert event["report"]["detected_families"] == ["arriraw"]
    assert event["report"]["checks"][0]["state"] == "unsupported_source_transport"
    assert (
        run_state.load_state("run-arx-preflight-failed")["stage"] == "media-preflight"
    )


def test_workflow_preflight_failure_is_recorded_before_copy_starts(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source, replica = _run_paths(tmp_path)
    (source / "DSC_0156.R3D").touch()
    report = MediaPreflightReport(
        source_paths=(str(source),),
        file_counts={"standard": 0, "braw": 0, "r3d": 1, "arriraw": 0},
        checks=(
            DependencyCheck(
                family="r3d",
                dependency="r3d_adapter",
                state="dependency_missing",
                resolved_path="/DataHelper/tools/r3d_adapter",
                message="REDR3D.dylib is missing.",
            ),
        ),
    )
    starts: list[str] = []
    monkeypatch.setattr(run_state, "RUNS_ROOT", tmp_path / "runs")
    monkeypatch.setattr(
        cli,
        "validate_media_dependencies",
        lambda paths, **kwargs: (_ for _ in ()).throw(
            MediaDependencyPreflightError(report)
        ),
    )
    monkeypatch.setattr(
        cli,
        "spawn_python_module",
        lambda run_id, module, *args: starts.append(module) or 1234,
    )

    with pytest.raises(MediaDependencyPreflightError):
        cli.start_run(
            source_paths=(source,),
            replica_paths=(replica,),
            project_name="Project",
            profile="test-profile",
            run_id="run-preflight-failed",
        )

    assert starts == []
    event = json.loads(
        (run_state.events_dir("run-preflight-failed") / "media-preflight.done.json").read_text(
            encoding="utf-8"
        )
    )
    assert event["status"] == "failed"
    assert event["report"]["detected_families"] == ["r3d"]
    assert run_state.load_state("run-preflight-failed")["stage"] == "media-preflight"


def test_datamanager_only_run_skips_processing_dependencies_but_records_source_check(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source, replica = _run_paths(tmp_path)
    (source / "DSC_0156.R3D").touch()
    starts: list[str] = []
    monkeypatch.setattr(run_state, "RUNS_ROOT", tmp_path / "runs")
    monkeypatch.setattr(
        cli,
        "spawn_python_module",
        lambda run_id, module, *args: starts.append(module) or 1234,
    )

    run_id = cli.start_run(
        source_paths=(source,),
        replica_paths=(replica,),
        project_name="Project",
        profile="test-profile",
        run_id="run-copy-only",
        run_mode=RUN_MODE_DATAMANAGER,
    )

    assert run_id == "run-copy-only"
    assert starts == ["orchestrator.datamanager_worker"]
    event = json.loads(
        (run_state.events_dir(run_id) / "media-preflight.done.json").read_text(
            encoding="utf-8"
        )
    )
    assert event["status"] == "completed"
    assert event["report"]["detected_families"] == ["r3d"]
    assert event["report"]["checks"] == []


def test_datamanager_only_run_blocks_arx_before_copy_starts(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source, replica = _run_paths(tmp_path)
    (source / "A001.MOV").touch()
    (source / "A001.0000001.arx").touch()
    starts: list[str] = []
    monkeypatch.setattr(run_state, "RUNS_ROOT", tmp_path / "runs")
    monkeypatch.setattr(
        cli,
        "spawn_python_module",
        lambda run_id, module, *args: starts.append(module) or 1234,
    )

    with pytest.raises(MediaDependencyPreflightError) as raised:
        cli.start_run(
            source_paths=(source,),
            replica_paths=(replica,),
            project_name="Project",
            profile="test-profile",
            run_id="run-copy-only-arx",
            run_mode=RUN_MODE_DATAMANAGER,
        )

    assert starts == []
    assert raised.value.report.failures[0].dependency == "arx_source_transport"
    event = json.loads(
        (
            run_state.events_dir("run-copy-only-arx")
            / "media-preflight.done.json"
        ).read_text(encoding="utf-8")
    )
    assert event["status"] == "failed"
    assert event["report"]["file_counts"] == {
        "standard": 1,
        "braw": 0,
        "r3d": 0,
        "arriraw": 1,
    }
    assert [check["dependency"] for check in event["report"]["checks"]] == [
        "arx_source_transport"
    ]


def _run_paths(tmp_path: Path) -> tuple[Path, Path]:
    source = tmp_path / "source"
    replica = tmp_path / "replica"
    source.mkdir()
    replica.mkdir()
    return source, replica


def _write_json_adapter(path: Path, response: dict[str, object], *, exit_code: int) -> None:
    payload = json.dumps(response)
    _write_executable(
        path,
        f"#!/bin/sh\nprintf '%s\\n' '{payload}'\nexit {exit_code}\n",
    )


def _write_executable(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    path.chmod(0o755)
