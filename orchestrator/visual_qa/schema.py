"""Strict validation of model output and coordinate conversion. Stdlib only."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

CATEGORIES = (
    "equipment_intrusion",
    "obstruction_or_edge_debris",
    "compression_or_corruption",
    "black_or_flat_frame",
    "focus_or_blur",
    "exposure_or_color_anomaly",
    "pixel_anomaly",
    "other_visual_anomaly",
)
CATEGORY_LABELS = {
    "equipment_intrusion": "촬영 장비 침범 의심",
    "obstruction_or_edge_debris": "화면 가림·가장자리 이물질 의심",
    "compression_or_corruption": "블록 깨짐·줄무늬·화면 손상 의심",
    "black_or_flat_frame": "검은 화면·단색 화면 확인 필요",
    "focus_or_blur": "초점 이탈·심한 흐림 의심",
    "exposure_or_color_anomaly": "극단적 노출·색 이상 확인 필요",
    "pixel_anomaly": "밝은 점·검은 점·색점 의심",
    "other_visual_anomaly": "기타 시각적 이상",
}
PRIORITIES = ("low", "medium", "high")
PRIORITY_RANK = {name: rank for rank, name in enumerate(PRIORITIES)}
ASSESSMENTS = ("no_issue_observed", "suspect", "inconclusive")
COORD_MAX = 1000  # the model is asked for coordinates on a 0..1000 grid of the image it saw
MAX_TEXT = 600
MAX_FINDINGS = 8

# JSON Schema handed to backends that can constrain decoding (none does in v1;
# the same shape is described in the prompt and enforced by validate_frame_result).
JSON_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["frame_assessment", "findings"],
    "properties": {
        "frame_assessment": {"enum": list(ASSESSMENTS)},
        "findings": {"type": "array", "maxItems": MAX_FINDINGS, "items": {
            "type": "object",
            "required": ["category", "priority", "observation", "reason_for_review",
                         "uncertainty", "bbox", "point", "needs_temporal_confirmation",
                         "suggested_human_check"],
            "properties": {
                "category": {"enum": list(CATEGORIES)},
                "priority": {"enum": list(PRIORITIES)},
                "observation": {"type": "string"},
                "reason_for_review": {"type": "string"},
                "uncertainty": {"type": ["string", "null"]},
                "bbox": {"type": ["array", "null"], "items": {"type": "number"}, "minItems": 4, "maxItems": 4},
                "point": {"type": ["array", "null"], "items": {"type": "number"}, "minItems": 2, "maxItems": 2},
                "needs_temporal_confirmation": {"type": "boolean"},
                "suggested_human_check": {"type": "string"},
            },
        }},
    },
}


class OutputError(ValueError):
    """Model output could not be turned into a valid frame result."""

    def __init__(self, kind: str, message: str):
        super().__init__(message)
        self.kind = kind  # invalid_json | schema_invalid | truncated


@dataclass(frozen=True)
class ParsedOutput:
    result: dict[str, Any]
    warnings: tuple[str, ...]


_THINK = re.compile(r"<think>.*?</think>", re.DOTALL)
_FENCE = re.compile(r"^```(?:json)?\s*(.*?)\s*```$", re.DOTALL)


def parse_model_output(text: str, *, finish_reason: str | None, image_size: tuple[int, int],
                       source_size: tuple[int, int]) -> ParsedOutput:
    """Parse, validate and convert one frame answer. Never returns a default result."""
    if finish_reason == "length":
        raise OutputError("truncated", "출력이 최대 토큰 수에서 잘렸습니다.")
    if not isinstance(text, str) or not text.strip():
        raise OutputError("invalid_json", "모델 출력이 비어 있습니다.")
    warnings: list[str] = []
    body = text.strip()
    if "<think>" in body:
        stripped = _THINK.sub("", body).strip()
        if "<think>" in stripped:
            raise OutputError("truncated", "닫히지 않은 thinking 블록만 출력되었습니다.")
        body = stripped
        warnings.append("thinking_block_in_output")
    fenced = _FENCE.match(body)
    if fenced:
        body = fenced.group(1)
    try:
        payload = json.loads(body)
    except json.JSONDecodeError as exc:
        payload = _first_object(body)
        if payload is None:
            raise OutputError("invalid_json", f"JSON을 해석하지 못했습니다: {exc.msg}") from None
        warnings.append("json_extracted_from_surrounding_text")
    return ParsedOutput(validate_frame_result(payload, image_size=image_size, source_size=source_size, warnings=warnings),
                        tuple(warnings))


def _first_object(text: str) -> Any:
    start = text.find("{")
    while start != -1:
        depth = 0
        in_string = escaped = False
        for index in range(start, len(text)):
            char = text[index]
            if in_string:
                if escaped:
                    escaped = False
                elif char == "\\":
                    escaped = True
                elif char == '"':
                    in_string = False
            elif char == '"':
                in_string = True
            elif char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(text[start:index + 1])
                    except json.JSONDecodeError:
                        break
        start = text.find("{", start + 1)
    return None


def _bad(message: str) -> OutputError:
    return OutputError("schema_invalid", message)


def _text(value: Any, name: str, *, nullable: bool = False) -> str | None:
    if value is None and nullable:
        return None
    if not isinstance(value, str):
        raise _bad(f"{name}은 문자열이어야 합니다.")
    value = value.strip()
    if not nullable and not value:
        raise _bad(f"{name}이 비어 있습니다.")
    if nullable and not value:
        return None
    return value[:MAX_TEXT]


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value) if value == value and abs(value) != float("inf") else None


def validate_frame_result(payload: Any, *, image_size: tuple[int, int], source_size: tuple[int, int],
                          warnings: list[str] | None = None) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise _bad("최상위 값이 객체가 아닙니다.")
    assessment = payload.get("frame_assessment")
    if assessment not in ASSESSMENTS:
        raise _bad(f"frame_assessment 값이 올바르지 않습니다: {assessment!r}")
    raw_findings = payload.get("findings")
    if not isinstance(raw_findings, list):
        raise _bad("findings는 목록이어야 합니다.")
    if len(raw_findings) > MAX_FINDINGS:
        raise _bad(f"findings가 {MAX_FINDINGS}개를 넘습니다.")
    if assessment == "no_issue_observed" and raw_findings:
        raise _bad("no_issue_observed인데 findings가 있습니다.")
    if assessment == "suspect" and not raw_findings:
        raise _bad("suspect인데 findings가 없습니다.")
    findings = [_finding(item, image_size, source_size, warnings if warnings is not None else [])
                for item in raw_findings]
    return {"frame_assessment": assessment, "findings": findings}


def _finding(item: Any, image_size: tuple[int, int], source_size: tuple[int, int],
             warnings: list[str]) -> dict[str, Any]:
    if not isinstance(item, dict):
        raise _bad("finding이 객체가 아닙니다.")
    category, priority = item.get("category"), item.get("priority")
    if category not in CATEGORIES:
        raise _bad(f"알 수 없는 category: {category!r}")
    if priority not in PRIORITIES:
        raise _bad(f"알 수 없는 priority: {priority!r}")
    temporal = item.get("needs_temporal_confirmation")
    if not isinstance(temporal, bool):
        raise _bad("needs_temporal_confirmation은 true/false여야 합니다.")
    location = convert_location(item.get("bbox"), item.get("point"), image_size, source_size)
    if location["status"] == "invalid_discarded":
        warnings.append("invalid_location_discarded")
    return {
        "category": category,
        "priority": priority,
        "observation": _text(item.get("observation"), "observation"),
        "reason_for_review": _text(item.get("reason_for_review"), "reason_for_review"),
        "uncertainty": _text(item.get("uncertainty"), "uncertainty", nullable=True),
        "needs_temporal_confirmation": temporal,
        "suggested_human_check": _text(item.get("suggested_human_check"), "suggested_human_check"),
        "location": location,
    }


def convert_location(bbox: Any, point: Any, image_size: tuple[int, int],
                     source_size: tuple[int, int]) -> dict[str, Any]:
    """Map model 0..1000 grid coordinates to source pixels, or report no location.

    ``image_size`` is the image the model saw, ``source_size`` the decoded frame.
    Preprocessing keeps aspect ratio, so grid -> source is a plain scale, but the
    model-image pixel position is stored too so the transformation stays auditable.
    A missing or unusable location stays null: no synthetic boxes are created.
    """
    result: dict[str, Any] = {"status": "not_provided", "bbox_grid": None, "bbox_model_px": None,
                              "bbox_source_px": None, "point_source_px": None,
                              "note": "대략적 위치(모델 추정)"}
    if bbox is None and point is None:
        return result
    mw, mh = image_size
    sw, sh = source_size
    if bbox is not None:
        values = [_number(v) for v in bbox] if isinstance(bbox, (list, tuple)) and len(bbox) == 4 else None
        if (values is None or None in values or any(v < 0 or v > COORD_MAX for v in values)
                or values[0] >= values[2] or values[1] >= values[3]):
            return {**result, "status": "invalid_discarded"}
        if (values[2] - values[0]) * (values[3] - values[1]) / (COORD_MAX * COORD_MAX) > 0.95:
            # A whole-frame box says nothing about where the issue is.
            return {**result, "status": "not_localized"}
        x0, y0, x1, y1 = values
        result.update(
            status="ok", bbox_grid=[x0, y0, x1, y1],
            bbox_model_px=[round(x0 / COORD_MAX * mw, 1), round(y0 / COORD_MAX * mh, 1),
                           round(x1 / COORD_MAX * mw, 1), round(y1 / COORD_MAX * mh, 1)],
            bbox_source_px=[round(x0 / COORD_MAX * sw, 1), round(y0 / COORD_MAX * sh, 1),
                            round(x1 / COORD_MAX * sw, 1), round(y1 / COORD_MAX * sh, 1)])
        return result
    values = [_number(v) for v in point] if isinstance(point, (list, tuple)) and len(point) == 2 else None
    if values is None or None in values or any(v < 0 or v > COORD_MAX for v in values):
        return {**result, "status": "invalid_discarded"}
    result.update(status="ok", point_source_px=[round(values[0] / COORD_MAX * sw, 1),
                                                round(values[1] / COORD_MAX * sh, 1)])
    return result


def iou(a: list[float], b: list[float]) -> float:
    ix = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / union if union > 0 else 0.0
