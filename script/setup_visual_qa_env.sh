#!/usr/bin/env bash
# Creates the dedicated visual-QA virtualenv outside the app bundle (Apple Silicon macOS).
set -euo pipefail
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
QA_HOME="${DATA_HANDLER_VISUAL_QA_HOME:-$HOME/Library/Application Support/Data Handler/visual-qa}"
PYTHON_BIN="${PYTHON_BIN:-python3}"
mkdir -p "$QA_HOME"
"$PYTHON_BIN" -m venv "$QA_HOME/venv"
"$QA_HOME/venv/bin/pip" install --upgrade pip
"$QA_HOME/venv/bin/pip" install -r "$ROOT_DIR/orchestrator/visual_qa/requirements.txt"
echo "Visual QA environment: $QA_HOME/venv"
echo "Next: PYTHONPATH=$ROOT_DIR $QA_HOME/venv/bin/python -m orchestrator.cli visual-qa install-model"
