from __future__ import annotations

from pathlib import Path
from typing import Any

from orchestrator.jsonio import read_json
from orchestrator.run_state import events_dir, load_spec, run_dir, utc_now


def datamanager_message(run_id: str) -> str:
    spec = load_spec(run_id)
    done = read_json(events_dir(run_id) / "datamanager.done.json")
    replica_text = "완료" if done.get("replicas_complete") else "확인 필요"
    return "\n".join(
        [
            f"DataManager 작업 보고: {spec.project_name}",
            f"- run_id: {run_id}",
            f"- 상태: {done.get('status')} / job_state: {done.get('job_state')}",
            f"- 복제 경로 검증: {replica_text}",
            f"- 파일 수: {done.get('file_count')}",
            f"- checksum PDF: {done.get('reports', {}).get('checksum_pdf', '-')}",
            f"- manifest JSON: {done.get('reports', {}).get('manifest_json', '-')}",
        ]
    )


def write_final_report(run_id: str) -> Path:
    spec = load_spec(run_id)
    dm_done = read_json(events_dir(run_id) / "datamanager.done.json")
    dh_done = read_json(events_dir(run_id) / "datahelper.done.json")
    lines = [
        f"# Replication Pipeline Final Report - {spec.project_name}",
        "",
        f"- run_id: `{run_id}`",
        f"- generated_at: `{utc_now()}`",
        "- source_paths:",
        *[f"  - `{path}`" for path in spec.source_paths],
        f"- replica paths: `{', '.join(str(path) for path in spec.replica_roots)}`",
        "",
        "## DataManager",
        "",
        f"- status: `{dm_done.get('status')}`",
        f"- job_id: `{dm_done.get('job_id')}`",
        f"- job_state: `{dm_done.get('job_state')}`",
        f"- replicas_complete: `{dm_done.get('replicas_complete')}`",
        f"- file_count: `{dm_done.get('file_count')}`",
        f"- checksum_pdf: `{dm_done.get('reports', {}).get('checksum_pdf', '-')}`",
        f"- manifest_json: `{dm_done.get('reports', {}).get('manifest_json', '-')}`",
        "",
        "## DataHelper",
        "",
        f"- status: `{dh_done.get('status')}`",
    ]
    for report in _iter_datahelper_reports(dh_done.get("reports", [])):
        lines.extend(_datahelper_report_lines(report))
    final_path = run_dir(run_id) / "final-report.md"
    final_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return final_path


def final_message(run_id: str, report_path: Path) -> str:
    spec = load_spec(run_id)
    return "\n".join(
        [
            f"복제 및 DataHelper 리포트 작업이 종료되었습니다: {spec.project_name}",
            f"- run_id: {run_id}",
            f"- 최종 문서: {report_path}",
        ]
    )


def _datahelper_report_lines(report: dict[str, Any]) -> list[str]:
    label = report.get("label", "unknown")
    return [
        "",
        f"### {label}",
        "",
        f"- input: `{report.get('input_path')}`",
        f"- exit_code: `{report.get('exit_code')}`",
        f"- pdf: `{report.get('pdf_path')}`",
        f"- csv: `{report.get('csv_path')}`",
        f"- json: `{report.get('json_path')}`",
    ]


def _iter_datahelper_reports(reports: Any) -> list[dict[str, Any]]:
    if isinstance(reports, list):
        return [report for report in reports if isinstance(report, dict)]
    if not isinstance(reports, dict):
        return []
    normalized: list[dict[str, Any]] = []
    for label, payload in reports.items():
        if not isinstance(payload, dict):
            continue
        normalized.append(
            {
                "label": label,
                "input_path": payload.get("input_path"),
                "exit_code": payload.get("exit_code"),
                "pdf_path": _legacy_report_path(payload.get("pdf")),
                "csv_path": _legacy_report_path(payload.get("csv")),
                "json_path": _legacy_report_path(payload.get("json")),
            }
        )
    return normalized


def _legacy_report_path(value: Any) -> Any:
    if isinstance(value, dict):
        return value.get("path")
    return value
