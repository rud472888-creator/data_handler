from __future__ import annotations

import json

import pytest

from orchestrator.visual_qa import schema
from orchestrator.visual_qa.schema import OutputError, parse_model_output

from visual_qa_helpers import CLEAN_JSON, issue_json


def parse(text, finish="stop", model=(1024, 576), source=(3840, 2160)):
    return parse_model_output(text, finish_reason=finish, image_size=model, source_size=source)


def test_valid_suspect_result_keeps_fields_and_converts_bbox_to_source_pixels():
    parsed = parse(issue_json("equipment_intrusion", "high", bbox=[100, 200, 300, 400], temporal=True))
    finding = parsed.result["findings"][0]
    assert parsed.result["frame_assessment"] == "suspect"
    assert finding["category"] == "equipment_intrusion" and finding["priority"] == "high"
    location = finding["location"]
    assert location["status"] == "ok"
    assert location["bbox_grid"] == [100, 200, 300, 400]
    assert location["bbox_model_px"] == [102.4, 115.2, 307.2, 230.4]
    assert location["bbox_source_px"] == [384.0, 432.0, 1152.0, 864.0]
    assert finding["needs_temporal_confirmation"] is True


def test_no_issue_is_distinct_from_inconclusive_and_failure():
    assert parse(CLEAN_JSON).result["frame_assessment"] == "no_issue_observed"
    inconclusive = json.dumps({"frame_assessment": "inconclusive", "findings": []})
    assert parse(inconclusive).result["frame_assessment"] == "inconclusive"
    with pytest.raises(OutputError) as excinfo:
        parse("not json at all")
    assert excinfo.value.kind == "invalid_json"


@pytest.mark.parametrize("text", ["", "   ", "{", '{"frame_assessment": "suspect", "findings": ['])
def test_broken_json_is_an_error_not_a_pass(text):
    with pytest.raises(OutputError) as excinfo:
        parse(text)
    assert excinfo.value.kind == "invalid_json"


def test_output_cut_at_token_limit_is_truncated_even_if_json_looks_complete():
    with pytest.raises(OutputError) as excinfo:
        parse(CLEAN_JSON, finish="length")
    assert excinfo.value.kind == "truncated"


@pytest.mark.parametrize("payload", [
    {"frame_assessment": "fine", "findings": []},
    {"frame_assessment": "suspect", "findings": []},
    {"frame_assessment": "no_issue_observed", "findings": json.loads(issue_json())["findings"]},
    {"frame_assessment": "suspect", "findings": "none"},
    {"frame_assessment": "suspect", "findings": [{"category": "made_up"}]},
    [],
])
def test_schema_violations_are_rejected(payload):
    with pytest.raises(OutputError) as excinfo:
        parse(json.dumps(payload))
    assert excinfo.value.kind == "schema_invalid"


def test_finding_field_rules():
    base = json.loads(issue_json())["findings"][0]
    for change in ({"priority": "urgent"}, {"observation": ""}, {"needs_temporal_confirmation": "yes"},
                   {"suggested_human_check": None}):
        bad = {"frame_assessment": "suspect", "findings": [{**base, **change}]}
        with pytest.raises(OutputError):
            parse(json.dumps(bad))
    too_many = {"frame_assessment": "suspect", "findings": [base] * (schema.MAX_FINDINGS + 1)}
    with pytest.raises(OutputError):
        parse(json.dumps(too_many))


def test_fenced_and_prefixed_json_is_accepted_with_warning_but_still_validated():
    fenced = parse("```json\n" + CLEAN_JSON + "\n```")
    assert fenced.result["frame_assessment"] == "no_issue_observed"
    prefixed = parse("결과입니다: " + CLEAN_JSON + " 끝")
    assert "json_extracted_from_surrounding_text" in prefixed.warnings


def test_thinking_block_is_stripped_but_flagged_and_unclosed_is_failure():
    parsed = parse("<think>\n생각\n</think>\n" + CLEAN_JSON)
    assert "thinking_block_in_output" in parsed.warnings
    with pytest.raises(OutputError) as excinfo:
        parse("<think>\n생각이 끝나지 않음")
    assert excinfo.value.kind == "truncated"


@pytest.mark.parametrize("bbox", [[10, 10, 5, 50], [-1, 0, 10, 10], [0, 0, 1001, 10], [1, 2, 3], ["a", 1, 2, 3], [True, 0, 5, 5]])
def test_invalid_bbox_is_discarded_not_replaced_with_a_guess(bbox):
    finding = parse(issue_json(bbox=bbox)).result["findings"][0]
    assert finding["location"]["status"] == "invalid_discarded"
    assert finding["location"]["bbox_source_px"] is None


def test_whole_frame_box_is_treated_as_not_localized():
    finding = parse(issue_json(bbox=[0, 0, 1000, 1000])).result["findings"][0]
    assert finding["location"]["status"] == "not_localized"
    assert finding["location"]["bbox_source_px"] is None


def test_missing_location_stays_null():
    finding = parse(issue_json(bbox=None)).result["findings"][0]
    assert finding["location"]["status"] == "not_provided"
    assert finding["location"]["bbox_source_px"] is None and finding["location"]["point_source_px"] is None


def test_point_conversion_and_validation():
    item = json.loads(issue_json())
    item["findings"][0]["point"] = [500, 250]
    location = parse(json.dumps(item)).result["findings"][0]["location"]
    assert location["point_source_px"] == [1920.0, 540.0]
    item["findings"][0]["point"] = [500, 2500]
    assert parse(json.dumps(item)).result["findings"][0]["location"]["status"] == "invalid_discarded"


def test_iou():
    assert schema.iou([0, 0, 10, 10], [0, 0, 10, 10]) == 1.0
    assert schema.iou([0, 0, 10, 10], [20, 20, 30, 30]) == 0.0
    assert 0.1 < schema.iou([0, 0, 10, 10], [5, 0, 15, 10]) < 0.5
