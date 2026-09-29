"""Scheduling, gating, idempotency and hook wiring. No decoding: media are placeholder bytes."""
from __future__ import annotations

import hashlib
import json
import threading
from datetime import datetime, timedelta, timezone

import pytest

from orchestrator import cli, datahelper_worker, run_state  # noqa: F401
from orchestrator.jsonio import read_json, write_json
from orchestrator.visual_qa import scheduler, store, worker
from orchestrator.visual_qa.backend import BackendUnavailable, MockBackend
from orchestrator.visual_qa.scheduler import ScheduleError, schedule_visual_qa
from orchestrator.visual_qa.store import QaDir

from visual_qa_helpers import make_run

CLIPS = {"A001/C0001.mp4": b"not really a video"}


class Spawner:
    def __init__(self):
        self.calls = []

    def __call__(self, run_id, qa_id):
        self.calls.append((run_id, qa_id))
        return 1000 + len(self.calls)


def env_for(tmp_path, monkeypatch, **kw):
    return make_run(tmp_path, monkeypatch, clips=CLIPS, **kw)


def test_option_off_means_no_auto_qa_but_manual_start_works(tmp_path, monkeypatch):
    env = env_for(tmp_path, monkeypatch, visual_qa=False)
    spawn = Spawner()
    result = schedule_visual_qa(env["run_id"], trigger="t", spawn=spawn)
    assert result["status"] == "disabled" and not spawn.calls
    assert not (env["folder"] / "visual_qa").exists()
    manual = schedule_visual_qa(env["run_id"], trigger="ui", manual=True, spawn=spawn)
    assert manual["action"] == "spawned" and len(spawn.calls) == 1


def test_qa_waits_until_existing_reports_finish(tmp_path, monkeypatch):
    env = env_for(tmp_path, monkeypatch, datahelper=False)
    spawn = Spawner()
    assert schedule_visual_qa(env["run_id"], trigger="t", spawn=spawn)["status"] == "waiting"
    with pytest.raises(ScheduleError) as excinfo:
        schedule_visual_qa(env["run_id"], trigger="ui", manual=True, spawn=spawn)
    assert excinfo.value.code == "existing_processing_not_finished" and not spawn.calls
    write_json(env["folder"] / "events/datahelper.done.json", {"status": "failed", "reports": []})
    # a failed report does not prevent QA: backup is verified and replicas exist
    assert schedule_visual_qa(env["run_id"], trigger="t", spawn=spawn)["action"] == "spawned"


def test_copy_only_runs_need_no_datahelper(tmp_path, monkeypatch):
    env = env_for(tmp_path, monkeypatch, datahelper=False, run_mode="datamanager")
    assert schedule_visual_qa(env["run_id"], trigger="t", spawn=Spawner())["action"] == "spawned"


def test_unverified_backup_is_blocked_and_nothing_is_inspected(tmp_path, monkeypatch):
    env = env_for(tmp_path, monkeypatch, verified=False)
    spawn = Spawner()
    result = schedule_visual_qa(env["run_id"], trigger="t", spawn=spawn)
    assert result["status"] == "blocked" and result["reason"] == "backup_not_verified" and not spawn.calls
    marker = read_json(env["folder"] / "visual_qa/blocked.json")
    assert marker["reason"] == "backup_not_verified"
    summary = scheduler.qa_summary(env["run_id"], env["runs_root"])
    assert summary["status"] == "blocked" and summary["blocked"]["reason"] == "backup_not_verified"


def test_missing_manifest_or_replica_links_block(tmp_path, monkeypatch):
    env = env_for(tmp_path, monkeypatch)
    (env["folder"] / "blackmagician/manifest.json").unlink()
    assert schedule_visual_qa(env["run_id"], trigger="t", spawn=Spawner())["reason"] == "manifest_missing"
    done = read_json(env["folder"] / "events/datamanager.done.json")
    done.pop("replica_path_ids")
    write_json(env["folder"] / "events/datamanager.done.json", done)
    assert schedule_visual_qa(env["run_id"], trigger="t", spawn=Spawner())["reason"] == "replica_links_missing"


def test_duplicate_events_start_one_worker_even_concurrently(tmp_path, monkeypatch):
    env = env_for(tmp_path, monkeypatch)
    spawn = Spawner()
    results = []
    threads = [threading.Thread(target=lambda: results.append(
        schedule_visual_qa(env["run_id"], trigger="dup", spawn=spawn, runs_root=env["runs_root"]))) for _ in range(6)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert len(spawn.calls) == 1
    assert sorted(r["action"] for r in results).count("spawned") == 1
    assert len(list((env["folder"] / "visual_qa").glob("qa-*"))) == 1


def test_completed_qa_is_not_rerun_and_new_revision_keeps_the_old_report(tmp_path, monkeypatch):
    env = env_for(tmp_path, monkeypatch)
    spawn = Spawner()
    first = schedule_visual_qa(env["run_id"], trigger="t", spawn=spawn)
    qa = QaDir(env["folder"] / "visual_qa" / first["qa_id"])
    qa.write_state(status=store.COMPLETED)
    qa.report.write_text("<html>old</html>")
    again = schedule_visual_qa(env["run_id"], trigger="t", spawn=spawn)
    assert again["action"] == "already_completed" and len(spawn.calls) == 1
    manual = schedule_visual_qa(env["run_id"], trigger="ui", manual=True, new_revision=True, spawn=spawn)
    assert manual["qa_id"] == first["qa_id"] + "-r2" and manual["action"] == "spawned"
    assert qa.report.read_text() == "<html>old</html>"
    runs = scheduler.qa_summary(env["run_id"], env["runs_root"])["runs"]
    assert [r["qa_id"] for r in runs] == [first["qa_id"], manual["qa_id"]]


def test_different_card_run_has_separate_qa_directory(tmp_path, monkeypatch):
    env = env_for(tmp_path, monkeypatch)
    a = schedule_visual_qa(env["run_id"], trigger="t", spawn=Spawner())
    other = make_run(tmp_path / "other", monkeypatch, run_id="run-qa2", clips=CLIPS)
    b = schedule_visual_qa("run-qa2", trigger="t", spawn=Spawner(), runs_root=other["runs_root"])
    assert a["qa_id"] != b["qa_id"]


def test_changed_input_or_config_gets_new_identity(tmp_path, monkeypatch):
    env = env_for(tmp_path, monkeypatch)
    a = schedule_visual_qa(env["run_id"], trigger="t", spawn=Spawner())
    b = schedule_visual_qa(env["run_id"], trigger="ui", manual=True, spawn=Spawner(), config={"model_max_side": 512})
    assert a["qa_id"] != b["qa_id"]


def test_orphaned_running_qa_is_recovered_but_live_one_is_left_alone(tmp_path, monkeypatch):
    env = env_for(tmp_path, monkeypatch)
    spawn = Spawner()
    first = schedule_visual_qa(env["run_id"], trigger="t", spawn=spawn)
    qa = QaDir(env["folder"] / "visual_qa" / first["qa_id"])
    qa.write_state(status=store.RUNNING, spawned_at=(datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat())
    assert scheduler.qa_summary(env["run_id"], env["runs_root"])["runs"][0]["interrupted"] is True
    with store.file_lock(qa.worker_lock, blocking=False):  # a live worker holds the lock
        assert scheduler.recover_orphans(env["runs_root"], spawn=spawn) == []
        assert schedule_visual_qa(env["run_id"], trigger="t", spawn=spawn)["action"] == "already_running"
    assert scheduler.recover_orphans(env["runs_root"], spawn=spawn) == [f"{env['run_id']}/{first['qa_id']}"]
    assert len(spawn.calls) == 2


def test_recover_does_not_start_new_inspections_for_old_runs(tmp_path, monkeypatch):
    env = env_for(tmp_path, monkeypatch)
    spawn = Spawner()
    assert scheduler.recover_orphans(env["runs_root"], spawn=spawn) == [] and not spawn.calls


def test_failed_partial_qa_is_retried_only_manually(tmp_path, monkeypatch):
    env = env_for(tmp_path, monkeypatch)
    spawn = Spawner()
    first = schedule_visual_qa(env["run_id"], trigger="t", spawn=spawn)
    QaDir(env["folder"] / "visual_qa" / first["qa_id"]).write_state(status=store.PARTIAL)
    assert schedule_visual_qa(env["run_id"], trigger="t", spawn=spawn)["action"] == "existing"
    assert schedule_visual_qa(env["run_id"], trigger="ui", manual=True, spawn=spawn)["action"] == "retry"
    assert len(spawn.calls) == 2


def test_qa_failure_leaves_backup_and_report_state_untouched(tmp_path, monkeypatch):
    env = env_for(tmp_path, monkeypatch)
    watched = [env["folder"] / "events/datamanager.done.json", env["folder"] / "events/datahelper.done.json",
               env["folder"] / "state.json", env["folder"] / "request.json", env["folder"] / "blackmagician/manifest.json"]
    before = {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in watched}
    result = schedule_visual_qa(env["run_id"], trigger="t", spawn=Spawner())
    backend = MockBackend(lambda *a: "")
    backend.ready_error = BackendUnavailable("model_not_installed", "no model")
    state = worker.run(env["run_id"], result["qa_id"], backend=backend, runs_root=env["runs_root"])
    assert state["status"] == "blocked"
    assert before == {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in watched}
    assert read_json(env["folder"] / "state.json")["status"] == "completed"


def test_worker_lock_prevents_double_execution(tmp_path, monkeypatch):
    env = env_for(tmp_path, monkeypatch)
    result = schedule_visual_qa(env["run_id"], trigger="t", spawn=Spawner())
    qa = QaDir(env["folder"] / "visual_qa" / result["qa_id"])
    backend = MockBackend(lambda *a: "")
    with store.file_lock(qa.worker_lock, blocking=False):
        worker.run(env["run_id"], qa.qa_id, backend=backend, runs_root=env["runs_root"])
    assert backend.calls == 0 and not backend.closed


def test_invalid_qa_ids_are_rejected(tmp_path):
    assert scheduler.is_valid_qa_id("qa-0123456789ab") and scheduler.is_valid_qa_id("qa-0123456789ab-r3")
    assert not scheduler.is_valid_qa_id("../x") and not scheduler.is_valid_qa_id("qa-XYZ")


# ---- completion-path wiring ------------------------------------------------

def test_datahelper_finalize_schedules_qa_after_the_final_report(tmp_path, monkeypatch):
    order = []
    monkeypatch.setattr("orchestrator.reporting.write_final_report", lambda run_id: order.append("report"))
    monkeypatch.setattr(scheduler, "schedule_visual_qa", lambda run_id, **kw: order.append(("qa", kw["trigger"])))
    datahelper_worker._finalize("run-x", "completed")
    assert order == ["report", ("qa", "datahelper_worker")]


def test_datahelper_finalize_still_schedules_qa_when_final_report_fails(monkeypatch):
    calls = []

    def boom(run_id):
        raise RuntimeError("report failed")

    monkeypatch.setattr("orchestrator.reporting.write_final_report", boom)
    monkeypatch.setattr(scheduler, "schedule_visual_qa", lambda run_id, **kw: calls.append(run_id))
    datahelper_worker._finalize("run-x", "failed")
    assert calls == ["run-x"]


def test_scheduling_errors_never_break_completion(monkeypatch):
    monkeypatch.setattr("orchestrator.reporting.write_final_report", lambda run_id: None)
    monkeypatch.setattr(scheduler, "schedule_visual_qa", lambda *a, **k: 1 / 0)
    datahelper_worker._finalize("run-x", "completed")  # must not raise


def test_cli_continuations_schedule_qa(tmp_path, monkeypatch):
    env = env_for(tmp_path, monkeypatch)
    write_json(env["folder"] / "request.json", {**read_json(env["folder"] / "request.json")})
    monkeypatch.setattr(cli, "deliver_via_hermes_gateway", lambda **kw: None)
    monkeypatch.setattr(cli, "write_final_report", lambda run_id: env["folder"] / "final-report.md")
    (env["folder"] / "final-report.md").write_text("x")
    calls = []
    monkeypatch.setattr(cli, "schedule_after_completion", lambda run_id, trigger: calls.append(trigger))
    # request.json here is not a valid RunSpec source dir set-up, so drive the function through its spec loader stub
    monkeypatch.setattr(cli, "load_spec", lambda run_id: type("S", (), {"hermes_profile": "p", "run_mode": "workflow"})())
    monkeypatch.setattr(cli, "final_message", lambda *a: "m")
    monkeypatch.setattr(cli, "_datahelper_failed", lambda done: False)
    cli.continue_datahelper(env["run_id"])
    assert calls == ["continue_datahelper"]


def test_watcher_local_agent_path_schedules_qa(tmp_path, monkeypatch):
    from orchestrator import watcher

    env = env_for(tmp_path, monkeypatch)
    write_json(env["folder"] / "agent/approval.json", {"ok": True})
    monkeypatch.setattr(watcher, "load_spec", lambda run_id: type("S", (), {"hermes_profile": "p"})())
    monkeypatch.setattr("orchestrator.reporting.write_final_report", lambda run_id: None)
    calls = []
    monkeypatch.setattr(scheduler, "schedule_visual_qa", lambda run_id, **kw: calls.append(kw["trigger"]))
    watcher._handle_artifact(env["folder"] / "events/datahelper.done.json", direct=True)
    assert calls == ["local-agent-completion"]
