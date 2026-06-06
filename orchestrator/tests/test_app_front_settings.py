from __future__ import annotations

from pathlib import Path

import pytest

from orchestrator.app_front.settings import AppSettings, SettingsError, SettingsStore


def test_default_settings(tmp_path: Path) -> None:
    store = SettingsStore(tmp_path / "settings.json")

    settings = store.load()

    assert settings.bind_host == "127.0.0.1"
    assert settings.preferred_port == 8765


def test_save_and_load_settings(tmp_path: Path) -> None:
    store = SettingsStore(tmp_path / "settings.json")

    store.save(AppSettings(bind_host="100.64.0.12", preferred_port=9001))

    assert store.load() == AppSettings(bind_host="100.64.0.12", preferred_port=9001)


@pytest.mark.parametrize("port", [0, 80, 65536])
def test_rejects_invalid_port(tmp_path: Path, port: int) -> None:
    store = SettingsStore(tmp_path / "settings.json")

    with pytest.raises(SettingsError):
        store.save(AppSettings(preferred_port=port))


@pytest.mark.parametrize("host", ["", "   ", "http://127.0.0.1", "127.0.0.1:8765", "tail scale"])
def test_rejects_invalid_bind_host(tmp_path: Path, host: str) -> None:
    store = SettingsStore(tmp_path / "settings.json")

    with pytest.raises(SettingsError):
        store.save(AppSettings(bind_host=host, preferred_port=8765))


def test_malformed_json_raises(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    path.write_text("{not json", encoding="utf-8")

    with pytest.raises(SettingsError, match="settings file must contain valid JSON"):
        SettingsStore(path).load()


def test_valid_file_with_invalid_port_raises(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    path.write_text('{"preferred_port": 80}', encoding="utf-8")

    with pytest.raises(SettingsError):
        SettingsStore(path).load()


@pytest.mark.parametrize("content", ["[]", "null"])
def test_valid_file_with_wrong_shape_raises(tmp_path: Path, content: str) -> None:
    path = tmp_path / "settings.json"
    path.write_text(content, encoding="utf-8")

    with pytest.raises(SettingsError, match="settings file must contain a JSON object"):
        SettingsStore(path).load()


@pytest.mark.parametrize(
    ("content", "message"),
    [
        ('{"preferred_port": "abc"}', "preferred port must be an integer"),
        ('{"preferred_port": 9001.5}', "preferred port must be an integer"),
        ('{"preferred_port": "9001"}', "preferred port must be an integer"),
        ('{"bind_host": 127}', "bind host must be a string"),
        ('{"bind_host": "127.0.0.1:8765"}', "bind host must not include a port"),
    ],
)
def test_valid_file_with_wrong_value_type_raises(tmp_path: Path, content: str, message: str) -> None:
    path = tmp_path / "settings.json"
    path.write_text(content, encoding="utf-8")

    with pytest.raises(SettingsError, match=message):
        SettingsStore(path).load()
