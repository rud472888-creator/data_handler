"""Offline HTML report rendered only from stored QA data (no model, no network)."""
from __future__ import annotations

import html
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote

from orchestrator.visual_qa import store
from orchestrator.visual_qa.schema import PRIORITY_RANK
from orchestrator.visual_qa.store import QaDir, read_jsonl

PRIORITY_LABEL = {"high": "높음", "medium": "보통", "low": "낮음"}
CLIP_STATUS = {
    "completed": "검사 완료", "partial": "일부만 검사", "failed": "검사 실패", "unsupported": "미지원 형식",
    "input_unavailable": "입력 사용 불가", "not_run": "검사하지 않음", "cancelled": "취소됨",
}
RUN_STATUS = {
    "queued": "대기 중", "running": "검사 중", "completed": "검사 완료", "partial": "일부만 검사",
    "failed": "검사 실패", "blocked": "시작할 수 없음", "cancelled": "취소됨", "disabled": "사용 안 함",
}
COVERAGE = {"full": "전체 프레임 검사", "limited": "제한 범위 검사 (전체 클립 검사 아님)", "incomplete": "검사 범위 불완전"}
REASON = {
    "incomplete_coverage": "미지원·실패·누락된 클립이나 프레임이 있어 전체 검사가 끝나지 않았습니다.",
    "no_inspectable_clips": "검사할 수 있는 클립이 없었습니다.",
    "backend_stopped": "모델 추론이 응답하지 않아 남은 검사를 중단했습니다.",
    "model_not_installed": "Qwen3.5-4B 모델이 설치되어 있지 않습니다.",
    "unsupported_platform": "이 컴퓨터에서는 MLX 추론을 실행할 수 없습니다 (Apple Silicon macOS 필요).",
    "runtime_missing": "추론 런타임(mlx-vlm)을 불러오지 못했습니다.",
    "model_changed": "다른 모델로 시작된 검사라 결과를 섞지 않고 중단했습니다.",
    "cancel_requested": "사용자 요청으로 취소되었습니다.",
    "worker_crashed": "검사 프로세스가 오류로 종료되었습니다.",
}
ERROR_KIND = {
    "invalid_json": "JSON 해석 실패", "schema_invalid": "스키마 검증 실패", "truncated": "출력 잘림",
    "timeout": "시간 초과", "out_of_memory": "메모리 부족", "backend_error": "백엔드 오류",
    "decode_convert_failed": "프레임 변환 실패",
}


def e(value: Any) -> str:
    return html.escape("" if value is None else str(value), quote=True)


def fmt_time(seconds: Any) -> str:
    if not isinstance(seconds, (int, float)):
        return "시각 미상"
    sign = "-" if seconds < 0 else ""
    seconds = abs(seconds)
    hours, rest = divmod(seconds, 3600)
    minutes, secs = divmod(rest, 60)
    return f"{sign}{int(hours):02d}:{int(minutes):02d}:{secs:06.3f}"


def fmt_dt(value: Any) -> str:
    try:
        return datetime.fromisoformat(str(value)).astimezone().strftime("%Y-%m-%d %H:%M:%S")
    except (TypeError, ValueError):
        return "-"


def href(path: str | None) -> str:
    return "/".join(quote(part) for part in (path or "").split("/"))


def size_text(value: Any) -> str:
    return f"{value[0]}×{value[1]}" if isinstance(value, list) and len(value) == 2 else "-"


def model_size(info: dict[str, Any] | None, max_side: int) -> str:
    if not info or not info.get("width"):
        return "-"
    w, h = info["width"], info["height"]
    if info.get("rotation_deg") in (90, 270):
        w, h = h, w
    scale = min(1.0, max_side / max(w, h))
    return f"{max(1, round(w * scale))}×{max(1, round(h * scale))}"


CSS = """
:root{--bg:#f4f6f9;--surface:#fff;--text:#172033;--muted:#667085;--border:#e4e8ef;--accent:#3568d4;--danger:#b3261e;--warn-bg:#fff8eb;--warn:#b85c00;--ok:#16825d;--danger-bg:#fff4f2;--mono:ui-monospace,SFMono-Regular,Menlo,monospace}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--text);font:14px/1.5 ui-sans-serif,system-ui,-apple-system,"Apple SD Gothic Neo","Malgun Gothic","Noto Sans KR",sans-serif;overflow-wrap:anywhere}
main{max-width:1180px;margin:0 auto;padding:24px 16px 64px}
h1{font-size:24px;margin:0 0 4px}h2{font-size:18px;margin:32px 0 12px}h3{font-size:15px;margin:0}
.muted{color:var(--muted)}.mono{font-family:var(--mono);font-size:12px}
.banner{border:1px solid var(--border);border-radius:8px;padding:12px 14px;margin:12px 0;background:var(--surface)}
.banner.warn{background:var(--warn-bg);border-color:#f0d9a8}.banner.bad{background:var(--danger-bg);border-color:#f0c4bd}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:12px}
.card{background:var(--surface);border:1px solid var(--border);border-radius:8px;padding:12px 14px}
dl{margin:0;display:grid;grid-template-columns:max-content 1fr;gap:4px 12px}dt{color:var(--muted)}dd{margin:0}
table{width:100%;border-collapse:collapse;background:var(--surface);border:1px solid var(--border);border-radius:8px}
th,td{text-align:left;padding:8px 10px;border-bottom:1px solid var(--border);vertical-align:top}th{color:var(--muted);font-size:12px}
.chip{display:inline-block;border-radius:999px;padding:1px 10px;font-size:12px;font-weight:700;border:1px solid var(--border)}
.chip.high{background:var(--danger-bg);color:var(--danger);border-color:#f0c4bd}.chip.medium{background:var(--warn-bg);color:var(--warn);border-color:#f0d9a8}.chip.low{background:#eef4ff;color:var(--accent)}
.event{background:var(--surface);border:1px solid var(--border);border-radius:8px;padding:14px;margin-bottom:14px}
.event header{display:flex;gap:8px;flex-wrap:wrap;align-items:center;margin-bottom:8px}
.shots{display:flex;gap:12px;flex-wrap:wrap;margin-top:10px}
figure{margin:0;max-width:100%}figure img{max-width:100%;height:auto;border:1px solid var(--border);border-radius:6px;display:block;max-height:520px}
figcaption{font-size:12px;color:var(--muted);margin-top:4px}
a{color:var(--accent)}
"""


def render_report(manifest: dict[str, Any], findings: dict[str, Any], state: dict[str, Any],
                  errors: list[dict[str, Any]], summary: dict[str, Any] | None = None) -> str:
    config = manifest.get("config") or {}
    model = findings.get("model") or manifest.get("model") or {}
    upstream = manifest.get("upstream") or {}
    counts = findings.get("counts") or {}
    coverage = findings.get("coverage") or "incomplete"
    max_side = int(config.get("model_max_side") or 1024)
    sessions = (summary or {}).get("sessions") or state.get("sessions") or []
    started = sessions[0].get("started_at") if sessions else None
    ended = sessions[-1].get("ended_at") if sessions else None
    status = state.get("status") or "-"
    events = sorted(findings.get("events") or [], key=lambda ev: (-PRIORITY_RANK[ev["priority"]], ev["clip_name"] or "", ev["start_frame"]))
    clips = findings.get("clips") or []
    runtime = model.get("runtime") or {}
    parts = [f"<!doctype html><html lang=\"ko\"><head><meta charset=\"utf-8\"><meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
             f"<title>영상 QA 보고서 - {e(upstream.get('project_name'))} {e(upstream.get('roll'))}</title><style>{CSS}</style></head><body><main>"]
    heading = " · ".join(str(x) for x in (
        upstream.get("project_name"), upstream.get("shoot_date"),
        f"카메라 {upstream['camera_unit']}" if upstream.get("camera_unit") else None,
        f"카드 {upstream.get('roll') or upstream.get('card')}" if (upstream.get("roll") or upstream.get("card")) else None,
        f"작업 {manifest.get('run_id')}") if x)
    parts.append(f"<h1>영상 QA 보고서</h1><p class=\"muted\">{e(heading)}</p>")
    if model.get("is_mock"):
        parts.append("<div class=\"banner bad\"><strong>MOCK 백엔드 결과입니다.</strong> 실제 Qwen3.5-4B 모델이 검사한 결과가 아니라 테스트용 응답입니다.</div>")
    parts.append("<div class=\"banner\"><strong>자동 시각 검사 결과입니다.</strong> 이 보고서는 사람이 확인해야 할 곳을 찾아 주는 보조 자료이며, "
                 "결함 확정이나 납품 합격 판정이 아닙니다. 검사하지 못한 항목이 있을 수 있고 놓친 문제가 있을 수 있습니다.</div>")
    if coverage != "full":
        limits = f" ({e(_limits(config))})" if config.get("max_frames_per_clip") or config.get("max_clips") or config.get("start_frame") or config.get("end_frame") else ""
        parts.append(f"<div class=\"banner warn\"><strong>{e(COVERAGE[coverage])}</strong>{limits} — 이 결과를 전체 클립 검사 완료로 해석하지 마세요.</div>")
    if status in {"partial", "failed", "blocked", "cancelled"}:
        parts.append(f"<div class=\"banner warn\"><strong>실행 상태: {e(RUN_STATUS.get(status, status))}</strong> {e(REASON.get(state.get('reason'), state.get('reason') or ''))} {e(state.get('message') or '')}</div>")

    def row(label: str, value: Any) -> str:
        return f"<dt>{e(label)}</dt><dd>{value if isinstance(value, _Raw) else e(value)}</dd>"

    failed_analysis = counts.get("frames_failed", 0)
    decode_fail = sum(1 for c in clips if c["status"] in {"partial", "failed"} and c.get("reason") == "decode_error")
    parts.append("<div class=\"grid\">")
    parts.append("<section class=\"card\"><h3>실행 정보</h3><dl>" + "".join([
        row("QA 실행 ID", manifest.get("qa_id")), row("실행 상태", RUN_STATUS.get(status, status)),
        row("검사 시작", fmt_dt(started)), row("검사 종료", fmt_dt(ended)),
        row("검사 방식", "촬영 원본 QA" if config.get("use_case") == "camera_original" else "납품본 QA"),
        row("검사 범위", f"{COVERAGE[coverage]}"), row("프레임 방식", "제한 범위(개발 옵션)" if _is_limited(config) else "디코딩 가능한 모든 프레임")]) + "</dl></section>")
    parts.append("<section class=\"card\"><h3>모델</h3><dl>" + "".join([
        row("원본 모델", model.get("original_model_id")), row("실제 로드", model.get("loaded_model") or model.get("loaded_model_path") or "-"),
        row("revision", model.get("revision") or "-"), row("양자화", model.get("quantization") or "없음/미기록"),
        row("런타임", ", ".join(f"{k} {v}" for k, v in runtime.items() if v and k in {"mlx", "mlx-vlm", "transformers", "python"}) or "-"),
        row("프롬프트 버전", config.get("prompt_version")), row("thinking", model.get("thinking_disabled") or "-")]) + "</dl></section>")
    parts.append("<section class=\"card\"><h3>검사 결과 요약</h3><dl>" + "".join([
        row("클립", f"{counts.get('clips_total', 0)}개 (완료 {counts.get('clips_completed', 0)}, 일부 {counts.get('clips_partial', 0)}, 실패 {counts.get('clips_failed', 0)})"),
        row("모델이 분석한 프레임", f"{counts.get('frames_analyzed', 0)}개"),
        row("프레임 분석 실패", f"{failed_analysis}개"), row("디코드 실패 클립", f"{decode_fail}개"),
        row("미지원 클립", f"{counts.get('clips_unsupported', 0)}개"), row("입력 사용 불가 클립", f"{counts.get('clips_input_unavailable', 0)}개"),
        row("의심 구간(event)", f"{counts.get('events_total', 0)}건 (높음 {counts.get('events_high', 0)} / 보통 {counts.get('events_medium', 0)} / 낮음 {counts.get('events_low', 0)})"),
        row("프레임 판정", f"이상 없음 관찰 {counts.get('frames_no_issue', 0)} / 의심 {counts.get('frames_suspect', 0)} / 판단 불가 {counts.get('frames_inconclusive', 0)}")]) + "</dl></section>")
    parts.append("<section class=\"card\"><h3>해상도 안내</h3><p>모델은 원본이 아니라 아래처럼 <strong>축소된 이미지</strong>로 검사했습니다 "
                 f"(가로·세로 중 긴 변 최대 {e(max_side)}px, 비율 유지). 축소 검사에서는 작은 점·미세한 노이즈·세밀한 초점 문제를 놓칠 수 있습니다. "
                 "증거 이미지는 원본 해상도 프레임을 저장한 것이며, 모델이 원본 해상도를 검사했다는 뜻이 아닙니다. 색은 디코더 기본 변환만 적용했고 LUT는 사용하지 않았습니다.</p></section>")
    parts.append("</div>")

    parts.append("<h2>의심 구간</h2>")
    if events:
        for event in events:
            parts.append(_event_html(event))
    elif coverage == "incomplete":
        parts.append("<div class=\"banner warn\">발견된 의심 사항은 0건이지만 <strong>검사 범위가 불완전</strong>합니다. 아래 클립별 검사 범위를 확인하세요.</div>")
    else:
        parts.append("<div class=\"banner\">검사한 범위에서 의심 사항을 발견하지 못했습니다. (영상에 문제가 없다는 뜻이 아닙니다.)</div>")

    parts.append("<h2>클립별 검사 범위</h2><div style=\"overflow-x:auto\"><table><thead><tr><th>클립</th><th>상태</th><th>프레임</th><th>원본 → 모델 입력</th><th>사용한 복제본</th><th>비고</th></tr></thead><tbody>")
    for clip in clips:
        info = clip.get("info") or {}
        notes = []
        if clip.get("reason"):
            notes.append(str(clip["reason"]))
        if clip.get("message"):
            notes.append(str(clip["message"]))
        if clip.get("declared_mismatch"):
            notes.append(f"컨테이너 표기 프레임 {clip.get('declared_frames')}개와 실제 디코딩 수가 다릅니다.")
        if clip.get("eof_reached") is False and clip["status"] in {"partial", "failed"}:
            notes.append("파일 끝(EOF)에 도달하지 못했습니다.")
        if clip.get("failed_frame_indexes"):
            notes.append("분석 실패 프레임: " + ", ".join(map(str, clip["failed_frame_indexes"][:20])) + (" …" if len(clip["failed_frame_indexes"]) > 20 else ""))
        for switch in clip.get("replica_switches") or []:
            notes.append(f"복제본 전환 {switch['from']}→{switch['to']} (프레임 {switch['at_frame']}부터)")
        for rej in clip.get("replicas_rejected") or []:
            notes.append(f"복제본 {rej['label']} 사용 불가: {rej['reason']}")
        rng = f"{clip['first_frame']}–{clip['last_frame']}" if clip.get("first_frame") is not None else "-"
        parts.append(f"<tr><td>{e(clip['display_name'])}<br><span class=\"muted mono\">{e(clip['source_relpath'])}</span></td>"
                     f"<td>{e(CLIP_STATUS.get(clip['status'], clip['status']))}</td>"
                     f"<td>분석 {clip['frames_analyzed']} / 실패 {clip['frames_failed']}<br><span class=\"muted\">범위 {e(rng)}"
                     f"{' · EOF 도달' if clip.get('eof_reached') else ''}</span></td>"
                     f"<td>{e(str(info.get('width', '-')) + '×' + str(info.get('height', '-')) if info else '-')} → {e(model_size(info, max_side))}</td>"
                     f"<td>{e(', '.join(clip.get('replica_used') or []) or '-')}</td><td>{'<br>'.join(e(n) for n in notes) or '-'}</td></tr>")
    parts.append("</tbody></table></div>")

    problems = [x for x in errors if x.get("kind") not in {"replica_switch"}]
    parts.append(f"<h2>오류·미지원·누락 기록 ({len(problems)}건)</h2>")
    if problems:
        parts.append("<div style=\"overflow-x:auto\"><table><thead><tr><th>종류</th><th>클립</th><th>프레임</th><th>내용</th></tr></thead><tbody>")
        for item in problems[:300]:
            parts.append(f"<tr><td>{e(ERROR_KIND.get(item.get('error_kind'), item.get('kind')))}</td><td class=\"mono\">{e(item.get('clip_id') or '-')}</td>"
                         f"<td>{e(item.get('frame_index', '-'))}</td><td>{e(item.get('message'))}</td></tr>")
        parts.append("</tbody></table></div>")
        if len(problems) > 300:
            parts.append(f"<p class=\"muted\">나머지 {len(problems) - 300}건은 errors.jsonl에서 확인하세요.</p>")
    else:
        parts.append("<p class=\"muted\">기록된 오류가 없습니다.</p>")
    parts.append("<p class=\"muted\">정상으로 관찰된 프레임 이미지는 이 보고서에 포함하지 않습니다. 프레임별 원본 결과는 frames.jsonl, 그룹화 결과는 findings.json에 있습니다. "
                 "시각은 디코더의 프레임 타임스탬프(PTS) 기준 클립 상대 시각이며 소스 타임코드가 아닙니다.</p></main></body></html>")
    return "".join(parts)


class _Raw(str):
    pass


def _is_limited(config: dict[str, Any]) -> bool:
    from orchestrator.visual_qa.config import QaConfig

    try:
        return QaConfig.from_payload(config).is_limited
    except ValueError:
        return True


def _limits(config: dict[str, Any]) -> str:
    from orchestrator.visual_qa.config import QaConfig

    try:
        return QaConfig.from_payload(config).limits_text()
    except ValueError:
        return ""


def _figure(path: str | None, caption: str, *, link: str | None = None, alt: str = "") -> str:
    if not path:
        return ""
    image = f"<img src=\"{href(path)}\" alt=\"{e(alt)}\" loading=\"lazy\">"
    body = f"<a href=\"{href(link)}\" target=\"_blank\" rel=\"noopener\">{image}</a>" if link else image
    return f"<figure>{body}<figcaption>{e(caption)}</figcaption></figure>"


def _event_html(event: dict[str, Any]) -> str:
    location = event.get("location") or {}
    frames_text = (f"프레임 {event['start_frame']}" if event["start_frame"] == event["end_frame"]
                   else f"프레임 {event['start_frame']}–{event['end_frame']} ({event['frame_count']}개 연속)")
    time_text = (fmt_time(event["start_time_s"]) if event["start_frame"] == event["end_frame"]
                 else f"{fmt_time(event['start_time_s'])} – {fmt_time(event['end_time_s'])}")
    if location.get("status") == "ok":
        box = location.get("bbox_source_px")
        point = location.get("point_source_px")
        where = (f"대략적 위치(모델 추정) 원본 좌표 [{', '.join(str(v) for v in box)}]" if box
                 else f"대략적 위치(모델 추정) 원본 좌표 ({', '.join(str(v) for v in point)})")
    else:
        where = "위치 정보를 얻지 못했습니다."
    temporal = ("시간적 확인이 필요합니다. " if event.get("needs_temporal_confirmation") else "") + \
               ("한 프레임에서만 관찰되었습니다." if event["frame_count"] == 1 else f"{event['frame_count']}개 연속 프레임에서 관찰되었습니다.")
    shots = []
    frames = event.get("evidence_frames") or []
    for item in frames:
        ev = item["evidence"]
        is_rep = item["frame_index"] == event["representative_frame"]
        label = f"{'대표 ' if is_rep else ''}프레임 {item['frame_index']} · {fmt_time(item.get('clip_time_s'))}"
        main = ev.get("marked") if is_rep and ev.get("marked") else ev.get("preview")
        shots.append(_figure(main, label + (" · 위치 표시" if main == ev.get("marked") else ""), link=ev.get("original"),
                             alt=f"{event['category_label']} {label}"))
        if is_rep:
            for crop in ev.get("crops") or []:
                shots.append(_figure(crop["path"], f"원본 크롭 #{crop['number']}", link=crop["path"], alt="원본 크롭"))
    if not shots:
        shots.append("<p class=\"muted\">증거 이미지가 저장되지 않았습니다 (클립당 증거 프레임 상한 또는 저장 오류). 프레임 번호와 시각으로 원본을 확인하세요.</p>")
    links = " ".join(f"<a href=\"{href(item['evidence']['original'])}\" target=\"_blank\" rel=\"noopener\">프레임 {e(item['frame_index'])} 원본 해상도 열기 ↗</a>"
                     for item in frames)
    return (f"<article class=\"event\" id=\"{e(event['event_id'])}\"><header><span class=\"chip {e(event['priority'])}\">우선순위 {e(PRIORITY_LABEL[event['priority']])}</span>"
            f"<h3>{e(event['category_label'])}</h3><span class=\"muted\">{e(event['clip_name'])}</span>"
            f"<span class=\"chip\">사람 검토: 미검토</span></header>"
            f"<dl><dt>구간</dt><dd>{e(frames_text)} · {e(time_text)} <span class=\"muted\">(클립 상대 시각)</span></dd>"
            f"<dt>관찰</dt><dd>{e(event['observation'])}</dd><dt>확인 이유</dt><dd>{e(event['reason_for_review'])}</dd>"
            f"<dt>사람이 확인할 사항</dt><dd>{e(event['suggested_human_check'])}</dd>"
            f"<dt>판단의 한계</dt><dd>{e(event.get('uncertainty') or '모델이 별도 불확실성을 밝히지 않았습니다.')} {e(temporal)} {e(event.get('evidence_note') or '')}</dd>"
            f"<dt>위치</dt><dd>{e(where)}</dd></dl><div class=\"shots\">{''.join(shots)}</div>"
            f"<p>{links}</p></article>")


def write_report(qa: QaDir) -> Path:
    manifest = store.read_json_safe(qa.manifest)
    findings = store.read_json_safe(qa.findings)
    if not manifest or not findings:
        raise ValueError("manifest.json / findings.json is required to render the report")
    errors, _ = read_jsonl(qa.errors)
    document = render_report(manifest, findings, qa.read_state(), errors, store.read_json_safe(qa.summary))
    temporary = qa.report.with_name(qa.report.name + ".tmp")
    temporary.write_text(document, encoding="utf-8")
    temporary.replace(qa.report)
    return qa.report
