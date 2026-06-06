from __future__ import annotations

import os
import subprocess
import sys

from orchestrator.paths import LOG_ROOT, ROOT


def spawn_python_module(run_id: str, module: str, *args: str) -> int:
    LOG_ROOT.mkdir(parents=True, exist_ok=True)
    stdout_path = LOG_ROOT / f"{run_id}.{module.rsplit('.', 1)[-1]}.out.log"
    stderr_path = LOG_ROOT / f"{run_id}.{module.rsplit('.', 1)[-1]}.err.log"
    env = os.environ.copy()
    env["PYTHONPATH"] = _prepend_pythonpath(str(ROOT), env.get("PYTHONPATH"))
    with stdout_path.open("ab") as stdout, stderr_path.open("ab") as stderr:
        process = subprocess.Popen(
            [sys.executable, "-m", module, *args],
            cwd=str(ROOT),
            env=env,
            stdout=stdout,
            stderr=stderr,
            start_new_session=True,
        )
    return int(process.pid)


def _prepend_pythonpath(path: str, current: str | None) -> str:
    if not current:
        return path
    return f"{path}{os.pathsep}{current}"
