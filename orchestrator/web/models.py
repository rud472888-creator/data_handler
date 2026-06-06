from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class ConsoleProject:
    id: str
    name: str
    replica_roots: tuple[Path, ...]
    replica_project_roots: tuple[Path, ...]
    preset_name: str
    created_at: str
    updated_at: str
    source_paths: tuple[Path, ...] = ()

    def to_payload(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["replica_roots"] = [str(path) for path in self.replica_roots]
        payload["replica_project_roots"] = [str(path) for path in self.replica_project_roots]
        payload["source_paths"] = [str(path) for path in self.source_paths]
        return payload


@dataclass(frozen=True)
class ConsoleRunRecord:
    project_id: str
    shoot_date: str
    camera_unit: str
    roll: str
    run_id: str
    source_path: str
    created_at: str
    source_paths: tuple[str, ...] = ()

    def to_payload(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["source_paths"] = list(self.source_paths or (self.source_path,))
        return payload
