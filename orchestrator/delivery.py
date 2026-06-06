from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

from orchestrator.jsonio import write_json
from orchestrator.paths import DEFAULT_HERMES_PROFILE
from orchestrator.run_state import run_dir, utc_now


def deliver_via_hermes_gateway(
    *,
    run_id: str,
    phase: str,
    message: str,
    profile: str = DEFAULT_HERMES_PROFILE,
) -> dict[str, Any]:
    status = _gateway_status(profile)
    if not status["running"]:
        payload = _pending_payload(run_id, phase, profile, status["reason"], message)
        write_json(run_dir(run_id) / f"delivery.{phase}.pending.json", payload)
        return payload

    prompt = (
        "Use the send_message tool to send this exact message to telegram home. "
        "Do not merely summarize it.\n\n"
        f"{message}"
    )
    command = ["hermes", "--profile", profile, "chat", "-q", prompt, "-Q", "--source", "pipeline"]
    completed = subprocess.run(command, text=True, capture_output=True, check=False, timeout=120)
    payload: dict[str, Any] = {
        "run_id": run_id,
        "phase": phase,
        "status": "sent" if completed.returncode == 0 else "pending",
        "profile": profile,
        "command": command,
        "stdout": completed.stdout,
        "stderr": completed.stderr,
        "returncode": completed.returncode,
        "created_at": utc_now(),
    }
    target = run_dir(run_id) / (
        f"delivery.{phase}.json" if completed.returncode == 0 else f"delivery.{phase}.pending.json"
    )
    write_json(target, payload)
    return payload


def _gateway_status(profile: str) -> dict[str, Any]:
    try:
        completed = subprocess.run(
            ["hermes", "--profile", profile, "gateway", "status"],
            text=True,
            capture_output=True,
            check=False,
            timeout=20,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"running": False, "reason": str(exc)}
    output = f"{completed.stdout}\n{completed.stderr}".lower()
    if completed.returncode != 0:
        return {"running": False, "reason": output.strip() or "gateway status failed"}
    if "stopped" in output or "not configured" in output or "✗" in output:
        return {"running": False, "reason": output.strip() or "gateway is not ready"}
    return {"running": True, "reason": output.strip()}


def _pending_payload(
    run_id: str,
    phase: str,
    profile: str,
    reason: str,
    message: str,
) -> dict[str, Any]:
    return {
        "run_id": run_id,
        "phase": phase,
        "status": "pending",
        "profile": profile,
        "reason": reason,
        "message": message,
        "retry_hint": (
            "Run `hermes gateway setup` and `hermes gateway start`, then rerun the "
            "matching continue command."
        ),
        "created_at": utc_now(),
    }


def read_markdown(path: Path) -> str:
    return path.read_text(encoding="utf-8")
