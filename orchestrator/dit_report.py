"""Shooting-day DIT report: one PDF that closes the backup-to-report chain.

Only durable completion evidence is summarized. Nothing here re-hashes media or
infers verification that the copy engine did not record.
"""
from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape

from orchestrator.blackmagician.review import read_object
from orchestrator.paths import DATA_MANAGER_ROOT

PHASES = {
    'waiting': '시작 대기', 'copying': '복사·검증 중', 'verified': '검증 완료',
    'reporting': 'PDF 생성 중', 'reported': '작업 완료', 'review': '확인 필요', 'failed': '작업 실패',
}
FONT, BOLD = 'DH-Sans', 'DH-Sans-Bold'


def human_bytes(value: int | None) -> str:
    if value is None:
        return '미기록'
    size = float(value)
    for unit in ('B', 'KB', 'MB', 'GB', 'TB'):
        if size < 1024 or unit == 'TB':
            return f'{size:.0f} {unit}' if unit == 'B' else f'{size:.2f} {unit}'
        size /= 1024
    return f'{value} B'


def report_label(name: str) -> str:
    if 'checksum' in name.lower():
        return '체크섬 검증 PDF'
    match = re.search(r'path(\d+)', name)
    return f'백업 {match.group(1)} 검수 PDF' if match else name


def card_rows(cards: list[dict[str, Any]], runs_root: Path) -> list[dict[str, Any]]:
    rows = []
    for card in cards:
        manifest = read_object(runs_root / str(card['run_id']) / 'blackmagician/manifest.json')
        files = [f for f in manifest.get('files', []) if isinstance(f, dict)]
        size = sum(int(f.get('size_bytes') or 0) for f in files) if files else None
        reviews = card.get('agent_reviews') or []
        rows.append({
            'roll': card.get('roll', ''),
            'camera': card.get('camera_unit', ''),
            'source': card.get('source_path', ''),
            'files': card.get('file_count') if card.get('file_count') is not None else (len(files) or None),
            'bytes': size,
            'verified': bool(card.get('verified')),
            'phase': PHASES.get(str(card.get('phase')), '상태 확인 필요'),
            'destinations': card.get('destinations') or [],
            'findings': sum(int(r.get('finding_count') or 0) for r in reviews),
            'error': card.get('error') or '',
            'reports': [report_label(a['name']) for a in card.get('artifacts', []) if str(a.get('path', '')).endswith('.pdf')],
            'failed_files': card.get('failed_files') or [],
        })
    return rows


def summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    sizes = [r['bytes'] for r in rows if r['bytes'] is not None]
    return {
        'cards': len(rows),
        'files': sum(int(r['files'] or 0) for r in rows),
        'bytes': sum(sizes) if sizes else None,
        'verified': sum(r['verified'] for r in rows),
        'attention': sum(1 for r in rows if not r['verified'] or r['findings'] or r['error']),
        'cameras': sorted({str(r['camera']) for r in rows}),
    }


def _fonts() -> None:
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont

    root = DATA_MANAGER_ROOT / 'app/runtime/fonts'
    for name, weight in ((FONT, 'Regular'), (BOLD, 'Bold')):
        if name not in pdfmetrics.getRegisteredFontNames():
            pdfmetrics.registerFont(TTFont(name, str(root / f'DataHandlerSans-{weight}.ttf')))


def write_day_report(path: Path, *, project: str, shoot_date: str, rows: list[dict[str, Any]]) -> Path:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    _fonts()
    ink, muted, line = colors.HexColor('#172C32'), colors.HexColor('#5F7278'), colors.HexColor('#D9E2E3')
    good, warn = colors.HexColor('#146C66'), colors.HexColor('#B3261E')

    def p(text: Any, size: float = 8.5, *, bold: bool = False, color: Any = ink) -> Paragraph:
        return Paragraph(escape(str(text)).replace('\n', '<br/>'), ParagraphStyle(
            'c', fontName=BOLD if bold else FONT, fontSize=size, leading=size * 1.35,
            textColor=color, wordWrap='CJK'))

    totals = summary(rows)
    story: list[Any] = [
        p('DIT 리포트', 18, bold=True),
        p(f'{project}  ·  촬영일 {shoot_date}', 11, color=muted),
        Spacer(1, 10),
    ]
    overview = [
        [p('카드', bold=True), p('파일', bold=True), p('용량', bold=True), p('체크섬 검증', bold=True),
         p('확인 필요', bold=True), p('카메라', bold=True)],
        [p(totals['cards']), p(totals['files']), p(human_bytes(totals['bytes'])),
         p(f"{totals['verified']} / {totals['cards']}", color=good if totals['verified'] == totals['cards'] else warn),
         p(totals['attention'], color=warn if totals['attention'] else good), p(', '.join(totals['cameras']) or '-')],
    ]
    width = landscape(A4)[0] - 60
    table = Table(overview, colWidths=[width / 6] * 6)
    table.setStyle(TableStyle([('LINEBELOW', (0, 0), (-1, 0), 0.6, line),
                               ('BOX', (0, 0), (-1, -1), 0.6, line), ('VALIGN', (0, 0), (-1, -1), 'TOP')]))
    story += [table, Spacer(1, 14)]
    header = ['카드', '카메라', '원본', '파일', '용량', '체크섬', '상태', '백업 위치', '리포트']
    body = [[p(h, bold=True) for h in header]]
    for r in rows:
        note = r['phase'] + (f"\n검토 항목 {r['findings']}개" if r['findings'] else '')
        if r['error']:
            note += f"\n{str(r['error'])[:200]}"
        if r['failed_files']:
            note += f"\n실패 파일 {len(r['failed_files'])}개"
        body.append([
            p(r['roll'], bold=True), p(r['camera']), p(r['source']), p(r['files'] if r['files'] is not None else '미기록'),
            p(human_bytes(r['bytes'])),
            p('검증 완료' if r['verified'] else '미확인', color=good if r['verified'] else warn),
            p(note, color=ink if r['phase'] in {'작업 완료', '검증 완료'} and not r['findings'] else warn),
            p('\n'.join(f'{i + 1}. {d}' for i, d in enumerate(r['destinations'])) or '-', 7.5),
            p('\n'.join(r['reports']) or '-', 7.5),
        ])
    ratios = [0.06, 0.06, 0.17, 0.05, 0.08, 0.07, 0.11, 0.26, 0.14]
    cards = Table(body, colWidths=[width * r for r in ratios], repeatRows=1)
    cards.setStyle(TableStyle([
        ('LINEBELOW', (0, 0), (-1, -1), 0.4, line), ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#F1F6F5')),
    ]))
    story += [cards, Spacer(1, 12), p(
        f'생성 {datetime.now().astimezone().strftime("%Y-%m-%d %H:%M %Z")} · 체크섬 상태는 복사 엔진의 완료 기록'
        ' (모든 백업의 SHA-256 일치)만으로 표시합니다. 카드별 상세 체크섬·클립 검수는 각 카드 리포트를 확인하세요.',
        7.5, color=muted)]

    def footer(canvas: Any, doc: Any) -> None:
        canvas.setFont(FONT, 7.5)
        canvas.setFillColor(muted)
        canvas.drawRightString(landscape(A4)[0] - 30, 18, f'{project} · {shoot_date} · {doc.page}')

    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix('.tmp.pdf')
    SimpleDocTemplate(str(temporary), pagesize=landscape(A4), leftMargin=30, rightMargin=30,
                      topMargin=28, bottomMargin=32, title=f'DIT 리포트 {project} {shoot_date}',
                      author='Data Handler').build(story, onFirstPage=footer, onLaterPages=footer)
    temporary.replace(path)
    return path
