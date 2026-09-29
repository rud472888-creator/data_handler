from __future__ import annotations

import json
import os
import secrets
from pathlib import Path

from orchestrator.paths import PIPELINE_ROOT


def private_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.' + secrets.token_hex(6) + '.tmp')
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'w') as stream:
        json.dump(payload, stream, ensure_ascii=False, indent=2)
    temporary.replace(path)


def config_path() -> Path:
    return PIPELINE_ROOT / 'agent/config.json'


def load_config() -> dict:
    return json.loads(config_path().read_text())


def initialize(model_path: str, allowed_roots: list[str]) -> dict:
    if config_path().exists():
        return load_config()
    config = {
        'api_token': secrets.token_urlsafe(32),
        'pairing_code': secrets.token_urlsafe(24),
        'model_path': model_path,
        'inference_url': 'http://127.0.0.1:8767',
        'allowed_roots': allowed_roots,
        'telegram_token_file': str(PIPELINE_ROOT / 'agent/telegram-token'),
        'allowed_user_id': None,
        'allowed_chat_id': None,
    }
    private_json(config_path(), config)
    return config
