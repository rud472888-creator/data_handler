from __future__ import annotations

from orchestrator.visual_qa.events import group_events


def finding(category="equipment_intrusion", priority="medium", bbox=None, temporal=False, note="관찰"):
    location = {"status": "ok", "bbox_source_px": bbox} if bbox else {"status": "not_provided", "bbox_source_px": None}
    return {"category": category, "priority": priority, "observation": note, "reason_for_review": "이유",
            "uncertainty": None, "needs_temporal_confirmation": temporal, "suggested_human_check": "확인", "location": location}


def frame(index, findings=None, status="analyzed", clip="c1", evidence=True):
    record = {"type": "frame", "clip_id": clip, "frame_index": index, "clip_time_s": index / 24, "status": status,
              "frame_assessment": "suspect" if findings else "no_issue_observed", "findings": findings or []}
    if findings and evidence:
        record["evidence"] = {"original": f"evidence/{clip}/{index:07d}.jpg", "preview": "p", "marked": None, "crops": []}
    return record


CLIPS = {"c1": {"display_name": "A001.mp4"}, "c2": {"display_name": "A002.mp4"}}


def test_consecutive_frames_with_same_category_form_one_event_and_keep_frame_list():
    frames = [frame(i, [finding()]) for i in (3, 4, 5)]
    events = group_events(frames, CLIPS)
    assert len(events) == 1
    event = events[0]
    assert (event["start_frame"], event["end_frame"], event["frame_count"]) == (3, 5, 3)
    assert [f["frame_index"] for f in event["frames"]] == [3, 4, 5]
    assert event["temporal_status"] == "observed_in_3_consecutive_frames"
    assert event["human_review_status"] == "unreviewed"
    assert event["clip_name"] == "A001.mp4"


def test_single_frame_event_is_kept():
    events = group_events([frame(7, [finding("pixel_anomaly", "low")])], CLIPS)
    assert len(events) == 1 and events[0]["frame_count"] == 1
    assert events[0]["temporal_status"] == "single_frame_only"


def test_clean_frame_between_findings_splits_events():
    frames = [frame(1, [finding()]), frame(2), frame(3, [finding()])]
    assert len(group_events(frames, CLIPS)) == 2


def test_failed_or_missing_frames_never_bridge_an_event():
    frames = [frame(1, [finding()]), frame(2, status="failed"), frame(3, [finding()]), frame(5, [finding()])]
    events = group_events(frames, CLIPS)
    assert [(e["start_frame"], e["end_frame"]) for e in events] == [(1, 1), (3, 3), (5, 5)]


def test_categories_are_grouped_separately_and_frames_can_have_several_findings():
    frames = [frame(1, [finding("equipment_intrusion"), finding("focus_or_blur", "low")]),
              frame(2, [finding("equipment_intrusion"), finding("focus_or_blur", "low")])]
    events = group_events(frames, CLIPS)
    assert sorted(e["category"] for e in events) == ["equipment_intrusion", "focus_or_blur"]
    assert all(e["frame_count"] == 2 for e in events)


def test_boxes_that_do_not_overlap_start_a_new_event():
    frames = [frame(1, [finding(bbox=[0, 0, 100, 100])]), frame(2, [finding(bbox=[500, 500, 600, 600])])]
    assert len(group_events(frames, CLIPS)) == 2
    frames = [frame(1, [finding(bbox=[0, 0, 100, 100])]), frame(2, [finding(bbox=[10, 10, 110, 110])])]
    assert len(group_events(frames, CLIPS)) == 1


def test_missing_location_is_compatible_but_marked():
    frames = [frame(1, [finding(bbox=[0, 0, 100, 100])]), frame(2, [finding()])]
    events = group_events(frames, CLIPS)
    assert len(events) == 1 and events[0]["location_consistency"] == "partly_located"


def test_priority_is_max_and_representative_prefers_high_priority_with_evidence():
    frames = [frame(1, [finding(priority="low", note="약함")]), frame(2, [finding(priority="high", note="강함")]),
              frame(3, [finding(priority="medium")])]
    event = group_events(frames, CLIPS)[0]
    assert event["priority"] == "high" and event["representative_frame"] == 2 and event["observation"] == "강함"
    assert {e["frame_index"] for e in event["evidence_frames"]} == {1, 2, 3}


def test_temporal_flag_propagates_and_clips_do_not_mix():
    frames = [frame(1, [finding(temporal=True)]), frame(2, [finding()]), frame(2, [finding()], clip="c2")]
    events = group_events(frames, CLIPS)
    assert len(events) == 2
    assert events[0]["needs_temporal_confirmation"] is True and events[1]["clip_id"] == "c2"


def test_event_ids_are_deterministic():
    frames = [frame(1, [finding()])]
    assert group_events(frames, CLIPS)[0]["event_id"] == group_events(frames, CLIPS)[0]["event_id"]
