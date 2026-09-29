"""Group per-frame findings into human-reviewable events. Journal stays the source of truth."""
from __future__ import annotations

from typing import Any

from orchestrator.visual_qa.schema import CATEGORY_LABELS, PRIORITY_RANK, iou

GROUPING_VERSION = "vqa-group-v1"


def _bbox(finding: dict[str, Any]) -> list[float] | None:
    location = finding.get("location") or {}
    return location.get("bbox_source_px") if location.get("status") == "ok" else None


def _compatible(event: dict[str, Any], finding: dict[str, Any], min_iou: float) -> tuple[bool, float]:
    """Same category is required; boxes must overlap when both sides have one."""
    if event["category"] != finding["category"]:
        return False, 0.0
    a, b = event["_last_bbox"], _bbox(finding)
    if a is not None and b is not None:
        score = iou(a, b)
        return score >= min_iou, score
    return True, 0.0


def group_events(frames: list[dict[str, Any]], clips: dict[str, dict[str, Any]], *,
                 min_iou: float = 0.2) -> list[dict[str, Any]]:
    """``frames`` are journal records. Only ``status == analyzed`` frames can form events.

    A finding continues an event only when it sits on the *next* frame index, so
    frames that were failed, skipped or not inspected always split events; we never
    assume an issue persisted across an unexamined stretch.
    """
    by_clip: dict[str, list[dict[str, Any]]] = {}
    for record in frames:
        if record.get("status") == "analyzed" and record.get("findings"):
            by_clip.setdefault(record["clip_id"], []).append(record)
    events: list[dict[str, Any]] = []
    order = {clip_id: index for index, clip_id in enumerate(clips)}
    for clip_id in sorted(by_clip, key=lambda c: order.get(c, 1 << 30)):
        clip = clips.get(clip_id, {})
        open_events: list[dict[str, Any]] = []
        clip_events: list[dict[str, Any]] = []
        for record in sorted(by_clip[clip_id], key=lambda r: r["frame_index"]):
            index = record["frame_index"]
            still_open = [e for e in open_events if e["end_frame"] == index - 1]
            used: set[int] = set()
            next_open: list[dict[str, Any]] = []
            for position, finding in enumerate(record["findings"]):
                best, best_score = None, -1.0
                for event in still_open:
                    if id(event) in used:
                        continue
                    ok, score = _compatible(event, finding, min_iou)
                    if ok and score > best_score:
                        best, best_score = event, score
                if best is None:
                    best = {"clip_id": clip_id, "category": finding["category"], "start_frame": index,
                            "end_frame": index, "_items": [], "_last_bbox": None}
                    clip_events.append(best)
                else:
                    used.add(id(best))
                best["end_frame"] = index
                best["_items"].append((record, position))
                best["_last_bbox"] = _bbox(finding) or best["_last_bbox"]
                next_open.append(best)
            open_events = next_open
        for sequence, event in enumerate(clip_events, 1):
            events.append(_finalize(event, clip, sequence))
    return events


def _finalize(event: dict[str, Any], clip: dict[str, Any], sequence: int) -> dict[str, Any]:
    items = event.pop("_items")
    event.pop("_last_bbox")

    def rank(item: tuple[dict[str, Any], int]) -> tuple[int, int, int, int]:
        record, position = item
        finding = record["findings"][position]
        has_evidence = 1 if (record.get("evidence") or {}).get("original") else 0
        has_location = 1 if _bbox(finding) else 0
        return (PRIORITY_RANK[finding["priority"]], has_evidence, has_location, -record["frame_index"])

    rep_record, rep_pos = max(items, key=rank)
    rep = rep_record["findings"][rep_pos]
    frames = [{"frame_index": r["frame_index"], "clip_time_s": r.get("clip_time_s"),
               "priority": r["findings"][p]["priority"], "has_evidence": bool((r.get("evidence") or {}).get("original"))}
              for r, p in items]
    first, last = items[0][0], items[-1][0]
    boxes = [_bbox(r["findings"][p]) for r, p in items]
    located = [b for b in boxes if b]
    evidence_refs = []
    for record in (first, rep_record, last):
        ev = record.get("evidence")
        if ev and ev.get("original") and all(ev["original"] != e["evidence"]["original"] for e in evidence_refs):
            evidence_refs.append({"frame_index": record["frame_index"], "clip_time_s": record.get("clip_time_s"),
                                  "evidence": ev})
    count = len(items)
    temporal_flag = any(r["findings"][p]["needs_temporal_confirmation"] for r, p in items)
    return {
        "event_id": f"evt-{event['clip_id']}-{event['start_frame']:07d}-{event['category']}-{sequence}",
        "clip_id": event["clip_id"],
        "clip_name": clip.get("display_name"),
        "category": event["category"],
        "category_label": CATEGORY_LABELS[event["category"]],
        "priority": max((r["findings"][p]["priority"] for r, p in items), key=PRIORITY_RANK.get),
        "start_frame": event["start_frame"], "end_frame": event["end_frame"],
        "start_time_s": first.get("clip_time_s"), "end_time_s": last.get("clip_time_s"),
        "frame_count": count, "frames": frames,
        "representative_frame": rep_record["frame_index"],
        "observation": rep["observation"], "reason_for_review": rep["reason_for_review"],
        "uncertainty": rep["uncertainty"], "suggested_human_check": rep["suggested_human_check"],
        "location": rep.get("location"),
        "location_consistency": ("boxes_overlap" if len(located) == count and count > 1 else
                                 "single_or_unlocated" if count == 1 or not located else "partly_located"),
        "needs_temporal_confirmation": temporal_flag,
        "temporal_status": ("single_frame_only" if count == 1 else f"observed_in_{count}_consecutive_frames"),
        "evidence_frames": evidence_refs,
        "human_review_status": "unreviewed",
        "grouping_version": GROUPING_VERSION,
    }
