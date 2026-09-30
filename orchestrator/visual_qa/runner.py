"""Executes one QA run: decode -> analyze -> journal -> events -> report. Resumable."""
from __future__ import annotations

import os
import threading
import time
from pathlib import Path
from typing import Any, Callable

from orchestrator.visual_qa import store
from orchestrator.visual_qa.analyzer import analyze_frame
from orchestrator.visual_qa.backend import BackendPoisoned, BackendUnavailable, VisionBackend
from orchestrator.visual_qa.config import QaConfig, digest
from orchestrator.visual_qa.decode import BoundedProducer, ClipReader, DecodeError, prepare_model_image
from orchestrator.visual_qa.events import GROUPING_VERSION, group_events
from orchestrator.visual_qa.store import QaDir, JsonlWriter, read_jsonl, utc_now

ReaderFactory = Callable[[Path], Any]
STATE_INTERVAL_S = 1.0


def model_fingerprint(description: dict[str, Any]) -> str:
    keys = ("backend", "is_mock", "original_model_id", "loaded_model", "loaded_model_path",
            "revision", "quantization", "weights_identity")
    return digest({k: description.get(k) for k in keys})


class Run:
    """Mutable execution context for one QA directory."""

    def __init__(self, qa: QaDir, backend: VisionBackend, *, reader_factory: ReaderFactory = ClipReader,
                 stop: threading.Event | None = None):
        self.qa, self.backend, self.reader_factory = qa, backend, reader_factory
        self.stop = stop or threading.Event()
        self.manifest = store.read_json_safe(qa.manifest)
        self.config = QaConfig.from_payload(self.manifest["config"])
        self.frames = JsonlWriter(qa.frames)
        self.clip_log = JsonlWriter(qa.clips)
        self.errors = JsonlWriter(qa.errors)
        self.counts = {"clips_total": len(self.manifest["clips"]), "clips_done": 0, "frames_decoded": 0,
                       "frames_analyzed": 0, "frames_failed": 0, "frames_reused": 0}
        self.decode_s = 0.0
        self.prepare_s = 0.0  # RGB conversion + resize, measured apart from demux/decode
        self.infer_s = 0.0
        self.peak_memory = 0
        self.evidence_counts: dict[str, int] = {}
        self.analysis_fp = ""
        self.poisoned: str | None = None
        self._last_state = 0.0
        self.prior = self._load_prior()
        for clip_id, by_index in self.prior.items():
            self.evidence_counts[clip_id] = sum(1 for r in by_index.values() if (r.get("evidence") or {}).get("original"))

    def _load_prior(self) -> dict[str, dict[int, dict[str, Any]]]:
        records, _bad = read_jsonl(self.qa.frames)
        latest: dict[str, dict[int, dict[str, Any]]] = {}
        for record in records:
            if record.get("type") == "frame":
                latest.setdefault(record["clip_id"], {})[record["frame_index"]] = record
        return latest

    def error(self, kind: str, message: str, **extra: Any) -> None:
        self.errors.append({"at": utc_now(), "kind": kind, "message": message[:800], **extra})

    def publish(self, *, force: bool = False, **fields: Any) -> None:
        now = time.monotonic()
        if not force and now - self._last_state < STATE_INTERVAL_S:
            return
        self._last_state = now
        self.qa.write_state(counts=dict(self.counts), heartbeat_at=utc_now(), pid=os.getpid(), **fields)

    def close(self) -> None:
        for writer in (self.frames, self.clip_log, self.errors):
            writer.close()


def run_qa(qa_dir: Path, backend: VisionBackend, *, reader_factory: ReaderFactory = ClipReader,
           stop: threading.Event | None = None) -> dict[str, Any]:
    """Run (or resume) the QA in ``qa_dir``. Returns the final state."""
    qa = QaDir(qa_dir)
    manifest = store.read_json_safe(qa.manifest)
    if not manifest:
        raise ValueError(f"manifest.json missing or unreadable in {qa_dir}")
    session = {"started_at": utc_now(), "pid": os.getpid()}
    started = time.monotonic()
    try:
        backend.check_ready()
        description = backend.describe()
    except BackendUnavailable as exc:
        qa.write_state(status=store.BLOCKED, reason=exc.code, message=str(exc), heartbeat_at=utc_now())
        _write_outputs_best_effort(qa, manifest, None)
        return qa.read_state()
    fingerprint = model_fingerprint(description)
    known = manifest.get("model_fingerprint")
    if known and known != fingerprint:
        qa.write_state(status=store.BLOCKED, reason="model_changed",
                       message="이 검사는 다른 모델·리비전으로 시작되었습니다. 결과를 섞지 않도록 새 리비전으로 다시 검사하세요.")
        return qa.read_state()
    manifest["model"], manifest["model_fingerprint"] = description, fingerprint
    store.write_json_atomic(qa.manifest, manifest)

    run = Run(qa, backend, reader_factory=reader_factory, stop=stop)
    run.analysis_fp = digest([run.config.fingerprint(), fingerprint])
    run.publish(force=True, status=store.RUNNING, reason=None, message="검사 중", phase="inspecting")
    try:
        _run_clips(run)
    finally:
        run.close()
    # The backend learns its rendered-prompt metadata on the first inference.
    # Persist that observation for the report without changing model identity.
    manifest["model"] = backend.describe()
    store.write_json_atomic(qa.manifest, manifest)
    session.update(ended_at=utc_now(), wall_s=round(time.monotonic() - started, 2))
    return _finalize(qa, manifest, run, session)


# ---------------------------------------------------------------- clips

def _run_clips(run: Run) -> None:
    clips = run.manifest["clips"]
    if run.config.max_clips is not None:
        inspected = [c for c in clips if c["kind"] == "video"][:run.config.max_clips]
        selected_ids = {c["clip_id"] for c in inspected}
    else:
        selected_ids = None
    for clip in clips:
        if _cancel_requested(run):
            return
        if run.poisoned:
            _clip_record(run, clip, "not_run", reason="backend_stopped", message=run.poisoned)
            continue
        if clip["kind"] == "raw":
            _clip_record(run, clip, "unsupported", reason="raw_format", message=clip.get("unsupported_reason"))
            run.error("clip_unsupported", clip.get("unsupported_reason") or "RAW", clip_id=clip["clip_id"])
            run.counts["clips_done"] += 1
            continue
        if selected_ids is not None and clip["clip_id"] not in selected_ids:
            _clip_record(run, clip, "not_run", reason="max_clips_limit", message="max_clips 개발 제한으로 검사하지 않았습니다.")
            run.counts["clips_done"] += 1
            continue
        _process_clip(run, clip)
        if _cancel_requested(run):
            return
        run.counts["clips_done"] += 1
        run.publish(force=True, status=store.RUNNING, phase="inspecting")


def _clip_record(run: Run, clip: dict[str, Any], status: str, **fields: Any) -> None:
    run.clip_log.append({"type": "clip", "clip_id": clip["clip_id"], "display_name": clip["display_name"],
                         "status": status, "at": utc_now(), **fields})


def _cancel_requested(run: Run) -> bool:
    if run.stop.is_set() or (run.qa.path / "cancel.requested").exists():
        run.stop.set()
        return True
    return False


def _viable_candidates(clip: dict[str, Any]) -> list[dict[str, Any]]:
    return list(clip.get("candidates", []))


def _check_candidate(candidate: dict[str, Any]) -> str | None:
    """Return a reason the verified replica can't be used, else None."""
    path = Path(candidate["path"])
    try:
        stat = path.stat()
    except OSError:
        return "file_unavailable"
    if not path.is_file():
        return "not_a_file"
    expected = candidate.get("expected_size")
    if expected is not None and stat.st_size != expected:
        return f"size_changed({stat.st_size}!={expected})"
    return None


def _process_clip(run: Run, clip: dict[str, Any]) -> None:
    cfg = run.config
    clip_id = clip["clip_id"]
    prior = run.prior.get(clip_id, {})
    switches: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    used: list[str] = []
    handled = failed = reused = analyzed = 0
    next_start = cfg.start_frame
    last_index = cfg.start_frame - 1
    eof = limit_reached = False
    decode_error: str | None = None
    info: dict[str, Any] | None = None
    declared: int | None = None
    previous_label: str | None = None
    for candidate in _viable_candidates(clip):
        if _cancel_requested(run) or run.poisoned:
            break
        reason = _check_candidate(candidate)
        if reason:
            rejected.append({"label": candidate["label"], "reason": reason})
            run.error("replica_rejected", f"{candidate['label']}: {reason}", clip_id=clip_id)
            continue
        if previous_label is not None:
            switches.append({"from": previous_label, "to": candidate["label"], "at_frame": next_start})
            run.error("replica_switch", f"{previous_label} -> {candidate['label']} (프레임 {next_start}부터)", clip_id=clip_id)
        previous_label = candidate["label"]
        used.append(candidate["label"])
        try:
            reader = run.reader_factory(Path(candidate["path"]))
        except DecodeError as exc:
            decode_error = str(exc)
            run.error("decode_error", decode_error, clip_id=clip_id, replica=candidate["label"])
            continue
        info = reader.info.to_payload()
        declared = reader.info.declared_frames
        remaining = None if cfg.max_frames_per_clip is None else cfg.max_frames_per_clip - handled
        producer = BoundedProducer(
            lambda r=reader, s=next_start, e=cfg.end_frame, l=remaining: r.frames(s, e, l), cfg.queue_size)
        try:
            for frame in producer:
                if _cancel_requested(run):
                    break
                # First-frame metadata is populated during decode, after _probe.
                info = reader.info.to_payload()
                outcome = _handle_frame(run, clip, frame, prior, candidate["label"], info)
                handled += 1
                last_index = frame.index
                next_start = frame.index + 1
                run.counts["frames_decoded"] += 1
                if outcome == "failed":
                    failed += 1
                    run.counts["frames_failed"] += 1
                else:
                    analyzed += 1
                    run.counts["frames_analyzed"] += 1
                    if outcome == "reused":
                        reused += 1
                        run.counts["frames_reused"] += 1
                if run.poisoned:
                    break
                run.publish(status=store.RUNNING, phase="inspecting", current_clip=clip["display_name"],
                            current_frame=frame.index)
                if _cancel_requested(run):
                    break
        finally:
            producer.close()
            run.decode_s += producer.decode_seconds
            reader.close()
        eof = reader.eof_reached
        info = reader.info.to_payload()
        decode_error = str(producer.error) if producer.error is not None else None
        if decode_error:
            run.error("decode_error", decode_error, clip_id=clip_id, replica=candidate["label"], frame_index=next_start)
            continue  # try another verified replica from the failed frame on
        break
    limit_reached = (cfg.max_frames_per_clip is not None and handled >= cfg.max_frames_per_clip) or \
                    (cfg.end_frame is not None and next_start >= cfg.end_frame)
    in_scope_done = eof or limit_reached
    if not used:
        status, reason = "input_unavailable", "verified_replica_unavailable"
    elif run.stop.is_set():
        status, reason = "cancelled", "cancel_requested"
    elif run.poisoned:
        status, reason = "partial", "backend_stopped"
    elif decode_error or not in_scope_done:
        status = "partial" if analyzed else "failed"
        reason = "decode_error" if decode_error else "range_not_finished"
    elif failed:
        status, reason = "partial", "frame_analysis_failed"
    else:
        status, reason = "completed", None
    _clip_record(
        run, clip, status, reason=reason, message=decode_error,
        replica_used=used, replica_switches=switches, replicas_rejected=rejected, info=info,
        declared_frames=declared, decoded_in_scope=handled, analyzed=analyzed, failed=failed, reused=reused,
        eof_reached=eof, limit_reached=limit_reached, last_frame_index=last_index if handled else None,
        declared_mismatch=bool(eof and declared and not cfg.start_frame and cfg.end_frame is None
                               and cfg.max_frames_per_clip is None and handled != declared))
    if status == "input_unavailable":
        run.error("clip_input_unavailable", "선택 가능한 검증된 복제본이 없어 검사하지 못했습니다.", clip_id=clip_id, replicas_rejected=rejected)


def _handle_frame(run: Run, clip: dict[str, Any], frame: Any, prior: dict[int, dict[str, Any]],
                  replica_label: str, info: dict[str, Any]) -> str:
    """Analyze (or reuse) one frame and journal it. Returns analyzed|reused|failed."""
    old = prior.get(frame.index)
    if old and old.get("status") == "analyzed" and old.get("analysis_fp") == run.analysis_fp:
        frame.release()
        return "reused"
    record: dict[str, Any] = {
        "type": "frame", "clip_id": clip["clip_id"], "clip_name": clip["display_name"],
        "frame_index": frame.index, "pts": frame.pts, "time_base": frame.time_base,
        "clip_time_s": frame.clip_time_s, "source_size": [frame.source_width, frame.source_height],
        "key_frame": frame.key_frame, "analysis_fp": run.analysis_fp, "replica": replica_label,
        "recorded_at": utc_now(),
        "decode": {"rotation_applied_deg": info.get("rotation_deg", 0), "color_space": info.get("color_space"),
                   "color_range": info.get("color_range"), "color_transfer": info.get("color_transfer"),
                   "pix_fmt": info.get("pix_fmt")},
    }
    prepared = time.perf_counter()
    try:
        image = frame.image()
        model_image, preprocess = prepare_model_image(image, run.config.model_max_side)
        from PIL import ImageStat

        record["image_stats"] = {"mean_luma": round(ImageStat.Stat(model_image.convert("L")).mean[0], 1)}
        record["source_size"] = list(image.size)  # after display rotation
    except Exception as exc:
        record.update(status="failed", error={"kind": "decode_convert_failed", "message": str(exc)[:400]})
        frame.release()
        run.frames.append(record)
        run.error("frame_failed", str(exc), clip_id=clip["clip_id"], frame_index=frame.index, error_kind="decode_convert_failed")
        return "failed"
    run.prepare_s += time.perf_counter() - prepared
    record["preprocess"] = preprocess
    record["model_size"] = preprocess["model_size"]
    try:
        analysis = analyze_frame(run.backend, model_image, source_size=image.size, config=run.config)
    except BackendPoisoned as exc:
        run.poisoned = str(exc)
        analysis = {"status": "failed", "error": {"kind": exc.kind, "message": str(exc)}, "attempts": []}
    record.update(analysis)
    inference = analysis.get("inference") or {}
    run.infer_s += float(inference.get("elapsed_s") or 0.0)
    run.peak_memory = max(run.peak_memory, int(inference.get("peak_memory_bytes") or 0))
    record["evidence"] = None
    if analysis["status"] == "analyzed" and analysis["findings"]:
        record["evidence"] = _save_evidence(run, clip, image, frame.index, analysis["findings"])
    frame.release()
    run.frames.append(record)
    if analysis["status"] == "failed":
        run.error("frame_failed", analysis["error"]["message"], clip_id=clip["clip_id"], frame_index=frame.index,
                  error_kind=analysis["error"]["kind"])
        return "failed"
    return "analyzed"


def _save_evidence(run: Run, clip: dict[str, Any], image: Any, index: int,
                   findings: list[dict[str, Any]]) -> dict[str, Any] | None:
    from orchestrator.visual_qa.evidence import save_frame_evidence

    clip_id = clip["clip_id"]
    saved = run.evidence_counts.get(clip_id, 0)
    if saved >= run.config.max_evidence_frames_per_clip:
        return {"original": None, "skipped": "max_evidence_frames_per_clip"}
    try:
        evidence = save_frame_evidence(image, run.qa.path, clip_id, index, findings)
    except Exception as exc:  # evidence trouble must not lose the analysis result
        run.error("evidence_failed", str(exc), clip_id=clip_id, frame_index=index)
        return {"original": None, "skipped": f"evidence_write_failed: {type(exc).__name__}"}
    run.evidence_counts[clip_id] = saved + 1
    return evidence


# ---------------------------------------------------------------- outputs

def load_journal(qa: QaDir) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    """Latest record per frame, and the latest record per clip (manifest order kept by callers)."""
    frame_records, _ = read_jsonl(qa.frames)
    latest: dict[tuple[str, int], dict[str, Any]] = {}
    for record in frame_records:
        if record.get("type") == "frame":
            latest[(record["clip_id"], record["frame_index"])] = record
    clip_records, _ = read_jsonl(qa.clips)
    clips: dict[str, dict[str, Any]] = {}
    for record in clip_records:
        if record.get("type") == "clip":
            clips[record["clip_id"]] = record
    return sorted(latest.values(), key=lambda r: (r["clip_id"], r["frame_index"])), clips


def build_results(qa: QaDir, manifest: dict[str, Any]) -> dict[str, Any]:
    frames, clip_records = load_journal(qa)
    analysis_fp_now = None
    model_fp = manifest.get("model_fingerprint")
    if model_fp:
        analysis_fp_now = digest([QaConfig.from_payload(manifest["config"]).fingerprint(), model_fp])
    valid = [f for f in frames if analysis_fp_now is None or f.get("analysis_fp") == analysis_fp_now]
    clips_meta = {c["clip_id"]: c for c in manifest["clips"]}
    cfg = QaConfig.from_payload(manifest["config"])
    events = group_events(valid, clips_meta, min_iou=cfg.group_min_iou)
    per_clip = []
    for clip in manifest["clips"]:
        record = clip_records.get(clip["clip_id"])
        own = [f for f in valid if f["clip_id"] == clip["clip_id"]]
        per_clip.append({
            "clip_id": clip["clip_id"], "display_name": clip["display_name"], "source_relpath": clip["source_relpath"],
            "kind": clip["kind"], "format_label": clip.get("format_label"),
            "status": record["status"] if record else "not_run", "reason": (record or {}).get("reason"),
            "message": (record or {}).get("message"), "replica_used": (record or {}).get("replica_used", []),
            "replica_switches": (record or {}).get("replica_switches", []),
            "replicas_rejected": (record or {}).get("replicas_rejected", []),
            "info": (record or {}).get("info"), "declared_frames": (record or {}).get("declared_frames"),
            "eof_reached": (record or {}).get("eof_reached"), "limit_reached": (record or {}).get("limit_reached"),
            "declared_mismatch": (record or {}).get("declared_mismatch"),
            "frames_in_scope": len(own),
            "frames_analyzed": sum(1 for f in own if f["status"] == "analyzed"),
            "frames_failed": sum(1 for f in own if f["status"] == "failed"),
            "frames_no_issue": sum(1 for f in own if f.get("frame_assessment") == "no_issue_observed"),
            "frames_suspect": sum(1 for f in own if f.get("frame_assessment") == "suspect"),
            "frames_inconclusive": sum(1 for f in own if f.get("frame_assessment") == "inconclusive"),
            "first_frame": own[0]["frame_index"] if own else None,
            "last_frame": own[-1]["frame_index"] if own else None,
            "failed_frame_indexes": [f["frame_index"] for f in own if f["status"] == "failed"][:200],
        })
    counts = {
        "clips_total": len(per_clip),
        "clips_completed": sum(c["status"] == "completed" for c in per_clip),
        "clips_partial": sum(c["status"] == "partial" for c in per_clip),
        "clips_failed": sum(c["status"] == "failed" for c in per_clip),
        "clips_unsupported": sum(c["status"] == "unsupported" for c in per_clip),
        "clips_input_unavailable": sum(c["status"] == "input_unavailable" for c in per_clip),
        "clips_not_run": sum(c["status"] in {"not_run", "cancelled"} for c in per_clip),
        "frames_decoded": len(valid),
        "frames_analyzed": sum(1 for f in valid if f["status"] == "analyzed"),
        "frames_failed": sum(1 for f in valid if f["status"] == "failed"),
        "frames_no_issue": sum(1 for f in valid if f.get("frame_assessment") == "no_issue_observed"),
        "frames_suspect": sum(1 for f in valid if f.get("frame_assessment") == "suspect"),
        "frames_inconclusive": sum(1 for f in valid if f.get("frame_assessment") == "inconclusive"),
        "events_total": len(events),
        "events_high": sum(e["priority"] == "high" for e in events),
        "events_medium": sum(e["priority"] == "medium" for e in events),
        "events_low": sum(e["priority"] == "low" for e in events),
    }
    ok_clips = all(c["status"] == "completed" for c in per_clip if c["kind"] == "video" and c["status"] != "not_run") \
        if not cfg.max_clips else all(c["status"] == "completed" for c in per_clip if c["status"] not in {"not_run"})
    any_gap = any(c["status"] in {"unsupported", "input_unavailable", "failed", "partial", "cancelled"} or
                  (c["status"] == "not_run" and cfg.max_clips is None) for c in per_clip)
    if any_gap or not per_clip or not ok_clips:
        coverage = "incomplete"
    else:
        coverage = "limited" if cfg.is_limited else "full"
    return {"grouping_version": GROUPING_VERSION, "events": events, "clips": per_clip, "counts": counts,
            "coverage": coverage, "frames_with_stale_fingerprint": len(frames) - len(valid)}


def _write_findings(qa: QaDir, manifest: dict[str, Any]) -> str | None:
    try:
        results = build_results(qa, manifest)
        store.write_json_atomic(qa.findings, {
            "qa_id": qa.qa_id, "run_id": manifest.get("run_id"), "analysis": manifest.get("config"),
            "model": manifest.get("model"), "coverage": results["coverage"], "counts": results["counts"],
            "clips": results["clips"], "events": results["events"], "grouping_version": GROUPING_VERSION,
            "note": "의심 사항이며 확정된 결함이 아닙니다. 프레임별 원본 결과는 frames.jsonl에 보존됩니다.",
        })
    except Exception as exc:
        qa.write_state(report_error=f"findings: {type(exc).__name__}: {exc}")
        return f"findings: {exc}"
    return None


def _write_report(qa: QaDir) -> str | None:
    try:
        from orchestrator.visual_qa.report import write_report

        write_report(qa)
        qa.write_state(report_error=None)
    except Exception as exc:  # the journal and findings.json are already safe on disk
        qa.write_state(report_error=f"report: {type(exc).__name__}: {exc}")
        return f"report: {exc}"
    return None


def _write_outputs_best_effort(qa: QaDir, manifest: dict[str, Any], run: Run | None) -> str | None:
    """Write findings/report. Failure here never touches the journal."""
    return _write_findings(qa, manifest) or _write_report(qa)


def _finalize(qa: QaDir, manifest: dict[str, Any], run: Run, session: dict[str, Any]) -> dict[str, Any]:
    error = _write_findings(qa, manifest)
    findings = store.read_json_safe(qa.findings)
    counts = findings.get("counts") or {}
    coverage = findings.get("coverage") or "incomplete"
    if run.stop.is_set():
        status, reason = store.CANCELLED, "cancel_requested"
    elif run.poisoned:
        status, reason = store.PARTIAL if counts.get("frames_analyzed") else store.FAILED, "backend_stopped"
    elif counts.get("clips_total") and coverage in {"full", "limited"} and not counts.get("frames_failed"):
        status, reason = store.COMPLETED, None
    elif counts.get("frames_analyzed"):
        status, reason = store.PARTIAL, "incomplete_coverage"
    else:
        status, reason = store.FAILED, "no_inspectable_clips"
    prior_sessions = qa.read_state().get("sessions", [])
    fresh = max(1, run.counts["frames_analyzed"] - run.counts["frames_reused"])
    summary = {
        "qa_id": qa.qa_id, "run_id": manifest.get("run_id"), "status": status, "reason": reason,
        "coverage": coverage, "counts": counts, "mock_backend": bool((manifest.get("model") or {}).get("is_mock")),
        "timings": {"decode_only_s": round(run.decode_s, 2), "prepare_s": round(run.prepare_s, 2),
                    "inference_s": round(run.infer_s, 2),
                    "session_wall_s": session["wall_s"], "mean_inference_s_per_frame": round(run.infer_s / fresh, 3)},
        "peak_memory_bytes_reported_by_backend": run.peak_memory or None,
        "sessions": [*prior_sessions, session], "finished_at": utc_now(),
    }
    store.write_json_atomic(qa.summary, summary)
    qa.write_state(status=status, reason=reason, phase="done", counts=counts or run.counts,
                           coverage=coverage, heartbeat_at=utc_now(), sessions=summary["sessions"],
                           events_total=counts.get("events_total"), message=error, current_clip=None,
                           current_frame=None, mock_backend=summary["mock_backend"])
    # Render last so the report shows the final status and times; a render failure
    # only sets report_error and leaves every result above intact.
    _write_report(qa)
    return qa.read_state()


def rebuild_outputs(qa_dir: Path) -> str | None:
    """Regenerate findings.json/summary inputs and report.html from the stored journal only."""
    qa = QaDir(qa_dir)
    manifest = store.read_json_safe(qa.manifest)
    if not manifest:
        raise ValueError(f"manifest.json missing or unreadable in {qa_dir}")
    return _write_outputs_best_effort(qa, manifest, None)
