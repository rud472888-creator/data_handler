"""QA run configuration. Only analysis-affecting fields enter the fingerprint."""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, fields
from typing import Any

ORIGINAL_MODEL_ID = "Qwen/Qwen3.5-4B"
PROMPT_VERSION = "vqa-prompt-v1"
SCHEMA_VERSION = "vqa-frame-v1"
MODE_FULL = "full_frames"
MODE_LIMITED = "limited_frames"
USE_CASES = ("camera_original", "delivery")


@dataclass(frozen=True)
class QaConfig:
    use_case: str = "camera_original"
    # Development limits. Any of these makes the run "limited", never "full".
    start_frame: int = 0
    end_frame: int | None = None  # exclusive
    max_frames_per_clip: int | None = None
    max_clips: int | None = None
    # Preprocessing / inference.
    model_max_side: int = 1024
    max_new_tokens: int = 700
    prompt_version: str = PROMPT_VERSION
    # Operational settings (not part of the analysis fingerprint).
    max_retries: int = 2
    inference_timeout_s: float = 300.0
    queue_size: int = 4
    max_evidence_frames_per_clip: int = 60
    group_min_iou: float = 0.2

    def __post_init__(self) -> None:
        if self.use_case not in USE_CASES:
            raise ValueError(f"unsupported use_case: {self.use_case}")
        if self.start_frame < 0 or (self.end_frame is not None and self.end_frame <= self.start_frame):
            raise ValueError("invalid frame range")
        for name in ("max_frames_per_clip", "max_clips"):
            value = getattr(self, name)
            if value is not None and value < 1:
                raise ValueError(f"{name} must be positive")
        if not 64 <= self.model_max_side <= 4096:
            raise ValueError("model_max_side must be within 64..4096")

    @property
    def is_limited(self) -> bool:
        return bool(self.start_frame or self.end_frame is not None
                    or self.max_frames_per_clip is not None or self.max_clips is not None)

    @property
    def mode(self) -> str:
        return MODE_LIMITED if self.is_limited else MODE_FULL

    def limits_text(self) -> str:
        parts = []
        if self.start_frame:
            parts.append(f"시작 프레임 {self.start_frame}")
        if self.end_frame is not None:
            parts.append(f"종료 프레임 {self.end_frame} 미만")
        if self.max_frames_per_clip is not None:
            parts.append(f"클립당 최대 {self.max_frames_per_clip}프레임")
        if self.max_clips is not None:
            parts.append(f"최대 {self.max_clips}개 클립")
        return ", ".join(parts)

    def analysis_payload(self) -> dict[str, Any]:
        return {
            "mode": self.mode, "use_case": self.use_case, "start_frame": self.start_frame,
            "end_frame": self.end_frame, "max_frames_per_clip": self.max_frames_per_clip,
            "max_clips": self.max_clips, "model_max_side": self.model_max_side,
            "max_new_tokens": self.max_new_tokens, "prompt_version": self.prompt_version,
            "schema_version": SCHEMA_VERSION,
        }

    def fingerprint(self) -> str:
        return digest(self.analysis_payload())

    def to_payload(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> "QaConfig":
        known = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in payload.items() if k in known})


def digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
