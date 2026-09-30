"""DIT app API for visual QA: separate from agent reviews, guarded, path-safe."""
from __future__ import annotations

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient

from orchestrator.app_front import server as engine
from orchestrator.app_front.settings import SettingsStore
from orchestrator.dit_app.server import create_app
from orchestrator.visual_qa import scheduler, store
from orchestrator.visual_qa.store import QaDir

from visual_qa_helpers import make_run

CLIPS = {"A001/C0001.mp4": b"placeholder"}


@pytest.fixture
def ctx(tmp_path, monkeypatch):
    env = make_run(tmp_path, monkeypatch, clips=CLIPS, visual_qa=False)
    app = create_app(settings_store=SettingsStore(tmp_path / "settings.json"),
                     registry_path=tmp_path / "pipeline" / "console-registry.json", runs_root=env["runs_root"],
                     source_roots=(tmp_path,), destination_roots=(tmp_path,))
    client = TestClient(app, base_url="http://127.0.0.1")
    project = client.post("/api/library/projects", json={"name": "Project"}).json()["project"]
    from orchestrator.web.registry import ConsoleRegistry

    registry = ConsoleRegistry(tmp_path / "pipeline" / "console-registry.json")
    data = registry.load()
    data["runs"].append({"run_id": env["run_id"], "project_id": project["id"], "shoot_date": "2026-01-02",
                         "camera_unit": "A", "roll": "R#1", "source_path": str(tmp_path / "card"),
                         "created_at": "2026-01-02T00:00:00+00:00", "status": "completed"})
    registry.save(data)
    spawned = []
    monkeypatch.setattr(scheduler, "_spawn", lambda run_id, qa_id: spawned.append((run_id, qa_id)) or 77)
    token = client.get("/api/visual-qa/session").json()["token"]
    return {"client": client, "env": env, "project": project, "spawned": spawned, "headers": {"X-DIT-Visual-QA": token}}


def test_card_lists_visual_qa_separately_from_agent_review_and_backup_state(ctx):
    cards = ctx["client"].get(f"/api/library/projects/{ctx['project']['id']}/cards").json()["cards"]
    card = cards[0]
    assert card["visual_qa"]["status"] is None and card["visual_qa"]["runs"] == []
    assert "agent_reviews" in card and card["verified"] is True


def test_manual_start_requires_token_and_uses_the_shared_scheduler(ctx):
    client, run_id = ctx["client"], ctx["env"]["run_id"]
    url = f"/api/library/cards/{run_id}/visual-qa"
    assert client.post(url, json={"action": "start"}).status_code == 401
    response = client.post(url, json={"action": "start"}, headers=ctx["headers"])
    assert response.status_code == 200 and response.json()["action"] == "spawned"
    assert len(ctx["spawned"]) == 1
    again = client.post(url, json={"action": "start"}, headers=ctx["headers"])
    assert again.json()["action"] == "already_running" and len(ctx["spawned"]) == 1
    summary = client.get(url).json()
    assert summary["status"] == "queued" and summary["runs"][0]["report_ready"] is False


def test_manual_start_reports_conflict_when_not_ready(ctx):
    (ctx["env"]["folder"] / "events/datahelper.done.json").unlink()
    response = ctx["client"].post(f"/api/library/cards/{ctx['env']['run_id']}/visual-qa", json={"action": "start"},
                                  headers=ctx["headers"])
    assert response.status_code == 409 and "끝나지" in response.json()["detail"]


def test_cross_site_requests_are_rejected(ctx):
    response = ctx["client"].post(f"/api/library/cards/{ctx['env']['run_id']}/visual-qa", json={"action": "start"},
                                  headers={**ctx["headers"], "Origin": "http://evil.example"})
    assert response.status_code == 403


def test_unknown_run_and_traversal_are_rejected(ctx):
    client = ctx["client"]
    assert client.get("/api/library/cards/run-nope/visual-qa").status_code == 404
    assert client.get("/api/library/visual-qa/run-qa1/..%2F..%2Fx/report.html").status_code == 404


def test_report_and_evidence_are_served_but_nothing_else(ctx):
    client, run_id = ctx["client"], ctx["env"]["run_id"]
    result = client.post(f"/api/library/cards/{run_id}/visual-qa", json={"action": "start"}, headers=ctx["headers"]).json()
    qa = QaDir(ctx["env"]["folder"] / "visual_qa" / result["qa_id"])
    qa.report.write_text("<html>report</html>")
    (qa.evidence / "c1").mkdir(parents=True)
    (qa.evidence / "c1" / "0000001.jpg").write_bytes(b"\xff\xd8jpeg")
    base = f"/api/library/visual-qa/{run_id}/{qa.qa_id}"
    page = client.get(f"{base}/report.html")
    assert page.status_code == 200 and "default-src 'none'" in page.headers["content-security-policy"]
    assert client.get(f"{base}/evidence/c1/0000001.jpg").status_code == 200
    for denied in ("manifest.json", "state.json", "frames.jsonl", "worker.lock", "evidence/c1", "evidence/../manifest.json",
                   "evidence/c1/../../manifest.json", "%2e%2e/%2e%2e/request.json"):
        assert client.get(f"{base}/{denied}").status_code == 404, denied
    assert client.get(f"/api/library/visual-qa/{run_id}/qa-NOTVALID/report.html").status_code == 404


def test_project_option_applies_to_new_runs_only_and_reaches_the_request(ctx, monkeypatch, tmp_path):
    client = ctx["client"]
    option = client.post(f"/api/library/projects/{ctx['project']['id']}/visual-qa", json={"enabled": True}, headers=ctx["headers"])
    assert option.json()["visual_qa"] is True
    assert client.get("/api/projects").json()["projects"][0]["visual_qa"] is True
    # existing completed card stayed untouched: no QA appeared by itself
    assert scheduler.qa_summary(ctx["env"]["run_id"], ctx["env"]["runs_root"])["runs"] == []
    calls = []
    monkeypatch.setattr(engine, "start_run", lambda **kw: calls.append(kw))
    source, one = tmp_path / "src2", tmp_path / "rep2"
    source.mkdir(), one.mkdir()
    payload = {"project_id": ctx["project"]["id"], "shoot_date": "2026-09-08", "camera_unit": "A",
               "source_path": str(source), "replica_roots": [str(one)]}
    assert client.post("/api/runs", json=payload).status_code == 200
    assert calls[0]["visual_qa"] is True
    client.post(f"/api/library/projects/{ctx['project']['id']}/visual-qa", json={"enabled": False}, headers=ctx["headers"])
    assert client.post("/api/runs", json=payload).status_code == 200
    assert calls[1]["visual_qa"] is False
    assert client.post("/api/runs", json={**payload, "visual_qa": True}).status_code == 200 and calls[2]["visual_qa"] is True


def test_run_spec_persists_the_option_only_when_enabled(tmp_path):
    from orchestrator.spec import RunSpec

    source, replica = tmp_path / "s", tmp_path / "r"
    source.mkdir(), replica.mkdir()
    spec = RunSpec(run_id="r", project_name="P", source_path=source, replica_roots=(replica,), visual_qa=True)
    assert spec.to_payload()["visual_qa"] is True and RunSpec.from_payload(spec.to_payload()).visual_qa is True
    plain = RunSpec(run_id="r", project_name="P", source_path=source, replica_roots=(replica,))
    assert "visual_qa" not in plain.to_payload() and RunSpec.from_payload(plain.to_payload()).visual_qa is False


def test_cancel_endpoint_marks_request(ctx):
    client, run_id = ctx["client"], ctx["env"]["run_id"]
    qa_id = client.post(f"/api/library/cards/{run_id}/visual-qa", json={"action": "start"}, headers=ctx["headers"]).json()["qa_id"]
    assert client.post(f"/api/library/cards/{run_id}/visual-qa/{qa_id}/cancel", json={}, headers=ctx["headers"]).status_code == 200
    assert (ctx["env"]["folder"] / "visual_qa" / qa_id / "cancel.requested").exists()
