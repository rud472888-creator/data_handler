"""Sequential, read-only frame decoding (PyAV) and model-image preparation."""
from __future__ import annotations

import queue
import threading
import time
from dataclasses import dataclass, field
from fractions import Fraction
from pathlib import Path
from typing import Any, Callable, Iterator

VIDEO_EXTENSIONS = frozenset({".mp4", ".mov", ".m4v", ".mxf", ".avi", ".mkv", ".mts", ".m2ts",
                              ".webm", ".mpg", ".mpeg"})
# RAW formats need vendor SDKs; the existing adapters only capture representative stills.
RAW_EXTENSIONS = {
    ".braw": "Blackmagic RAW", ".r3d": "RED R3D", ".ari": "ARRIRAW", ".arx": "ARRIRAW",
    ".crm": "Canon Cinema RAW Light", ".cine": "Phantom Cine", ".nev": "Nikon N-RAW",
}


class DecodeError(RuntimeError):
    pass


@dataclass
class ClipInfo:
    width: int
    height: int
    codec: str | None
    pix_fmt: str | None
    time_base: str | None
    start_time: int | None
    declared_frames: int | None
    average_rate: str | None
    duration_s: float | None
    rotation_deg: int
    color_space: str | None
    color_range: str | None
    color_transfer: str | None
    source_timecode: str | None
    variable_frame_rate_possible: bool = True

    def to_payload(self) -> dict[str, Any]:
        return dict(self.__dict__)


@dataclass
class DecodedFrame:
    index: int
    pts: int | None
    time_base: str | None
    clip_time_s: float | None
    source_width: int
    source_height: int
    key_frame: bool | None
    _frame: Any = field(repr=False, default=None)
    _rotation: int = 0

    def image(self):
        """Full-resolution RGB PIL image. Only display rotation is applied."""
        from PIL import Image

        image = self._frame.to_image() if hasattr(self._frame, "to_image") else self._frame
        if image.mode != "RGB":
            image = image.convert("RGB")
        if self._rotation % 360:
            image = image.rotate(self._rotation % 360, expand=True, resample=Image.NEAREST)
        return image

    def release(self) -> None:
        self._frame = None


def classify_path(path: Path) -> tuple[str, str]:
    """('video'|'raw'|'ignored', label)."""
    suffix = path.suffix.lower()
    if suffix in RAW_EXTENSIONS:
        return "raw", RAW_EXTENSIONS[suffix]
    if suffix in VIDEO_EXTENSIONS:
        return "video", suffix.lstrip(".")
    return "ignored", suffix.lstrip(".")


class ClipReader:
    """Opens a clip read-only and yields decoded frames in decoder output order."""

    def __init__(self, path: Path):
        import av

        self.path = Path(path)
        self._av = av
        try:
            self._container = av.open(str(self.path), mode="r")
        except Exception as exc:  # av.error.* varies by ffmpeg version
            raise DecodeError(f"파일을 열지 못했습니다: {exc}") from exc
        streams = self._container.streams.video
        if not streams:
            self._container.close()
            raise DecodeError("영상 스트림이 없습니다.")
        self._stream = streams[0]
        self._stream.thread_type = "AUTO"
        self.info = self._probe()
        self.eof_reached = False
        self.decoded = 0

    def _probe(self) -> ClipInfo:
        stream, container = self._stream, self._container
        ctx = stream.codec_context
        rate = stream.average_rate
        duration = None
        if stream.duration is not None and stream.time_base is not None:
            duration = float(stream.duration * stream.time_base)
        elif container.duration:
            duration = container.duration / 1_000_000
        timecode = (stream.metadata.get("timecode") if stream.metadata else None) or \
                   (container.metadata.get("timecode") if container.metadata else None)
        return ClipInfo(
            width=int(ctx.width), height=int(ctx.height), codec=ctx.name, pix_fmt=ctx.pix_fmt,
            time_base=str(stream.time_base) if stream.time_base else None,
            start_time=stream.start_time,
            declared_frames=int(stream.frames) if stream.frames else None,
            average_rate=str(rate) if rate else None, duration_s=duration,
            rotation_deg=0, color_space=None, color_range=None, color_transfer=None,
            source_timecode=str(timecode) if timecode else None,
        )

    def frames(self, start: int = 0, end: int | None = None, limit: int | None = None) -> Iterator[DecodedFrame]:
        """Yield frames whose decoder-order index is within [start, end), at most ``limit``.

        Decoding stays sequential so ``index`` is exact; earlier frames are decoded
        and dropped. ``eof_reached`` is set only when the demuxer really ran out.
        """
        stream = self._stream
        origin: Fraction | None = None
        index = -1
        yielded = 0
        try:
            for frame in self._container.decode(stream):
                index += 1
                self.decoded = index + 1
                pts = frame.pts
                tb = frame.time_base or stream.time_base
                clip_time = None
                if pts is not None and tb is not None:
                    seconds = Fraction(pts) * Fraction(tb.numerator, tb.denominator)
                    if origin is None:
                        origin = Fraction(stream.start_time) * Fraction(stream.time_base.numerator, stream.time_base.denominator) \
                            if stream.start_time is not None and stream.time_base else seconds
                    clip_time = float(seconds - origin)
                if index == 0:
                    self.info.rotation_deg = int(getattr(frame, "rotation", 0) or 0) % 360
                    self.info.color_space = _name(frame.colorspace)
                    self.info.color_range = _name(frame.color_range)
                    self.info.color_transfer = _name(getattr(frame, "color_trc", None))
                if index < start:
                    continue
                if (end is not None and index >= end) or (limit is not None and yielded >= limit):
                    return
                yielded += 1
                yield DecodedFrame(
                    index=index, pts=pts, time_base=str(tb) if tb is not None else None,
                    clip_time_s=clip_time, source_width=frame.width, source_height=frame.height,
                    key_frame=bool(frame.key_frame) if hasattr(frame, "key_frame") else None,
                    _frame=frame, _rotation=self.info.rotation_deg)
            self.eof_reached = True
        except DecodeError:
            raise
        except GeneratorExit:
            raise
        except Exception as exc:
            raise DecodeError(f"프레임 {index + 1} 디코딩 중 오류: {exc}") from exc

    def close(self) -> None:
        try:
            self._container.close()
        except Exception:
            pass


def _name(value: Any) -> str | None:
    if value is None:
        return None
    return getattr(value, "name", str(value))


def prepare_model_image(image, max_side: int) -> tuple[Any, dict[str, Any]]:
    """Aspect-preserving downscale; never upscales; no crop, LUT or tone mapping."""
    from PIL import Image

    width, height = image.size
    scale = min(1.0, max_side / max(width, height))
    if scale < 1.0:
        size = (max(1, round(width * scale)), max(1, round(height * scale)))
        model_image = image.resize(size, Image.LANCZOS)
    else:
        model_image = image
        size = (width, height)
    return model_image, {
        "source_size": [width, height], "model_size": list(size), "scale": round(scale, 6),
        "resample": "LANCZOS" if scale < 1.0 else "none", "crop": None, "color_conversion": "decoder yuv->rgb only; no LUT",
        "max_side": max_side,
    }


_SENTINEL = object()


class BoundedProducer:
    """Runs a frame iterator in a thread behind a bounded queue (memory cap)."""

    def __init__(self, factory: Callable[[], Iterator[DecodedFrame]], size: int):
        self._queue: queue.Queue = queue.Queue(maxsize=max(1, size))
        self._stop = threading.Event()
        self.error: Exception | None = None
        self.decode_seconds = 0.0
        self._thread = threading.Thread(target=self._run, args=(factory,), daemon=True, name="visual-qa-decode")
        self._thread.start()

    def _run(self, factory: Callable[[], Iterator[DecodedFrame]]) -> None:
        iterator = None
        try:
            iterator = factory()
            while True:
                started = time.perf_counter()
                frame = next(iterator, _SENTINEL)
                self.decode_seconds += time.perf_counter() - started
                if frame is _SENTINEL:
                    break
                while not self._stop.is_set():
                    try:
                        self._queue.put(frame, timeout=0.2)
                        break
                    except queue.Full:
                        continue
                if self._stop.is_set():
                    break
        except Exception as exc:
            self.error = exc
        finally:
            if iterator is not None and hasattr(iterator, "close"):
                try:
                    iterator.close()
                except Exception:
                    pass
            while not self._stop.is_set():
                try:
                    self._queue.put(_SENTINEL, timeout=0.2)
                    break
                except queue.Full:
                    continue

    def __iter__(self) -> Iterator[DecodedFrame]:
        while True:
            item = self._queue.get()
            if item is _SENTINEL:
                return
            yield item

    def close(self) -> None:
        self._stop.set()
        while True:
            try:
                self._queue.get_nowait()
            except queue.Empty:
                break
        self._thread.join(timeout=5)
