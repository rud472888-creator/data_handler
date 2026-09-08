from __future__ import annotations

import json
import os
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Mapping

from orchestrator.paths import DATA_HELPER_ROOT

_CHECK_TIMEOUT_SECONDS = 10
_TOOL_SEARCH_DIRS = (Path("/opt/homebrew/bin"), Path("/usr/local/bin"))
_MXF_SCAN_LIMIT_BYTES = 16 * 1024 * 1024
_MXF_SCAN_CHUNK_BYTES = 64 * 1024
_RECOGNIZED_ARRIRAW_PICTURE_CODING_ULS = tuple(
    bytes.fromhex(value)
    for value in (
        "060e2b340401010d0401020102010101",
        "060e2b340401010d0401020102010102",
        "060e2b340401010d0401020102010103",
        "060e2b340401010d0401020102010201",
        "060e2b340401010d0401020102010202",
        "060e2b340401010d0f01020101010100",
        "060e2b340401010d0f01020101010200",
    )
)

_STANDARD_EXTENSIONS = frozenset(
    {
        ".avi",
        ".m4v",
        ".mkv",
        ".mov",
        ".mp4",
        ".mxf",
        ".mpeg",
        ".mpg",
        ".webm",
        ".wmv",
    }
)
_RAW_EXTENSION_FAMILIES = {
    ".braw": "braw",
    ".r3d": "r3d",
    ".ari": "arriraw",
    ".arx": "arriraw",
}
_FAMILY_ORDER = ("standard", "braw", "r3d", "arriraw")


@dataclass(frozen=True)
class DependencyCheck:
    family: str
    dependency: str
    state: str
    resolved_path: str | None
    message: str
    detail: Mapping[str, object] = field(default_factory=dict)

    @property
    def available(self) -> bool:
        return self.state == "available"

    def to_dict(self) -> dict[str, object]:
        return {
            "family": self.family,
            "dependency": self.dependency,
            "state": self.state,
            "resolved_path": self.resolved_path,
            "message": self.message,
            "detail": dict(self.detail),
        }


@dataclass(frozen=True)
class MediaPreflightReport:
    source_paths: tuple[str, ...]
    file_counts: Mapping[str, int]
    checks: tuple[DependencyCheck, ...]
    warnings: tuple[str, ...] = ()

    @property
    def detected_families(self) -> tuple[str, ...]:
        return tuple(
            family for family in _FAMILY_ORDER if self.file_counts.get(family, 0) > 0
        )

    @property
    def failures(self) -> tuple[DependencyCheck, ...]:
        return tuple(check for check in self.checks if not check.available)

    @property
    def ok(self) -> bool:
        return not self.failures

    def to_dict(self) -> dict[str, object]:
        return {
            "ok": self.ok,
            "source_paths": list(self.source_paths),
            "detected_families": list(self.detected_families),
            "file_counts": dict(self.file_counts),
            "checks": [check.to_dict() for check in self.checks],
            "warnings": list(self.warnings),
        }


class MediaDependencyPreflightError(RuntimeError):
    """Raised before copying when source media dependencies are unavailable."""

    def __init__(self, report: MediaPreflightReport) -> None:
        self.report = report
        failures = "; ".join(
            f"{check.family}: {check.message}" for check in report.failures
        )
        super().__init__(f"media dependency preflight failed: {failures}")


def validate_media_dependencies(
    source_paths: Iterable[str | Path] | str | Path,
    *,
    data_helper_root: str | Path = DATA_HELPER_ROOT,
    check_processing_dependencies: bool = True,
) -> MediaPreflightReport:
    """Validate only the dependencies needed by media found below source paths.

    A successful report is returned. If any required executable, vendor SDK,
    adapter backend, or source transport is unavailable,
    ``MediaDependencyPreflightError`` is raised with the complete report
    attached as ``error.report``. Copy-only runs may disable processing checks;
    source-transport checks still run so unsupported media is never omitted
    silently.

    An MXF file is classified as ARRIRAW only when its bounded header scan finds
    a recognized ARRIRAW picture coding UL. Other MXF files remain on the
    standard-video path with an ambiguity warning.
    """

    normalized_paths = _normalize_source_paths(source_paths)
    try:
        (
            counts,
            ambiguous_mxf_count,
            unreadable_mxf_paths,
            arriraw_sequence_count,
            zero_byte_arx_count,
            materialized_arx_count,
        ) = _detect_media_families(normalized_paths)
    except OSError as exc:
        raise _source_access_error(
            normalized_paths,
            f"Media source became unavailable while it was being scanned: {exc}",
        ) from exc
    helper_root = Path(data_helper_root).expanduser()

    checks: list[DependencyCheck] = []
    if check_processing_dependencies and counts["standard"]:
        checks.extend(_check_standard_dependencies())
    if check_processing_dependencies and counts["braw"]:
        checks.append(
            _check_json_adapter(
                family="braw",
                dependency="braw_adapter",
                executable=helper_root / "tools" / "braw_adapter",
                install_hint=(
                    "Install the Blackmagic RAW SDK/runtime and ensure the bundled "
                    "BRAW adapter and native helper are executable."
                ),
            )
        )
    if check_processing_dependencies and counts["r3d"]:
        checks.append(
            _check_json_adapter(
                family="r3d",
                dependency="r3d_adapter",
                executable=helper_root / "tools" / "r3d_adapter",
                install_hint=(
                    "Install the RED R3D SDK and set RED_R3D_SDK_LIBRARIES to the "
                    "directory containing REDR3D.dylib; also verify the bundled "
                    "r3d_native_helper."
                ),
            )
        )
    if zero_byte_arx_count:
        checks.append(
            DependencyCheck(
                family="arriraw",
                dependency="arx_source_transport",
                state="unsupported_source_transport",
                resolved_path=None,
                message=(
                    f"Detected {zero_byte_arx_count} zero-byte .arx file(s). Live "
                    "CODEX VFS .arx sources require an HDE-aware offload tool; "
                    "Data Handler does not support this source transport and will "
                    "not start a normal file copy."
                ),
                detail={"file_count": zero_byte_arx_count},
            )
        )
    if materialized_arx_count:
        checks.append(
            DependencyCheck(
                family="arriraw",
                dependency="arx_processing",
                state="unsupported_processing",
                resolved_path=None,
                message=(
                    f"Detected {materialized_arx_count} materialized .arx file(s), "
                    "but DataHelper does not support .arx processing. Offload or "
                    "convert the source to a supported ARRIRAW format before "
                    "starting this workflow."
                ),
                detail={"file_count": materialized_arx_count},
            )
        )
    art_input_count = counts["arriraw"] - zero_byte_arx_count - materialized_arx_count
    if check_processing_dependencies and art_input_count:
        checks.append(_check_arriraw_dependency(helper_root / "tools" / "art-cmd"))

    warnings: list[str] = []
    if ambiguous_mxf_count:
        warnings.append(
            f"Classified {ambiguous_mxf_count} .mxf file(s) as standard video. "
            "Their bounded header scan did not find a recognized ARRIRAW picture "
            "coding UL; extension alone cannot distinguish generic "
            "MXF from every ARRI variant."
        )
    if unreadable_mxf_paths:
        warnings.append(
            "Could not read MXF headers during preflight and retained the standard-"
            "video fallback for: " + ", ".join(unreadable_mxf_paths)
        )
    if arriraw_sequence_count:
        detail = (
            "Dependency preflight checks ARRI ART CMD availability; "
            if check_processing_dependencies
            else "A later DataHelper start must check ARRI ART CMD availability; "
        )
        warnings.append(
            f"Detected {arriraw_sequence_count} ARRIRAW .ari frame(s). {detail}"
            "downstream processing must preserve sequence grouping rather than "
            "treating every frame as a separate clip."
        )

    report = MediaPreflightReport(
        source_paths=tuple(str(path) for path in normalized_paths),
        file_counts=counts,
        checks=tuple(checks),
        warnings=tuple(warnings),
    )
    if not report.ok:
        raise MediaDependencyPreflightError(report)
    return report


def _normalize_source_paths(
    source_paths: Iterable[str | Path] | str | Path,
) -> tuple[Path, ...]:
    raw_paths: Iterable[str | Path]
    if isinstance(source_paths, (str, Path)):
        raw_paths = (source_paths,)
    else:
        raw_paths = source_paths

    paths = tuple(Path(path).expanduser() for path in raw_paths)
    if not paths:
        raise ValueError("at least one source path is required for media preflight")
    missing_paths = tuple(path for path in paths if not path.exists())
    if missing_paths:
        raise _source_access_error(
            paths,
            "Media source path is unavailable: "
            + ", ".join(str(path) for path in missing_paths),
        )
    invalid_paths = tuple(path for path in paths if not path.is_dir() and not path.is_file())
    if invalid_paths:
        raise _source_access_error(
            paths,
            "Media source path is not a file or directory: "
            + ", ".join(str(path) for path in invalid_paths),
        )
    return paths


def _source_access_error(paths: Iterable[Path], message: str) -> MediaDependencyPreflightError:
    normalized = tuple(paths)
    report = MediaPreflightReport(
        source_paths=tuple(str(path) for path in normalized),
        file_counts={family: 0 for family in _FAMILY_ORDER},
        checks=(
            DependencyCheck(
                family="source",
                dependency="source_path",
                state="source_unavailable",
                resolved_path=None,
                message=message,
                detail={"paths": [str(path) for path in normalized]},
            ),
        ),
    )
    return MediaDependencyPreflightError(report)


def _detect_media_families(
    source_paths: tuple[Path, ...],
) -> tuple[dict[str, int], int, tuple[str, ...], int, int, int]:
    counts = {family: 0 for family in _FAMILY_ORDER}
    ambiguous_mxf_count = 0
    unreadable_mxf_paths: list[str] = []
    arriraw_sequence_count = 0
    zero_byte_arx_count = 0
    materialized_arx_count = 0
    for source_path in source_paths:
        candidates = (source_path,) if source_path.is_file() else source_path.rglob("*")
        for candidate in candidates:
            if not candidate.is_file() or candidate.name.startswith("._"):
                continue
            extension = candidate.suffix.lower()
            if extension == ".mxf":
                is_arriraw, read_error = _mxf_contains_arriraw_ul(candidate)
                family = "arriraw" if is_arriraw else "standard"
                if not is_arriraw:
                    ambiguous_mxf_count += 1
                if read_error:
                    unreadable_mxf_paths.append(str(candidate))
            else:
                family = _RAW_EXTENSION_FAMILIES.get(extension)
            if family is None and extension in _STANDARD_EXTENSIONS:
                family = "standard"
            if family is None:
                continue
            counts[family] += 1
            if extension == ".ari":
                arriraw_sequence_count += 1
            elif extension == ".arx":
                if candidate.stat().st_size == 0:
                    zero_byte_arx_count += 1
                else:
                    materialized_arx_count += 1
    return (
        counts,
        ambiguous_mxf_count,
        tuple(unreadable_mxf_paths),
        arriraw_sequence_count,
        zero_byte_arx_count,
        materialized_arx_count,
    )


def _mxf_contains_arriraw_ul(path: Path) -> tuple[bool, str | None]:
    overlap = b""
    remaining = _MXF_SCAN_LIMIT_BYTES
    overlap_size = (
        max(len(value) for value in _RECOGNIZED_ARRIRAW_PICTURE_CODING_ULS) - 1
    )
    try:
        with path.open("rb") as stream:
            while remaining > 0:
                chunk = stream.read(min(_MXF_SCAN_CHUNK_BYTES, remaining))
                if not chunk:
                    break
                searchable = overlap + chunk
                if any(
                    value in searchable
                    for value in _RECOGNIZED_ARRIRAW_PICTURE_CODING_ULS
                ):
                    return True, None
                overlap = searchable[-overlap_size:]
                remaining -= len(chunk)
    except OSError as exc:
        return False, str(exc)
    return False, None


def _check_standard_dependencies() -> tuple[DependencyCheck, ...]:
    return tuple(_check_standard_tool(name) for name in ("ffmpeg", "ffprobe"))


def _check_standard_tool(name: str) -> DependencyCheck:
    executable = _resolve_standard_tool(name)
    if executable is None:
        return DependencyCheck(
            family="standard",
            dependency=name,
            state="configured_missing",
            resolved_path=None,
            message=(
                f"{name} was not found. Install FFmpeg and ensure {name} is on PATH "
                "or installed under /opt/homebrew/bin or /usr/local/bin."
            ),
        )

    try:
        completed = subprocess.run(
            [executable, "-version"],
            capture_output=True,
            text=True,
            check=False,
            timeout=_CHECK_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return DependencyCheck(
            family="standard",
            dependency=name,
            state="runtime_error",
            resolved_path=executable,
            message=f"{name} could not complete its version check: {exc}",
        )
    if completed.returncode != 0:
        output = _command_output(completed)
        return DependencyCheck(
            family="standard",
            dependency=name,
            state="runtime_error",
            resolved_path=executable,
            message=(
                f"{name} exists but its version check failed with exit code "
                f"{completed.returncode}: {output or 'no diagnostic output'}"
            ),
            detail={"exit_code": completed.returncode},
        )
    return DependencyCheck(
        family="standard",
        dependency=name,
        state="available",
        resolved_path=executable,
        message=f"{name} is available.",
    )


def _resolve_standard_tool(name: str) -> str | None:
    resolved = shutil.which(name)
    if resolved:
        return resolved
    for directory in _TOOL_SEARCH_DIRS:
        candidate = directory / name
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return str(candidate)
    return None


def _check_json_adapter(
    *,
    family: str,
    dependency: str,
    executable: Path,
    install_hint: str,
) -> DependencyCheck:
    missing = _missing_executable_check(family, dependency, executable, install_hint)
    if missing is not None:
        return missing

    request = json.dumps(
        {
            "request_id": "orchestrator-media-preflight",
            "command": "version",
            "input": {},
            "options": {},
        }
    )
    try:
        completed = subprocess.run(
            [str(executable)],
            input=request,
            capture_output=True,
            text=True,
            check=False,
            timeout=_CHECK_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return DependencyCheck(
            family=family,
            dependency=dependency,
            state="runtime_error",
            resolved_path=str(executable),
            message=f"{dependency} version check could not run: {exc}. {install_hint}",
        )

    try:
        response = json.loads(completed.stdout or "{}")
        if not isinstance(response, dict):
            raise ValueError("adapter response was not a JSON object")
    except (json.JSONDecodeError, ValueError) as exc:
        return DependencyCheck(
            family=family,
            dependency=dependency,
            state="runtime_error",
            resolved_path=str(executable),
            message=(
                f"{dependency} returned an invalid version response: {exc}. "
                f"{install_hint}"
            ),
            detail={
                "exit_code": completed.returncode,
                "stdout": (completed.stdout or "").strip(),
                "stderr": (completed.stderr or "").strip(),
            },
        )

    if completed.returncode != 0 or response.get("ok") is not True:
        adapter_message = _adapter_error_message(response)
        return DependencyCheck(
            family=family,
            dependency=dependency,
            state=str(response.get("status") or "runtime_error"),
            resolved_path=str(executable),
            message=(
                f"{adapter_message or f'{dependency} version check failed'}. "
                f"{install_hint}"
            ),
            detail={
                "exit_code": completed.returncode,
                "response": response,
                "stderr": (completed.stderr or "").strip(),
            },
        )

    return DependencyCheck(
        family=family,
        dependency=dependency,
        state="available",
        resolved_path=str(executable),
        message=f"{dependency} and its vendor runtime are available.",
        detail={
            "adapter_version": response.get("adapter_version"),
            "metadata_raw": response.get("metadata_raw", {}),
        },
    )


def _check_arriraw_dependency(executable: Path) -> DependencyCheck:
    install_hint = (
        "Install ARRI Reference Tool CMD, or set FRAMEPROOF_ARRI_ART_CMD to its "
        "art-cmd executable path."
    )
    missing = _missing_executable_check(
        "arriraw", "arri_art_cmd", executable, install_hint
    )
    if missing is not None:
        return missing

    try:
        completed = subprocess.run(
            [str(executable), "--help"],
            capture_output=True,
            text=True,
            check=False,
            timeout=_CHECK_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return DependencyCheck(
            family="arriraw",
            dependency="arri_art_cmd",
            state="runtime_error",
            resolved_path=str(executable),
            message=f"ARRI ART CMD availability check could not run: {exc}. {install_hint}",
        )
    if completed.returncode != 0:
        output = _command_output(completed)
        return DependencyCheck(
            family="arriraw",
            dependency="arri_art_cmd",
            state="runtime_error",
            resolved_path=str(executable),
            message=(
                "The bundled ARRI ART CMD launcher exists, but its backend failed "
                f"with exit code {completed.returncode}: "
                f"{output or 'no diagnostic output'}. {install_hint}"
            ),
            detail={"exit_code": completed.returncode},
        )
    return DependencyCheck(
        family="arriraw",
        dependency="arri_art_cmd",
        state="available",
        resolved_path=str(executable),
        message="ARRI ART CMD is available.",
    )


def _missing_executable_check(
    family: str,
    dependency: str,
    executable: Path,
    install_hint: str,
) -> DependencyCheck | None:
    if executable.is_file() and os.access(executable, os.X_OK):
        return None
    return DependencyCheck(
        family=family,
        dependency=dependency,
        state="configured_missing",
        resolved_path=None,
        message=(
            f"Required bundled executable is missing or not executable: {executable}. "
            f"{install_hint}"
        ),
        detail={"configured_path": str(executable)},
    )


def _adapter_error_message(response: Mapping[str, object]) -> str:
    errors = response.get("errors")
    if not isinstance(errors, list):
        return ""
    messages: list[str] = []
    for error in errors:
        if isinstance(error, dict) and error.get("message"):
            messages.append(str(error["message"]))
    return "; ".join(messages)


def _command_output(completed: subprocess.CompletedProcess[str]) -> str:
    return ((completed.stderr or "").strip() or (completed.stdout or "").strip())[:1000]
