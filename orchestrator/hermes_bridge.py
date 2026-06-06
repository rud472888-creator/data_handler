from __future__ import annotations

import subprocess
from typing import Any

from orchestrator.jsonio import write_json
from orchestrator.paths import DEFAULT_HERMES_PROFILE, ROOT
from orchestrator.run_state import run_dir, utc_now


def launch_wakeup_session(
    run_id: str,
    phase: str,
    profile: str = DEFAULT_HERMES_PROFILE,
) -> dict[str, Any]:
    command_name = "continue-datamanager" if phase == "datamanager" else "continue-datahelper"
    prompt = (
        "You are the Hermes wakeup agent for the local data pipeline.\n"
        "Do not inspect progress in real time. Read the run artifacts and execute "
        "exactly this command:\n"
        f"cd {ROOT} && python -m orchestrator.cli {command_name} --run-id {run_id}\n"
        "After the command completes, summarize the artifact paths briefly."
    )
    command = ["hermes", "--profile", profile, "chat", "-q", prompt, "-Q", "--source", "pipeline"]
    try:
        completed = subprocess.run(
            command,
            cwd=str(ROOT),
            text=True,
            capture_output=True,
            check=False,
            timeout=600,
        )
        payload: dict[str, Any] = {
            "run_id": run_id,
            "phase": phase,
            "status": "launched" if completed.returncode == 0 else "failed",
            "command": command,
            "returncode": completed.returncode,
            "stdout": completed.stdout,
            "stderr": completed.stderr,
            "created_at": utc_now(),
        }
    except (OSError, subprocess.TimeoutExpired) as exc:
        payload = {
            "run_id": run_id,
            "phase": phase,
            "status": "failed",
            "error": str(exc),
            "created_at": utc_now(),
        }
    write_json(run_dir(run_id) / f"wakeup.{phase}.json", payload)
    return payload
