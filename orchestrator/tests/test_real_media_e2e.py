from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from orchestrator import datahelper_worker, datamanager_worker, reporting, run_state
from orchestrator.spec import RunSpec


def test_real_media_datamanager_datahelper_final_report_e2e(monkeypatch, tmp_path: Path) -> None:
    ffmpeg = shutil.which("ffmpeg")
    assert ffmpeg is not None, "ffmpeg is required to generate real mp4/mov fixtures"
    _patch_run_state(monkeypatch, tmp_path)
    monkeypatch.setattr(
        datamanager_worker,
        "spawn_python_module",
        lambda *_args, **_kwargs: 1234,
        raising=False,
    )
    source1 = tmp_path / "source-a"
    source2 = tmp_path / "source-b"
    path1 = tmp_path / "path1"
    path2 = tmp_path / "path2"
    for directory in (source1, source2, path1, path2):
        directory.mkdir()
    _write_media(ffmpeg, source1 / "A001_C001.mp4")
    _write_media(ffmpeg, source1 / "A001_C002.mov")
    _write_media(ffmpeg, source2 / "B001_C001.mp4")
    _write_media(ffmpeg, source2 / "B001_C002.mov")
    run_state.save_spec(
        RunSpec(
            run_id="run-real-media",
            project_name="Real Media Project",
            source_path=source1,
            extra_source_paths=(source2,),
            replica_roots=(path1, path2),
            footage_run_name="260601/A-cam/R#1",
        )
    )

    dm_payload = datamanager_worker.run_datamanager("run-real-media")
    dh_payload = datahelper_worker.run_datahelper("run-real-media")
    final_report = reporting.write_final_report("run-real-media")

    assert dm_payload["status"] == "completed"
    assert dm_payload["replicas_complete"] is True
    assert dm_payload["file_count"] == 4
    assert dm_payload["replica_count"] == 2
    assert dm_payload["source_path_ids"] == ["source-path-1", "source-path-2"]
    assert _copied_files(path1) == _copied_files(path2) == {
        "source-path-1/A001_C001.mp4",
        "source-path-1/A001_C002.mov",
        "source-path-2/B001_C001.mp4",
        "source-path-2/B001_C002.mov",
    }
    assert dh_payload["status"] == "completed"
    assert len(dh_payload["reports"]) == 2
    for report in dh_payload["reports"]:
        assert report["exit_code"] == 0
        assert Path(report["pdf_path"]).is_file()
        assert Path(report["csv_path"]).is_file()
        assert Path(report["json_path"]).is_file()
    report_text = final_report.read_text(encoding="utf-8")
    assert str(source1) in report_text
    assert str(source2) in report_text
    assert "### path1" in report_text
    assert "### path2" in report_text


def test_live_external_footage_e2e_when_env_provides_media(monkeypatch, tmp_path: Path) -> None:
    media_values = _live_media_values()
    if not media_values:
        pytest.skip(
            "set DIT_LIVE_MEDIA_PATHS to at least two existing .mp4/.mov/.mxf/.braw/.r3d/.ari files or folders for live footage E2E"
        )
    media_files = _live_media_files(media_values)
    if len(media_files) < 2:
        pytest.skip("DIT_LIVE_MEDIA_PATHS did not resolve to at least two supported media files")

    _patch_run_state(monkeypatch, tmp_path)
    monkeypatch.setattr(
        datamanager_worker,
        "spawn_python_module",
        lambda *_args, **_kwargs: 1234,
        raising=False,
    )
    source = tmp_path / "live-source"
    path1 = tmp_path / "path1"
    path2 = tmp_path / "path2"
    for directory in (source, path1, path2):
        directory.mkdir()
    copied_sources: list[Path] = []
    for index, media in enumerate(media_files[:2], start=1):
        target = source / f"live-{index}{media.suffix.lower()}"
        shutil.copy2(media, target)
        copied_sources.append(target)
    run_state.save_spec(
        RunSpec(
            run_id="run-live-media",
            project_name="Live Media Project",
            source_path=source,
            replica_roots=(path1, path2),
            footage_run_name="260601/A-cam/R#1",
        )
    )

    dm_payload = datamanager_worker.run_datamanager("run-live-media")
    dh_payload = datahelper_worker.run_datahelper("run-live-media")
    final_report = reporting.write_final_report("run-live-media")

    assert dm_payload["status"] == "completed"
    assert dh_payload["status"] == "completed"
    assert final_report.is_file()
    for source_file in copied_sources:
        source_hash = _sha256(source_file)
        replica_relpath = Path("Live Media Project/01_Footage/260601/A-cam/R#1/source-path-1") / source_file.name
        assert _sha256(path1 / replica_relpath) == source_hash
        assert _sha256(path2 / replica_relpath) == source_hash


def _patch_run_state(monkeypatch, tmp_path: Path) -> None:
    runs_root = tmp_path / "runs"
    monkeypatch.setattr(run_state, "RUNS_ROOT", runs_root)
    for module in (datamanager_worker, datahelper_worker, reporting):
        monkeypatch.setattr(module, "run_dir", run_state.run_dir)
        monkeypatch.setattr(module, "events_dir", run_state.events_dir)
        monkeypatch.setattr(module, "load_spec", run_state.load_spec)
    monkeypatch.setattr(datamanager_worker, "update_state", run_state.update_state)
    monkeypatch.setattr(datahelper_worker, "update_state", run_state.update_state)


def _write_media(ffmpeg: str, path: Path) -> None:
    subprocess.run(
        [
            ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            "testsrc=size=160x90:rate=24",
            "-t",
            "0.5",
            "-pix_fmt",
            "yuv420p",
            str(path),
        ],
        check=True,
    )


def _copied_files(replica_root: Path) -> set[str]:
    footage = replica_root / "Real Media Project" / "01_Footage" / "260601" / "A-cam" / "R#1"
    return {
        path.relative_to(footage).as_posix()
        for path in footage.rglob("*")
        if path.is_file()
    }


def _live_media_values() -> list[Path]:
    configured = os.environ.get("DIT_LIVE_MEDIA_PATHS", "")
    return [Path(value).expanduser() for value in configured.split(os.pathsep) if value]


def _live_media_files(values: list[Path]) -> list[Path]:
    suffixes = {".ari", ".braw", ".mov", ".mp4", ".mxf", ".r3d"}
    files: list[Path] = []
    for value in values:
        if value.is_file() and value.suffix.lower() in suffixes:
            files.append(value)
        elif value.is_dir():
            files.extend(
                path
                for path in sorted(value.rglob("*"))
                if path.is_file() and path.suffix.lower() in suffixes
            )
    return files


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
