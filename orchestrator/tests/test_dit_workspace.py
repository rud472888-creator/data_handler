from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from orchestrator.app_front import server as engine
from orchestrator.app_front.settings import SettingsStore
from orchestrator.dit_app.server import card_snapshot, create_app
from orchestrator.jsonio import write_json


def client(tmp_path):
    return TestClient(create_app(
        settings_store=SettingsStore(tmp_path / "settings.json"),
        registry_path=tmp_path / "registry.json", runs_root=tmp_path / "runs",
        source_roots=(tmp_path,), destination_roots=(tmp_path,),
    ))


def test_project_without_disks_persists_and_rejects_duplicate(tmp_path):
    app = client(tmp_path)
    response = app.post("/api/library/projects", json={"name": "야간 촬영"})
    assert response.status_code == 201
    project = response.json()["project"]
    assert project["replica_roots"] == []
    assert client(tmp_path).get("/api/projects").json()["projects"][0]["id"] == project["id"]
    assert app.post("/api/library/projects", json={"name": "야간 촬영"}).status_code == 409
    assert app.get(f'/api/library/projects/{project["id"]}/cards').json() == {"cards": []}
    assert not (tmp_path / "야간 촬영").exists()


@pytest.mark.parametrize("name", ["", "../escape", "a/b", "a\\b", ".."])
def test_invalid_project_names(tmp_path, name):
    assert client(tmp_path).post("/api/library/projects", json={"name": name}).status_code == 400


def test_new_project_can_preview_and_start_existing_engine(tmp_path, monkeypatch):
    app = client(tmp_path)
    project = app.post("/api/library/projects", json={"name": "Film"}).json()["project"]
    source, first, second = [tmp_path / name for name in ("card", "one", "two")]
    for folder in (source, first, second):
        folder.mkdir()
    calls = []
    monkeypatch.setattr(engine, "start_run", lambda **kw: calls.append(kw))
    payload = {"project_id": project["id"], "shoot_date": "2026-09-08", "camera_unit": "A", "source_path": str(source), "replica_roots": [str(first), str(second)]}
    preview = app.post("/api/roll-preview", json=payload)
    assert preview.status_code == 200
    response = app.post("/api/runs", json=payload)
    assert response.status_code == 200
    assert calls[0]["source_paths"] == (source,)
    assert calls[0]["replica_paths"] == (first, second)
    assert calls[0]["footage_run_name"] == preview.json()["footage_run_name"]
    cards = app.get(f'/api/library/projects/{project["id"]}/cards').json()["cards"]
    assert len(cards) == 1
    assert cards[0]["verified"] is False


def test_completion_requires_checksum_evidence_and_preserves_report_failure(tmp_path):
    record = {"run_id": "run-test"}
    folder = tmp_path / "run-test"
    write_json(folder / "state.json", {"status": "completed"})
    assert card_snapshot(record, tmp_path)["verified"] is False
    write_json(folder / "events/datamanager.done.json", {"status": "completed", "replicas_complete": True})
    write_json(folder / "events/datahelper.done.json", {"status": "failed", "error": "decoder unavailable"})
    result = card_snapshot(record, tmp_path)
    assert result["verified"] is True
    assert result["phase"] == "failed"
    assert result["error"] == "decoder unavailable"


def test_report_success_does_not_hide_unverified_copy(tmp_path):
    write_json(tmp_path / "run-test/events/datahelper.done.json", {"status": "completed"})
    assert card_snapshot({"run_id": "run-test"}, tmp_path)["phase"] == "review"


def test_missing_pdf_is_not_a_download_link(tmp_path):
    folder = tmp_path / "run-test"
    write_json(folder / "events/datahelper.done.json", {"status": "completed", "reports": [{"pdf_path": str(folder / "absent.pdf")} ]})
    artifacts = card_snapshot({"run_id": "run-test"}, tmp_path)["artifacts"]
    assert artifacts[0]["available"] is False
    assert artifacts[0]["url"] is None


def test_workspace_and_legacy_api_are_both_served(tmp_path):
    app = client(tmp_path)
    assert "프로젝트 라이브러리" in app.get("/").text
    assert app.get("/workspace-static/app.js").status_code == 200
    assert app.get("/api/projects").status_code == 200


def test_real_card_copy_and_pdf_through_workspace(tmp_path, monkeypatch):
    import hashlib
    import shutil
    import subprocess

    from orchestrator import cli, datahelper_worker, datamanager_worker, run_state, stages

    source, first, second = [tmp_path / name for name in ("source", "replica-a", "replica-b")]
    for folder in (source, first, second):
        folder.mkdir()
    subprocess.run([
        shutil.which("ffmpeg"), "-v", "error", "-f", "lavfi", "-i",
        "color=c=blue:s=320x240:r=24", "-t", "0.25", "-c:v", "libx264",
        "-pix_fmt", "yuv420p", str(source / "A001.mp4"),
    ], check=True)
    monkeypatch.setattr(run_state, "RUNS_ROOT", tmp_path / "runs")
    monkeypatch.setattr(cli, "spawn_python_module", lambda *args: 1)
    monkeypatch.setattr(stages, "spawn_python_module", lambda *args: 1)
    app = client(tmp_path)
    project = app.post("/api/library/projects", json={"name": "Workspace E2E"}).json()["project"]
    response = app.post("/api/runs", json={
        "project_id": project["id"], "shoot_date": "2026-09-08", "camera_unit": "A",
        "source_path": str(source), "replica_roots": [str(first), str(second)],
    })
    assert response.status_code == 200, response.text
    run_id = response.json()["run_id"]
    datamanager_worker.run_datamanager(run_id)
    datahelper_worker.run_datahelper(run_id)
    card = app.get(f'/api/library/projects/{project["id"]}/cards').json()["cards"][0]
    assert card["verified"] is True
    assert card["phase"] == "reported"
    original_hash = hashlib.sha256((source / "A001.mp4").read_bytes()).hexdigest()
    for destination in card["destinations"]:
        assert Path(destination).parts[-2:] == ("001_Footage", "R#1")
        copied = Path(destination) / "A001.mp4"
        assert not (Path(destination) / "source-path-1").exists()
        assert hashlib.sha256(copied.read_bytes()).hexdigest() == original_hash
    assert not (first / "Workspace E2E" / "01_Footage").exists()
    pdfs = [a for a in card["artifacts"] if a["path"].endswith(".pdf")]
    assert len(pdfs) >= 3
    for pdf in pdfs:
        download = app.get(pdf["url"])
        assert download.status_code == 200
        assert download.content.startswith(b"%PDF")
        assert download.headers["content-type"] == "application/pdf"
    assert app.get(f"/api/library/reports/{run_id}/-1").status_code == 404


def test_remove_project_hides_only_library_entry_and_undo_restores(tmp_path):
    app = client(tmp_path)
    project = app.post("/api/library/projects", json={"name": "Keep files"}).json()["project"]
    original = tmp_path / "original.mov"
    original.write_bytes(b"original footage")
    assert app.post(f'/api/library/projects/{project["id"]}/remove').status_code == 200
    assert client(tmp_path).get("/api/projects").json()["projects"] == []
    assert original.read_bytes() == b"original footage"
    assert app.post(f'/api/library/projects/{project["id"]}/restore').status_code == 200
    assert app.get("/api/projects").json()["projects"][0]["id"] == project["id"]


def test_remove_does_not_hide_running_report_after_copy_completed(tmp_path):
    app = client(tmp_path)
    project = app.post("/api/library/projects", json={"name": "Running"}).json()["project"]
    from orchestrator.web.registry import ConsoleRegistry
    registry = ConsoleRegistry(tmp_path / "registry.json")
    data = registry.load()
    data["runs"].append({"run_id": "run-busy", "project_id": project["id"], "status": "started"})
    registry.save(data)
    folder = tmp_path / "runs/run-busy"
    write_json(folder / "state.json", {"stage": "datamanager", "status": "completed"})
    write_json(folder / "request.json", {"run_mode": "workflow"})
    assert app.post(f'/api/library/projects/{project["id"]}/remove').status_code == 409
    write_json(folder / "events/datahelper.done.json", {"status": "completed"})
    assert app.post(f'/api/library/projects/{project["id"]}/remove').status_code == 200


def test_flat_rolls_are_project_wide_and_skip_existing_destination(tmp_path, monkeypatch):
    app = client(tmp_path)
    project = app.post("/api/library/projects", json={"name": "Rolls"}).json()["project"]
    source, dest = tmp_path / "card", tmp_path / "backup"
    source.mkdir(); dest.mkdir()
    monkeypatch.setattr(engine, "start_run", lambda **kw: None)
    payload = {"project_id": project["id"], "shoot_date": "2026-09-08", "camera_unit": "A", "source_path": str(source), "replica_roots": [str(dest)]}
    assert app.post("/api/runs", json=payload).json()["roll"] == "R#1"
    payload.update(shoot_date="2026-09-09", camera_unit="B")
    preview = app.post("/api/roll-preview", json=payload).json()
    assert preview["roll"] == "R#2"
    assert preview["replica_destinations"] == [str(dest / "Rolls/001_Footage/R#2")]
    (dest / "Rolls/001_Footage/R#9").mkdir(parents=True)
    assert app.post("/api/runs", json=payload).json()["roll"] == "R#10"
