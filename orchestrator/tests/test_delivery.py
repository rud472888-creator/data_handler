from __future__ import annotations

import subprocess
from pathlib import Path

from orchestrator import delivery


def test_gateway_delivery_writes_pending_when_gateway_is_stopped(
    monkeypatch,
    tmp_path: Path,
) -> None:
    run_root = tmp_path / "run-test"
    monkeypatch.setattr(delivery, "run_dir", lambda run_id: run_root)

    def fake_run(*args, **kwargs):
        return subprocess.CompletedProcess(
            args=args[0],
            returncode=0,
            stdout="Status: stopped",
            stderr="",
        )

    monkeypatch.setattr(delivery.subprocess, "run", fake_run)

    payload = delivery.deliver_via_hermes_gateway(
        run_id="run-test",
        phase="final",
        message="done",
        profile="macbook-dit-agent",
    )

    assert payload["status"] == "pending"
    assert (run_root / "delivery.final.pending.json").is_file()
