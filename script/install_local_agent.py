#!/usr/bin/env python3
"""Install user launch agents; never stores credentials in plist or argv."""
from __future__ import annotations

import os
import plistlib
import subprocess
import sys
from pathlib import Path


def main():
    root = Path(__file__).resolve().parents[1]
    python = root / '.pipeline/agent-venv/bin/python'
    if not python.is_file():
        raise SystemExit('Install orchestrator/agent/requirements.lock into .pipeline/agent-venv first')
    support = Path.home() / 'Library/Application Support/Data Handler'
    logs = support / 'logs'
    logs.mkdir(parents=True, exist_ok=True)
    env = {'DATA_HANDLER_PIPELINE_ROOT': str(support / '.pipeline'),
           'PYTHONPATH': str(root), 'PYTHONDONTWRITEBYTECODE': '1',
           'HF_HUB_OFFLINE': '1', 'TRANSFORMERS_OFFLINE': '1',
           'PATH': '/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin'}
    launch = Path.home() / 'Library/LaunchAgents'
    launch.mkdir(exist_ok=True)
    domain = f'gui/{os.getuid()}'
    for command, suffix in [('inference', 'inference'), ('serve', 'agent')]:
        label = 'com.dit.data-handler.' + suffix
        path = launch / (label + '.plist')
        payload = {'Label': label, 'ProgramArguments': [str(python), '-m', 'orchestrator.agent', command],
                   'WorkingDirectory': str(root), 'EnvironmentVariables': env,
                   'RunAtLoad': True, 'KeepAlive': True, 'ThrottleInterval': 15, 'Umask': 0o077,
                   'StandardOutPath': str(logs / (suffix + '.out.log')),
                   'StandardErrorPath': str(logs / (suffix + '.err.log'))}
        with path.open('wb') as file:
            plistlib.dump(payload, file)
        os.chmod(path, 0o600)
        subprocess.run(['launchctl', 'bootout', domain + '/' + label], capture_output=True)
        subprocess.run(['launchctl', 'bootstrap', domain, str(path)], check=True)
        print('Installed ' + label)


if __name__ == '__main__':
    main()
