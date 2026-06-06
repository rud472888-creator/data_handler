from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from orchestrator.paths import DEFAULT_HERMES_PROFILE


class SpecError(ValueError):
    """Raised when an approved pipeline request is unsafe or incomplete."""


@dataclass(frozen=True)
class RunSpec:
    run_id: str
    project_name: str
    source_path: Path
    replica_roots: tuple[Path, ...]
    hermes_profile: str = DEFAULT_HERMES_PROFILE
    footage_run_name: str | None = None
    extra_source_paths: tuple[Path, ...] = ()

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> "RunSpec":
        source_paths = tuple(
            Path(str(path)).expanduser() for path in payload.get("source_paths", [])
        )
        if not source_paths:
            source_paths = (Path(str(payload["source_path"])).expanduser(),)
        return cls(
            run_id=str(payload["run_id"]),
            project_name=str(payload["project_name"]),
            source_path=source_paths[0],
            replica_roots=tuple(
                Path(str(path)).expanduser() for path in payload["replica_roots"]
            ),
            hermes_profile=str(payload.get("hermes_profile") or DEFAULT_HERMES_PROFILE),
            footage_run_name=(
                str(payload["footage_run_name"]) if payload.get("footage_run_name") else None
            ),
            extra_source_paths=source_paths[1:],
        )

    @property
    def source_paths(self) -> tuple[Path, ...]:
        return (self.source_path, *self.extra_source_paths)

    def to_payload(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "project_name": self.project_name,
            "source_path": str(self.source_path.resolve()),
            "source_paths": [str(path.resolve()) for path in self.source_paths],
            "replica_roots": [str(path.resolve()) for path in self.replica_roots],
            "hermes_profile": self.hermes_profile,
            "footage_run_name": self.footage_run_name,
        }

    def validate(self) -> None:
        if not self.run_id.strip():
            raise SpecError("run_id is required")
        _validate_project_name(self.project_name)
        sources = tuple(path.resolve() for path in self.source_paths)
        replicas = tuple(path.resolve() for path in self.replica_roots)
        if not sources:
            raise SpecError("at least one source path is required")
        if len(set(sources)) != len(sources):
            raise SpecError("source paths must be unique")
        for source in sources:
            if not source.exists() or not source.is_dir():
                raise SpecError(f"source_path must be an existing directory: {source}")
        if not replicas:
            raise SpecError("at least one replica root is required")
        if len(set(replicas)) != len(replicas):
            raise SpecError("replica roots must be unique")
        for replica in replicas:
            if not replica.exists() or not replica.is_dir():
                raise SpecError(f"replica root must be an existing directory: {replica}")
        if set(sources) & set(replicas):
            raise SpecError("source_path must be different from replica roots")
        if self.footage_run_name is not None:
            _validate_relative_run_path(self.footage_run_name)


def _validate_project_name(project_name: str) -> None:
    value = project_name.strip()
    if not value:
        raise SpecError("project_name is required")
    if value in {".", ".."}:
        raise SpecError("project_name cannot be . or ..")
    if "/" in value or "\\" in value or "\x00" in value:
        raise SpecError("project_name cannot contain path separators")


def _validate_relative_run_path(value: str) -> None:
    path = Path(value)
    if not value.strip():
        raise SpecError("footage_run_name cannot be empty")
    if path.is_absolute():
        raise SpecError("footage_run_name must be relative")
    if "\\" in value or "\x00" in value:
        raise SpecError("footage_run_name cannot contain backslashes or null bytes")
    if any(part in {"", ".", ".."} for part in path.parts):
        raise SpecError("footage_run_name cannot contain empty, . or .. segments")
