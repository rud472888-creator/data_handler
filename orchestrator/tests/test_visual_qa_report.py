from __future__ import annotations

from orchestrator.visual_qa.report import fmt_time, render_report

EVIDENCE = {"original": "evidence/c1/0000003.jpg", "preview": "evidence/c1/0000003_preview.jpg",
            "marked": "evidence/c1/0000003_marked.jpg",
            "crops": [{"finding_index": 0, "number": 1, "path": "evidence/c1/0000003_crop1.jpg"}]}


def make(events=None, coverage="full", mock=False, config=None, status="completed", clips=None):
    manifest = {"qa_id": "qa-x", "run_id": "run-1", "config": {"model_max_side": 1024, **(config or {})},
                "upstream": {"project_name": "<b>P</b>", "shoot_date": "2026-01-02", "roll": "R#1"}}
    findings = {"coverage": coverage, "model": {"is_mock": mock, "original_model_id": "Qwen/Qwen3.5-4B", "runtime": {}},
                "counts": {"events_total": len(events or []), "frames_analyzed": 3, "clips_total": 1},
                "clips": clips if clips is not None else [{"clip_id": "c1", "display_name": "a.mp4", "source_relpath": "A/a.mp4",
                                                          "status": "completed", "frames_analyzed": 3, "frames_failed": 0,
                                                          "info": {"width": 3840, "height": 2160}, "replica_used": ["path1"]}],
                "events": events or []}
    return render_report(manifest, findings, {"status": status}, [])


def event(**over):
    base = {"event_id": "evt-1", "clip_id": "c1", "clip_name": "긴파일명_<img src=x onerror=alert(1)>.mp4",
            "category": "equipment_intrusion", "category_label": "촬영 장비 침범 의심", "priority": "high",
            "start_frame": 3, "end_frame": 3, "start_time_s": 0.125, "end_time_s": 0.125, "frame_count": 1,
            "representative_frame": 3, "observation": "<script>alert('x')</script> 마이크",
            "reason_for_review": "확인", "uncertainty": None, "suggested_human_check": "원본 확인",
            "location": {"status": "ok", "bbox_source_px": [1, 2, 3, 4]}, "needs_temporal_confirmation": True,
            "evidence_frames": [{"frame_index": 3, "clip_time_s": 0.125, "evidence": EVIDENCE}]}
    return {**base, **over}


def test_model_and_file_text_is_escaped():
    html = make([event()])
    assert "<script>" not in html and "&lt;script&gt;" in html
    assert "<img src=x" not in html and "&lt;b&gt;P&lt;/b&gt;" in html


def test_images_use_relative_paths_and_link_to_original_resolution():
    html = make([event()])
    assert 'src="evidence/c1/0000003_marked.jpg"' in html
    assert 'href="evidence/c1/0000003.jpg"' in html and "원본 해상도 열기" in html
    assert 'src="evidence/c1/0000003_crop1.jpg"' in html
    assert "http://" not in html and "https://" not in html and 'src="/' not in html


def test_zero_events_wording_depends_on_coverage():
    assert "검사한 범위에서 의심 사항을 발견하지 못했습니다" in make([])
    assert "완벽" not in make([])
    incomplete = make([], coverage="incomplete", status="partial")
    assert "검사 범위가 불완전" in incomplete and "발견하지 못했습니다" not in incomplete


def test_limited_and_mock_are_flagged():
    limited = make([], coverage="limited", config={"max_frames_per_clip": 5})
    assert "제한 범위 검사" in limited and "클립당 최대 5프레임" in limited
    assert "MOCK 백엔드" in make([], mock=True) and "MOCK 백엔드" not in make([])


def test_missing_location_and_evidence_are_stated_not_faked():
    html = make([event(location=None, evidence_frames=[])])
    assert "위치 정보를 얻지 못했습니다" in html and "증거 이미지가 저장되지 않았습니다" in html


def test_resolution_gap_and_disclaimer_present():
    html = make([event()])
    assert "3840×2160 → 1024×576" in html and "결함 확정이나 납품 합격 판정이 아닙니다" in html


def test_time_format_is_clip_relative_and_unknown_is_explicit():
    assert fmt_time(83.456) == "00:01:23.456" and fmt_time(None) == "시각 미상"
