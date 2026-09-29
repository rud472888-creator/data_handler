"""Explicit model installation. Running QA never downloads or converts weights."""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from orchestrator.visual_qa.config import ORIGINAL_MODEL_ID
from orchestrator.visual_qa.settings import MODEL_MANIFEST, model_dir
from orchestrator.visual_qa.store import utc_now, write_json_atomic


def _dir_size(path: Path) -> int:
    return sum(p.stat().st_size for p in path.rglob("*") if p.is_file())


def install_model(*, source_repo: str = ORIGINAL_MODEL_ID, revision: str | None = None,
                  quantization: str | None = None, derived_from: str | None = None,
                  local_path: Path | None = None) -> dict[str, Any]:
    """Download (needs network) or register (offline) the Qwen3.5-4B weights.

    * ``source_repo`` defaults to the original model. A different repo (for example a
      verified MLX quantization of it) must state ``quantization`` and
      ``derived_from == Qwen/Qwen3.5-4B``; the app cannot verify that claim, so it
      is stored as ``derived_from_claimed``.
    * ``revision`` is resolved to the commit hash on the hub at install time.
    * ``local_path`` registers an already-downloaded directory without any network
      access; its revision is stored only if the caller supplies it.
    """
    if source_repo != ORIGINAL_MODEL_ID:
        if derived_from != ORIGINAL_MODEL_ID or not quantization:
            raise ValueError(f"{ORIGINAL_MODEL_ID} 이외의 저장소는 --quantization과 --derived-from {ORIGINAL_MODEL_ID}가 필요합니다.")
    target_root = model_dir()
    target_root.mkdir(parents=True, exist_ok=True)
    if local_path is not None:
        local = Path(local_path).expanduser().resolve()
        if not (local / "config.json").is_file():
            raise ValueError(f"config.json이 없는 폴더입니다: {local}")
        sha = revision
    else:
        from huggingface_hub import HfApi, snapshot_download

        sha = HfApi().model_info(source_repo, revision=revision).sha
        local = target_root / re.sub(r"[^A-Za-z0-9._-]", "_", source_repo) / str(sha)
        snapshot_download(repo_id=source_repo, revision=sha, local_dir=str(local))
    record = {
        "original_model_id": ORIGINAL_MODEL_ID, "source_repo": source_repo if local_path is None else (source_repo or None),
        "revision": sha, "quantization": quantization, "derived_from_claimed": derived_from,
        "derived_from": derived_from if source_repo != ORIGINAL_MODEL_ID else None,
        "local_path": str(local), "installed_at": utc_now(), "size_bytes": _dir_size(local),
        "registered_offline": local_path is not None,
    }
    write_json_atomic(target_root / MODEL_MANIFEST, record)
    return record
