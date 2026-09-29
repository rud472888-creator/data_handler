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
    if sys.platform == 'darwin' and os.path.isfile('/usr/bin/caffeinate'):
        # Tie the sleep assertion to the worker, not the UI or messenger process.
        try:
            subprocess.Popen(['/usr/bin/caffeinate', '-i', '-w', str(process.pid)],
                             stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL, start_new_session=True)
        except OSError:
            pass
    return int(process.pid)


def _prepend_pythonpath(path: str, current: str | None) -> str:
    if not current:
        return path
    return f"{path}{os.pathsep}{current}"
