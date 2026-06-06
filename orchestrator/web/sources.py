from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any


def list_source_candidates(roots: tuple[Path, ...] = (Path("/Volumes"),)) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for root in roots:
        if not root.exists() or not root.is_dir():
            continue
        for child in sorted(root.iterdir(), key=lambda path: path.name.lower()):
            if not child.is_dir():
                continue
            if _is_ignored_volume(child):
                continue
            usage = shutil.disk_usage(child)
            candidates.append(
                {
                    "id": str(child),
                    "name": child.name,
                    "path": str(child),
                    "available": True,
                    "total_bytes": usage.total,
                    "free_bytes": usage.free,
                }
            )
    return candidates


def _is_ignored_volume(path: Path) -> bool:
    name = path.name
    return name.startswith(".") or name in {"Macintosh HD"}
