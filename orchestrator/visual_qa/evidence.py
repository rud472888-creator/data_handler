"""Evidence images for suspect frames: original-resolution JPEG, preview, marked, crops."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

PREVIEW_SIDE = 1280
JPEG_QUALITY = 90


def _save(image, path: Path, **kwargs: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + f".{os.getpid()}.tmp")
    image.save(temporary, format="JPEG", quality=kwargs.get("quality", JPEG_QUALITY))
    temporary.replace(path)


def save_frame_evidence(image, qa_root: Path, clip_id: str, frame_index: int,
                        findings: list[dict[str, Any]]) -> dict[str, Any]:
    """Write evidence for one frame; paths are relative to the QA directory.

    The original file is the decoded frame at source resolution (not what the model
    saw). Marked/crop images only exist for findings whose location survived
    validation - nothing is drawn for missing locations.
    """
    from PIL import ImageDraw

    stem = f"{frame_index:07d}"
    folder = qa_root / "evidence" / clip_id
    rel = lambda name: (Path("evidence") / clip_id / name).as_posix()  # noqa: E731
    width, height = image.size
    _save(image, folder / f"{stem}.jpg")
    scale = min(1.0, PREVIEW_SIDE / max(width, height))
    preview = image.resize((max(1, round(width * scale)), max(1, round(height * scale)))) if scale < 1 else image.copy()
    _save(preview, folder / f"{stem}_preview.jpg", quality=85)
    result: dict[str, Any] = {"original": rel(f"{stem}.jpg"), "preview": rel(f"{stem}_preview.jpg"),
                              "marked": None, "crops": [], "source_size": [width, height],
                              "preview_size": list(preview.size)}
    located = [(i, f["location"]) for i, f in enumerate(findings) if (f.get("location") or {}).get("status") == "ok"]
    if not located:
        return result
    marked = preview.copy()
    draw = ImageDraw.Draw(marked)
    line = max(2, round(max(marked.size) / 400))
    for number, (index, location) in enumerate(located, 1):
        box = location.get("bbox_source_px")
        if box:
            x0, y0, x1, y1 = (v * scale for v in box)
            draw.rectangle([x0, y0, x1, y1], outline=(255, 64, 64), width=line)
            draw.text((x0 + line + 2, y0 + line + 2), str(number), fill=(255, 255, 0))
            pad_x, pad_y = (box[2] - box[0]) * 0.25, (box[3] - box[1]) * 0.25
            crop_box = (max(0, int(box[0] - pad_x)), max(0, int(box[1] - pad_y)),
                        min(width, int(box[2] + pad_x)), min(height, int(box[3] + pad_y)))
            if crop_box[2] - crop_box[0] >= 2 and crop_box[3] - crop_box[1] >= 2:
                crop = image.crop(crop_box)
                _save(crop, folder / f"{stem}_crop{number}.jpg")
                result["crops"].append({"finding_index": index, "number": number,
                                        "path": rel(f"{stem}_crop{number}.jpg"),
                                        "crop_box_source_px": list(crop_box)})
        point = location.get("point_source_px")
        if point:
            x, y = point[0] * scale, point[1] * scale
            radius = line * 4
            draw.ellipse([x - radius, y - radius, x + radius, y + radius], outline=(255, 64, 64), width=line)
            draw.text((x + radius + 2, y - radius), str(number), fill=(255, 255, 0))
    _save(marked, folder / f"{stem}_marked.jpg", quality=85)
    result["marked"] = rel(f"{stem}_marked.jpg")
    return result
