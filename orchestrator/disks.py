from __future__ import annotations

import plistlib
import shutil
import subprocess
from pathlib import Path
from typing import Any, Callable

MOUNT_ROOT = Path("/Volumes")
DISKUTIL = Path("/usr/sbin/diskutil")


class DiskUnmountError(ValueError):
    pass


def list_mounted_disks(
    mount_root: Path = MOUNT_ROOT,
    *,
    disk_classifier: Callable[[Path], str] | None = None,
) -> list[dict[str, Any]]:
    if not mount_root.exists():
        return []
    classify = disk_classifier or classify_disk
    disks: list[dict[str, Any]] = []
    for path in sorted(mount_root.iterdir(), key=lambda item: item.name.lower()):
        if not path.is_dir() or path.name.startswith("."):
            continue
        disk_type = classify(path)
        try:
            usage = shutil.disk_usage(path)
        except OSError:
            continue
        total = int(usage.total)
        used = int(usage.used)
        free = int(usage.free)
        disks.append(
            {
                "name": path.name,
                "path": str(path),
                "total_bytes": total,
                "used_bytes": used,
                "free_bytes": free,
                "used_percent": round((used / total) * 100) if total > 0 else 0,
                "disk_type": disk_type,
            }
        )
    external = [disk for disk in disks if disk["disk_type"] == "external"]
    internal = [disk for disk in disks if disk["disk_type"] != "external"]
    return (external + internal[: max(0, 3 - len(external))])[:3]


def classify_disk(path: Path) -> str:
    try:
        result = subprocess.run(
            [str(DISKUTIL), "info", "-plist", str(path)],
            check=True,
            capture_output=True,
            timeout=2,
        )
        payload = plistlib.loads(result.stdout)
    except (OSError, plistlib.InvalidFileException, subprocess.SubprocessError):
        return "internal"
    if payload.get("Internal") is False:
        return "external"
    if payload.get("RemovableMediaOrExternalDevice") is True or payload.get("Ejectable") is True:
        return "external"
    return "internal"


def unmount_disk(
    path: str | Path,
    mount_root: Path = MOUNT_ROOT,
    *,
    disk_classifier: Callable[[Path], str] | None = None,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> dict[str, str]:
    mount_root = mount_root.expanduser().resolve()
    target = Path(path).expanduser().resolve()
    if target.parent != mount_root or target.name.startswith("."):
        raise DiskUnmountError(f"disk must be a mounted volume under {mount_root}")
    if not target.exists() or not target.is_dir():
        raise DiskUnmountError(f"disk is not mounted: {target}")
    classify = disk_classifier or classify_disk
    if classify(target) != "external":
        raise DiskUnmountError("only external disks can be unmounted from the app")
    try:
        runner(
            [str(DISKUTIL), "eject", str(target)],
            check=True,
            capture_output=True,
            text=True,
            timeout=15,
        )
    except subprocess.CalledProcessError as exc:
        message = (exc.stderr or exc.stdout or "").strip()
        raise DiskUnmountError(f"failed to eject disk: {message or exc}") from exc
    except (OSError, subprocess.SubprocessError) as exc:
        raise DiskUnmountError(f"failed to eject disk: {exc}") from exc
    return {"path": str(target), "status": "ejected"}
