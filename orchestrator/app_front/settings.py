from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from orchestrator.jsonio import read_json, write_json
from orchestrator.paths import PIPELINE_ROOT

DEFAULT_SETTINGS_PATH = PIPELINE_ROOT / "app-front-settings.json"


class SettingsError(ValueError):
    pass


@dataclass(frozen=True)
class AppSettings:
    bind_host: str = "127.0.0.1"
    preferred_port: int = 8765


class SettingsStore:
    def __init__(self, path: Path = DEFAULT_SETTINGS_PATH) -> None:
        self.path = path

    def load(self) -> AppSettings:
        if not self.path.exists():
            return AppSettings()
        try:
            payload = read_json(self.path)
        except json.JSONDecodeError as exc:
            raise SettingsError("settings file must contain valid JSON") from exc
        return _settings_from_payload(payload)

    def save(self, settings: AppSettings) -> AppSettings:
        _validate_bind_host(settings.bind_host)
        _validate_port(settings.preferred_port)
        write_json(self.path, asdict(settings))
        return settings


def _settings_from_payload(payload: Any) -> AppSettings:
    if not isinstance(payload, dict):
        raise SettingsError("settings file must contain a JSON object")
    bind_host = payload.get("bind_host", "127.0.0.1")
    preferred_port = payload.get("preferred_port", 8765)
    _validate_bind_host(bind_host)
    _validate_port(preferred_port)
    return AppSettings(
        bind_host=bind_host,
        preferred_port=preferred_port,
    )


def _validate_bind_host(host: str) -> None:
    if type(host) is not str:
        raise SettingsError("bind host must be a string")
    stripped = host.strip()
    if not stripped:
        raise SettingsError("bind host must not be empty")
    if stripped != host:
        raise SettingsError("bind host must not include leading or trailing spaces")
    if any(character.isspace() for character in host):
        raise SettingsError("bind host must not contain spaces")
    if "://" in host or "/" in host:
        raise SettingsError("bind host must be a host or IP address, not a URL")
    if ":" in host:
        raise SettingsError("bind host must not include a port")


def _validate_port(port: int) -> None:
    if type(port) is not int:
        raise SettingsError("preferred port must be an integer")
    if port < 1024 or port > 65535:
        raise SettingsError("preferred port must be between 1024 and 65535")

