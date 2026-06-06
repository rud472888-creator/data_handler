from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA_MANAGER_ROOT = ROOT / "DataManager"
DATA_HELPER_ROOT = ROOT / "DataHelper"
PIPELINE_ROOT = Path(os.environ.get("DATA_HANDLER_PIPELINE_ROOT", ROOT / ".pipeline"))
RUNS_ROOT = PIPELINE_ROOT / "runs"
LOG_ROOT = PIPELINE_ROOT / "logs"
WATCH_STATE_PATH = PIPELINE_ROOT / "watcher-state.json"
DEFAULT_HERMES_PROFILE = "macbook-dit-agent"
