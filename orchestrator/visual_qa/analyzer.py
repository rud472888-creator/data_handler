"""Per-frame analysis: one fresh single-image context, bounded retries, no fake passes."""
from __future__ import annotations

from typing import Any

from orchestrator.visual_qa.backend import BackendPoisoned, InferenceError, VisionBackend
from orchestrator.visual_qa.config import QaConfig
from orchestrator.visual_qa.prompt import SYSTEM_PROMPT, user_prompt
from orchestrator.visual_qa.schema import OutputError, parse_model_output

RETRYABLE = {"invalid_json", "schema_invalid", "truncated"}
RAW_KEEP = 3000


def analyze_frame(backend: VisionBackend, model_image: Any, *, source_size: tuple[int, int],
                  config: QaConfig) -> dict[str, Any]:
    """Return ``{"status": "analyzed", ...}`` or ``{"status": "failed", "error": ...}``.

    A failure is never converted to ``no_issue_observed``. ``BackendPoisoned`` is
    re-raised so the runner can stop using the backend.
    """
    image_size = model_image.size
    attempts: list[dict[str, Any]] = []
    for attempt in range(1, config.max_retries + 2):
        try:
            answer = backend.infer([model_image], SYSTEM_PROMPT, user_prompt(config.use_case),
                                   max_new_tokens=config.max_new_tokens, timeout_s=config.inference_timeout_s)
        except BackendPoisoned:
            raise
        except InferenceError as exc:
            attempts.append({"attempt": attempt, "error_kind": exc.kind, "error": str(exc)[:400]})
            if exc.kind == "out_of_memory" and attempt <= 1:
                continue  # one retry after the backend released memory
            return _failed(exc.kind, str(exc), attempts)
        raw = (answer.text or "")[:RAW_KEEP]
        try:
            parsed = parse_model_output(answer.text, finish_reason=answer.finish_reason,
                                        image_size=image_size, source_size=source_size)
        except OutputError as exc:
            attempts.append({"attempt": attempt, "error_kind": exc.kind, "error": str(exc)[:400],
                             "raw_output": raw, "finish_reason": answer.finish_reason})
            if exc.kind in RETRYABLE and attempt <= config.max_retries:
                continue
            return _failed(exc.kind, str(exc), attempts)
        attempts.append({"attempt": attempt, "ok": True})
        return {
            "status": "analyzed", "frame_assessment": parsed.result["frame_assessment"],
            "findings": parsed.result["findings"], "warnings": list(parsed.warnings),
            "raw_output": raw, "finish_reason": answer.finish_reason,
            "attempts": attempts,
            "inference": {"elapsed_s": round(answer.elapsed_s, 3), "prompt_tokens": answer.prompt_tokens,
                          "generation_tokens": answer.generation_tokens,
                          "peak_memory_bytes": answer.peak_memory_bytes},
        }
    return _failed("backend_error", "재시도 한도를 넘었습니다.", attempts)  # pragma: no cover


def _failed(kind: str, message: str, attempts: list[dict[str, Any]]) -> dict[str, Any]:
    return {"status": "failed", "error": {"kind": kind, "message": message[:600]}, "attempts": attempts}
