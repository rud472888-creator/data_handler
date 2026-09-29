"""Where the QA runtime, model cache and settings live. Stdlib only."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

from orchestrator import paths
from orchestrator.jsonio import read_json, write_json

MODEL_MANIFEST = "model-install.json"


def qa_home() -> Path:
    """Model cache and inference venv, deliberately outside the app bundle."""
    configured = os.environ.get("DATA_HANDLER_VISUAL_QA_HOME")
    if configured:
        return Path(configured).expanduser()
    if sys.platform == "darwin":
        return Path.home() / "Library/Application Support/Data Handler/visual-qa"
    return Path.home() / ".cache/data-handler/visual-qa"


def model_dir() -> Path:
    return qa_home() / "models"


def settings_path() -> Path:
    return paths.PIPELINE_ROOT / "visual-qa-settings.json"


def runtime_python() -> str:
    """Interpreter for the worker: the dedicated QA venv when present."""
    configured = os.environ.get("DATA_HANDLER_VISUAL_QA_PYTHON")
    if configured:
        return configured
    candidate = qa_home() / "venv/bin/python"
    return str(candidate) if candidate.is_file() else sys.executable


def load_settings() -> dict[str, Any]:
    """App-level defaults for new QA runs (config overrides, backend name)."""
    path = settings_path()
    try:
        payload = read_json(path) if path.is_file() else {}
    except (OSError, ValueError):
        payload = {}
    return payload if isinstance(payload, dict) else {}


def save_settings(payload: dict[str, Any]) -> None:
    write_json(settings_path(), payload)


def read_model_manifest(directory: Path | None = None) -> dict[str, Any] | None:
    path = (directory or model_dir()) / MODEL_MANIFEST
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return payload if isinstance(payload, dict) else None
