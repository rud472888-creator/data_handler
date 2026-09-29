"""Vision backends. Only the MLX-VLM backend talks to a real model.

``MockBackend`` exists for tests and is stamped as mock everywhere it is reported.
"""
from __future__ import annotations

import gc
import platform
import re
import threading
import time
from dataclasses import dataclass
from importlib import metadata
from pathlib import Path
from typing import Any, Callable, Protocol

from orchestrator.visual_qa.config import ORIGINAL_MODEL_ID
from orchestrator.visual_qa.settings import read_model_manifest


class BackendUnavailable(RuntimeError):
    """The run cannot start (model missing, unsupported runtime). Maps to ``blocked``."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


class InferenceError(RuntimeError):
    def __init__(self, kind: str, message: str):
        super().__init__(message)
        self.kind = kind  # timeout | out_of_memory | backend_error


class BackendPoisoned(InferenceError):
    """An inference call is still running somewhere; the backend must not be reused."""


@dataclass
class InferenceResult:
    text: str
    finish_reason: str | None = None
    prompt_tokens: int | None = None
    generation_tokens: int | None = None
    peak_memory_bytes: int | None = None
    elapsed_s: float = 0.0
    rendered_prompt_check: dict[str, Any] | None = None


class VisionBackend(Protocol):
    name: str
    is_mock: bool

    def check_ready(self) -> None: ...
    def describe(self) -> dict[str, Any]: ...
    def infer(self, images: list[Any], system: str, user: str, *, max_new_tokens: int,
              timeout_s: float | None) -> InferenceResult: ...
    def close(self) -> None: ...


def _version(package: str) -> str | None:
    try:
        return metadata.version(package)
    except metadata.PackageNotFoundError:
        return None


class MockBackend:
    """Scripted responder. Never a substitute for the real model."""

    name = "mock"
    is_mock = True

    def __init__(self, responder: Callable[[list[Any], str, str], str | InferenceResult]):
        self._responder = responder
        self.calls = 0
        self.closed = False
        self.ready_error: BackendUnavailable | None = None

    def check_ready(self) -> None:
        if self.ready_error:
            raise self.ready_error

    def describe(self) -> dict[str, Any]:
        return {"backend": self.name, "is_mock": True, "original_model_id": ORIGINAL_MODEL_ID,
                "loaded_model": "mock", "revision": None, "quantization": None,
                "runtime": {"python": platform.python_version()}, "thinking_disabled": None,
                "notice": "MOCK BACKEND: 실제 Qwen3.5-4B 추론이 아닙니다."}

    def infer(self, images, system, user, *, max_new_tokens, timeout_s):
        self.calls += 1
        started = time.monotonic()
        answer = self._responder(images, system, user)
        if isinstance(answer, InferenceResult):
            return answer
        return InferenceResult(text=answer, finish_reason="stop", elapsed_s=time.monotonic() - started)

    def close(self) -> None:
        self.closed = True


class MlxVlmBackend:
    """Local Qwen3.5-4B through MLX-VLM (Apple Silicon). Model loaded once per worker.

    The model is loaded from the directory recorded by ``visual-qa install-model``;
    weights are never downloaded or converted at run time.
    """

    name = "mlx_vlm"
    is_mock = False

    def __init__(self, model_directory: Path | None = None):
        self._directory = model_directory
        self._install: dict[str, Any] | None = None
        self._model = self._processor = self._config = None
        self._poisoned = False
        self._thinking_check: dict[str, Any] | None = None

    def check_ready(self) -> None:
        if platform.system() != "Darwin" or platform.machine() != "arm64":
            raise BackendUnavailable(
                "unsupported_platform",
                f"MLX-VLM은 Apple Silicon macOS에서만 실행됩니다 ({platform.system()} {platform.machine()}).")
        install = read_model_manifest(self._directory)
        if not install or not install.get("local_path"):
            raise BackendUnavailable("model_not_installed",
                                     "Qwen3.5-4B 모델이 설치되어 있지 않습니다. `python -m orchestrator.cli visual-qa install-model`을 먼저 실행하세요.")
        if not Path(install["local_path"]).is_dir():
            raise BackendUnavailable("model_missing", f"설치 기록의 모델 경로가 없습니다: {install['local_path']}")
        if install.get("original_model_id") != ORIGINAL_MODEL_ID:
            raise BackendUnavailable("model_mismatch", f"설치된 모델의 원본 ID가 {ORIGINAL_MODEL_ID}가 아닙니다.")
        try:
            import mlx_vlm  # noqa: F401
        except ImportError as exc:
            raise BackendUnavailable("runtime_missing", f"mlx-vlm을 불러오지 못했습니다: {exc}") from exc
        self._install = install

    def _load(self) -> None:
        if self._model is not None:
            return
        import os

        # Offline by construction: a missing file must fail, not download.
        os.environ["HF_HUB_OFFLINE"] = "1"
        from mlx_vlm import load
        from mlx_vlm.utils import load_config

        path = self._install["local_path"]
        try:
            self._model, self._processor = load(path)
            self._config = load_config(path)
        except MemoryError as exc:
            raise BackendUnavailable("out_of_memory", f"모델을 메모리에 올리지 못했습니다: {exc}") from exc
        except Exception as exc:
            raise BackendUnavailable("model_load_failed", f"모델을 불러오지 못했습니다: {type(exc).__name__}: {exc}") from exc

    def describe(self) -> dict[str, Any]:
        install = self._install or {}
        return {
            "backend": self.name, "is_mock": False, "original_model_id": ORIGINAL_MODEL_ID,
            "loaded_model": install.get("source_repo") or install.get("local_path"),
            "loaded_model_path": install.get("local_path"), "revision": install.get("revision"),
            "quantization": install.get("quantization"), "derived_from": install.get("derived_from"),
            "runtime": {"python": platform.python_version(), "platform": platform.platform(),
                        "mlx": _version("mlx"), "mlx-vlm": _version("mlx-vlm"),
                        "transformers": _version("transformers"), "pillow": _version("pillow")},
            "thinking_disabled": "chat template enable_thinking=False + generate(enable_thinking=False)",
            "thinking_check": self._thinking_check,
            "structured_output": "prompt JSON guide + strict validation (no constrained decoding)",
        }

    def infer(self, images, system, user, *, max_new_tokens, timeout_s):
        if self._poisoned:
            raise BackendPoisoned("backend_error", "이전 추론이 종료되지 않아 백엔드를 다시 사용할 수 없습니다.")
        self._load()
        box: dict[str, Any] = {}

        def call() -> None:
            try:
                box["result"] = self._generate(images, system, user, max_new_tokens)
            except BaseException as exc:  # noqa: BLE001 - relayed to the caller
                box["error"] = exc

        worker = threading.Thread(target=call, daemon=True, name="visual-qa-infer")
        started = time.monotonic()
        worker.start()
        worker.join(timeout_s)
        if worker.is_alive():
            # MLX calls cannot be cancelled; stop using this backend for the run.
            self._poisoned = True
            raise BackendPoisoned("timeout", f"추론이 {timeout_s:.0f}초 안에 끝나지 않았습니다.")
        if "error" in box:
            error = box["error"]
            text = f"{type(error).__name__}: {error}"
            if isinstance(error, MemoryError) or re.search(r"out of memory|OOM|kIOGPU", text, re.I):
                gc.collect()
                raise InferenceError("out_of_memory", text)
            raise InferenceError("backend_error", text)
        result: InferenceResult = box["result"]
        result.elapsed_s = time.monotonic() - started
        return result

    def _generate(self, images, system, user, max_new_tokens) -> InferenceResult:
        from mlx_vlm import apply_chat_template, generate

        # Fresh, single-turn context for every call; nothing is carried over.
        prompt = apply_chat_template(
            self._processor, self._config,
            [{"role": "system", "content": system}, {"role": "user", "content": user}],
            num_images=len(images), enable_thinking=False)
        if self._thinking_check is None:
            tail = prompt[-80:] if isinstance(prompt, str) else ""
            self._thinking_check = {
                "prompt_tail": tail,
                "empty_think_block_present": bool(re.search(r"<think>\s*</think>\s*$", tail)) if isinstance(prompt, str) else None,
            }
        output = generate(self._model, self._processor, prompt, image=list(images),
                          max_tokens=max_new_tokens, temperature=0.0, verbose=False,
                          enable_thinking=False)
        text = getattr(output, "text", output)
        peak = getattr(output, "peak_memory", None)
        return InferenceResult(
            text=text if isinstance(text, str) else str(text),
            finish_reason=getattr(output, "finish_reason", None),
            prompt_tokens=getattr(output, "prompt_tokens", None),
            generation_tokens=getattr(output, "generation_tokens", None),
            # mlx-vlm reports peak memory in GB.
            peak_memory_bytes=int(peak * 1e9) if isinstance(peak, (int, float)) and peak else None,
            rendered_prompt_check=self._thinking_check)

    def close(self) -> None:
        self._model = self._processor = None
        gc.collect()


def make_backend(name: str) -> VisionBackend:
    if name == "mlx_vlm":
        return MlxVlmBackend()
    raise BackendUnavailable("unknown_backend", f"지원하지 않는 백엔드입니다: {name}")
