"""Read-only reviews of completed work. Model prose never establishes verification."""
from __future__ import annotations

from pathlib import Path
from datetime import datetime

from orchestrator.blackmagician.review import MEDIA, build_review, file_evidence, read_object


def finding(code, evidence, cause, action, *, file=None):
    return dict(code=code, file=file, evidence=evidence, cause=cause, action=action)


def result(summary, findings, **extra):
    return dict(status='review_needed' if findings else 'verified', summary=summary,
                findings=findings, **extra)


def manifest_for(folder, done):
    path = folder / 'blackmagician/manifest.json'
    if not path.is_file():
        path = Path((done.get('reports') or {}).get('manifest_json') or str(path))
    return path, read_object(path)


def copy_review(folder):
    done = read_object(folder / 'events/datamanager.done.json')
    request = read_object(folder / 'request.json')
    path, manifest = manifest_for(folder, done)
    issues, files = [], []
    if (not done.get('job_id') or manifest.get('job_id') != done['job_id']
            or not isinstance(manifest.get('files'), list)):
        return result('이 카드의 복제 파일 목록을 확인할 수 없습니다.', [finding(
            'manifest_missing', str(path), '완료 기록과 연결되는 파일별 manifest가 없습니다.',
            '이 작업의 manifest를 복구한 뒤 다시 검토하세요. 다른 카드의 보고서로 대체하지 마세요.')])
    items = manifest['files']
    if not items or len(items) != done.get('file_count'):
        issues.append(finding('file_count', f"완료 {done.get('file_count')}개 / manifest {len(items)}개",
            '완료 기록과 파일 목록이 불일치하거나 비어 있습니다.', '원본 목록과 해당 작업의 manifest를 확인하세요.'))
    expected_roots = [str((Path(p) / request.get('project_name', '')).resolve())
                      for p in request.get('replica_roots', [])]
    actual_roots = done.get('replica_project_roots') or {}
    actual = [str(Path(actual_roots[k]).resolve()) for k in sorted(actual_roots)]
    if (not expected_roots or sorted(expected_roots) != sorted(actual)
            or len(set(actual)) != len(actual)):
        issues.append(finding('destinations', str(actual), '실행 요청의 복제 위치와 완료 기록이 일치하지 않습니다.',
            '승인했던 모든 복제 위치에 이 카드가 있는지 확인하세요.'))
    ids, names, destinations = set(), set(), set()
    for item in items:
        if not isinstance(item, dict):
            issues.append(finding('invalid_file', str(path), '파일 기록 형식이 잘못되었습니다.', 'manifest를 복구하고 다시 검토하세요.'))
            continue
        name, fid = item.get('source_relpath'), item.get('file_id')
        source_key = (item.get('source_path_id'), name)
        if (not isinstance(name, str) or not name or Path(name).is_absolute() or '..' in Path(name).parts
                or not fid or fid in ids or source_key in names or item.get('job_id') != done['job_id']):
            issues.append(finding('file_identity', str(path), '파일 식별자가 누락·중복되었거나 다른 작업의 기록입니다.',
                '이 작업의 원본 파일별 기록을 확인하세요.', file=name))
            continue
        ids.add(fid)
        names.add(source_key)
        try:
            status, reason, evidence = file_evidence(item, done, request, folder)
        except (TypeError, ValueError, KeyError, AttributeError, OSError):
            status, reason, evidence = 'unverified', '파일별 체크섬 또는 복제 기록 형식이 잘못되었습니다.', {}
        for replica in evidence.get('replicas', []):
            target = str(Path(replica['path']).resolve())
            if target in destinations:
                status, reason = 'unverified', '서로 다른 파일이 같은 복제 경로를 가리킵니다.'
            destinations.add(target)
        files.append(dict(file=name, status=status, reason=reason, evidence=evidence))
        if status != 'verified':
            issues.append(finding('copy_' + status, reason,
                '파일 접근 불가 또는 복제 검증 근거 불일치입니다. 이 기록만으로 매체 고장을 단정할 수 없습니다.',
                '원본을 보존하고 해당 복제 볼륨·파일을 확인한 뒤 체크섬을 다시 검증하세요.', file=name))
    verified = sum(f['status'] == 'verified' for f in files)
    return result(f'복제 파일 {len(items)}개 중 {verified}개의 완료 체크섬과 현재 파일 존재·크기를 확인했습니다.',
        issues, counts=dict(total=len(items), verified=verified), files=files,
        limitations=['복제 완료 시점의 체크섬을 재검토합니다. 이번 검토는 전체 파일을 다시 해시하지 않습니다.',
                      '복사 엔진이 기록한 원본 목록을 검토하며 원본 카드 전체를 다시 스캔하지 않습니다.'])


def diagnose(status, messages):
    value = (status + ' ' + ' '.join(str(m) for m in messages)).lower()
    if any(x in value for x in ('dependency_missing', 'not found', 'not configured', 'sdk', 'adapter unavailable')):
        return ('디코더·SDK 또는 실행 도구 누락 가능성이 있습니다.',
                '보고서의 adapter를 확인하고 해당 SDK/도구 설치와 경로 설정 후 검수를 다시 실행하세요.')
    if any(x in value for x in ('permission', 'denied', 'no space', 'read-only', 'output_write')):
        return ('저장 위치의 권한·여유 공간 또는 볼륨 접근 문제일 수 있습니다.',
                '보고서 저장 볼륨의 연결·권한·여유 공간을 확인하고 보고서를 다시 생성하세요.')
    if 'timeout' in value or 'timed out' in value:
        return ('디코더 응답 지연 또는 저장장치 읽기 지연 가능성이 있습니다.',
                '해당 파일을 로컬 디스크와 제조사 재생 도구에서 확인하고 검수를 다시 실행하세요.')
    if any(x in value for x in ('decode', 'probe', 'invalid data', 'unsupported')):
        return ('코덱 지원·디코더 문제 또는 원본 미디어 손상 가능성이 있습니다. 보고서만으로 확정할 수 없습니다.',
                '원본과 모든 복제본의 체크섬을 확인하고 제조사 플레이어에서 같은 프레임을 재생해 비교하세요.')
    if any(x in value for x in ('metadata', 'timecode', 'fps')):
        return ('메타데이터 누락 또는 디코더가 제공하는 정보의 제한일 수 있습니다.',
                '카메라 원본 메타데이터와 촬영 기록에서 FPS·타임코드를 확인하세요.')
    return ('보고서만으로 원인을 확정하기 어렵습니다.',
            '표시된 파일·프레임과 오류 메시지를 확인하고 해당 파일만 재검수하세요. 원본은 보존하세요.')


def report_review(folder):
    done = read_object(folder / 'events/datahelper.done.json')
    dm = read_object(folder / 'events/datamanager.done.json')
    reports = done.get('reports') or []
    issues, reviewed, inventories = [], 0, []
    _, manifest = manifest_for(folder, dm)
    if done.get('error'):
        cause, action = diagnose(str(done.get('status', '')), [done['error']])
        issues.append(finding('helper_error', str(done['error']), cause, action))
    expected_labels = set((dm.get('replica_project_roots') or {}).keys())
    labels = [r.get('label') for r in reports if isinstance(r, dict)]
    if not reports or set(labels) != expected_labels or len(labels) != len(set(labels)):
        issues.append(finding('report_set', str(folder / 'events/datahelper.done.json'),
            '복제 위치별 보고서가 누락되었거나 중복되었습니다.', '각 복제 위치의 검수 보고서를 다시 생성하세요.'))
    for report in reports:
        if not isinstance(report, dict):
            continue
        label = str(report.get('label', '?'))
        if report.get('status') != 'completed' or report.get('exit_code') != 0 or report.get('missing_artifacts'):
            messages = [report.get('stderr', ''), report.get('stdout', '')]
            cause, action = diagnose(str(report.get('status', '')), messages)
            issues.append(finding('report_process', f"{label}: {report.get('status')} / {str(messages[0])[:2000]}", cause, action))
        # New runs snapshot structured reports before publishing completion. Never
        # silently fall back to a project-wide report if that snapshot is missing.
        value = report.get('review_json_path') or report.get('json_path')
        path = Path(value) if isinstance(value, str) and value else folder / 'missing-report'
        data = {} if report.get('review_snapshot_error') else read_object(path)
        clips, summary = data.get('clips'), data.get('summary') or {}
        if not isinstance(clips, list) or not clips or summary.get('total_clips') != len(clips):
            issues.append(finding('report_content', str(path), '구조화 보고서가 없거나 클립 수와 요약이 일치하지 않습니다.',
                '해당 카드의 JSON·PDF 보고서를 다시 생성하세요.'))
            continue
        reviewed += 1
        inventory = []
        input_root = Path(report.get('input_path') or '/__unknown__').resolve()
        for clip in clips:
            if not isinstance(clip, dict) or not isinstance(clip.get('clip'), dict):
                issues.append(finding('clip_schema', str(path), '클립 보고서 형식이 잘못되었습니다.', '검수 보고서를 다시 생성하세요.'))
                continue
            name = clip['clip'].get('clip_name') or clip['clip'].get('source_path')
            source = Path(clip['clip'].get('source_path') or '/__unknown__').resolve()
            if not source.is_relative_to(input_root):
                issues.append(finding('report_identity', str(path), '보고서가 이 카드의 입력 위치를 벗어난 파일을 참조합니다.',
                    '다른 카드의 보고서인지 확인하고 해당 카드로 다시 생성하세요.', file=name))
            else:
                inventory.append(str(source.relative_to(input_root)))
            points = [clip, *(clip.get('captures') or [])]
            for point in points:
                status = str(point.get('status', 'unknown'))
                messages = [*(point.get('errors') or []), *(point.get('warnings') or [])]
                if status != 'success' or messages:
                    cause, action = diagnose(status, messages)
                    issues.append(finding('media_' + status,
                        f"{label} / {point.get('label', '클립')}: {status}; " + '; '.join(map(str, messages)),
                        cause, action, file=name))
            if clip.get('status') == 'success' and not clip.get('captures'):
                issues.append(finding('capture_missing', str(path), '성공으로 기록됐지만 프레임 검수 결과가 없습니다.',
                    '해당 클립의 시작·중간·끝 프레임을 다시 검수하세요.', file=name))
        inventories.append(sorted(inventory))
        # These formats are one physical file per logical clip. Segmented RAW
        # formats are grouped by DataHelper, so do not compare their raw counts.
        single_file = {'.mov', '.mp4', '.mxf', '.braw'}
        expected_paths = set()
        for item in manifest.get('files', []):
            if not isinstance(item, dict) or Path(item.get('source_relpath', '')).suffix.lower() not in single_file:
                continue
            for replica in item.get('replica_results', []):
                root = (dm.get('replica_project_roots') or {}).get(label)
                if root:
                    dest = (Path(root) / replica.get('dest_relpath', '')).resolve()
                    if dest.is_relative_to(input_root):
                        expected_paths.add(str(dest.relative_to(input_root)))
        missing = expected_paths - set(inventory)
        for name in sorted(missing):
            issues.append(finding('unreviewed_clip', str(path), '복제 목록에 있지만 보고서에 없는 클립입니다.',
                '검수 입력 범위와 지원 형식을 확인한 뒤 이 클립을 검수하세요.', file=name))
        if summary.get('success_count') != sum(c.get('status') == 'success' for c in clips if isinstance(c, dict)):
            issues.append(finding('summary_count', str(path), '성공 클립 수와 상세 결과가 다릅니다.', '보고서를 다시 생성하세요.'))
        if summary.get('status') != 'success' or any(summary.get(k, 0) for k in (
                'partial_success_count', 'probe_failed_count', 'decode_failed_count', 'skipped_count')):
            issues.append(finding('report_summary', str(path), '보고서 요약에 실패·부분 성공·건너뜀 기록이 있습니다.',
                '해당 클립의 상세 오류와 프레임을 확인하세요.'))
    if inventories and any(i != inventories[0] for i in inventories):
        issues.append(finding('replica_report_difference', '복제본별 클립 목록 불일치',
            '복제본마다 검수한 클립 범위가 다릅니다.', '누락된 클립과 검수 입력 범위를 확인하세요.'))
    if done.get('status') != 'completed' and not issues:
        issues.append(finding('helper_incomplete', str(folder / 'events/datahelper.done.json'),
            'DataHelper 정상 종료가 확인되지 않았습니다.', '작업 오류를 확인하고 검수를 다시 실행하세요.'))
    return result(f'검수 보고서 {reviewed}개를 읽고 확인할 항목 {len(issues)}개를 찾았습니다.', issues,
                  counts=dict(reports=reviewed, findings=len(issues)),
                  limitations=['PDF와 함께 생성된 JSON의 클립·프레임·오류를 검토합니다. 영상 전체 재생 검수는 아닙니다.'])


def reel_review(folder, record, public):
    snapshot, connection = public.get('snapshot') or {}, public.get('connection')
    if not connection:
        return dict(status='skipped', summary='Blackmagician이 연결되지 않아 촬영 기록 대조를 건너뛰었습니다.', findings=[])
    dm = read_object(folder / 'events/datamanager.done.json')
    _, manifest = manifest_for(folder, dm)
    names = {Path(f['source_relpath']).name for f in manifest.get('files', []) if isinstance(f, dict) and isinstance(f.get('source_relpath'), str)}
    names |= {Path(n).stem for n in list(names) if Path(n).suffix.lower() in MEDIA}
    entries = snapshot.get('entries') or []
    def timestamp(value):
        try:
            if isinstance(value, (int, float)):
                return value / 1000  # Blackmagician Date / Firestore epoch milliseconds.
            return datetime.fromisoformat(value.replace('Z', '+00:00')).timestamp()
        except (ValueError, AttributeError, TypeError):
            return None
    cutoff = timestamp(dm.get('finished_at'))
    later = [e for e in entries if cutoff is not None and timestamp(e['data'].get('createdAt')) is not None
             and timestamp(e['data']['createdAt']) > cutoff]
    entries = [e for e in entries if e not in later]
    # A local R#n is an ingest counter, not a camera reel. Infer a scope only
    # from matching historical clips; never borrow the current camera settings.
    keys = ('shootDayKey', 'cameraId', 'reel')
    anchors = [e for e in entries if e['data'].get('clipName') in names
               and e['data'].get('cameraId') == record.get('camera_unit')
               and str(e['data'].get('shootDayKey', '')).replace('-', '') == str(record.get('shoot_date', '')).replace('-', '')]
    scopes = {tuple(str(e['data'].get(k) or '') for k in keys) for e in anchors}
    if len(scopes) != 1 or not all(next(iter(scopes), ())):
        return result('이 카드에 해당하는 촬영일·카메라·릴을 확정할 수 없습니다.', [finding(
            'reel_scope', f'일치하는 범위 {len(scopes)}개', '촬영 기록의 식별 정보가 부족하거나 클립명이 여러 릴에 중복됩니다.',
            'Blackmagician에서 이 카드의 clipName·shootDayKey·cameraId·reel을 확인하고 동기화한 뒤 다시 검토하세요.')])
    scope = next(iter(scopes))
    selected = [e for e in entries if tuple(str(e['data'].get(k) or '') for k in keys) == scope]
    scoped = {**snapshot, 'entries': selected}
    review = build_review(scoped, connection, [record], folder.parent, record['project_id'])
    issues = [finding('shooting_' + c['status'], c['reason'], '촬영 기록과 이 카드의 복제 파일 근거가 일치하지 않습니다.',
        '해당 릴의 원본 파일명과 복제 위치를 확인하세요. 다른 카드에 백업했다면 그 작업 기록을 확인하세요.', file=c['clip_name'])
        for c in review['clips'] if c['status'] != 'verified']
    issues.extend(finding('shooting_evidence', i['reason'], '복제 파일 근거가 부족합니다.', '복제 검토 결과를 먼저 확인하세요.') for i in review['issues'])
    if review['status'] != 'verified' and not issues:
        issues.append(finding('shooting_freshness', review['summary'], '최신의 완전한 촬영 기록 또는 백업 검증이 확인되지 않았습니다.',
            'Blackmagician을 다시 동기화하고 복제 검토 결과를 확인하세요.'))
    uncertain = [e for e in entries if any(not e['data'].get(k) for k in keys)
                 and all(not e['data'].get(k) or str(e['data'][k]) == value for k, value in zip(keys, scope))]
    if uncertain:
        issues.append(finding('shooting_scope_incomplete', f'범위를 확인할 수 없는 촬영 기록 {len(uncertain)}개',
            '촬영일·카메라·릴 정보가 빠져 같은 릴의 촬영인지 배제할 수 없습니다.',
            '누락된 촬영 식별 정보를 확인하고 다시 동기화하세요.'))
    return result(review['summary'], issues, counts=review['counts'], clips=review['clips'],
        scope=dict(zip(keys, scope)), connection=review['connection'], snapshot_at=review['session_snapshot_at'],
        excluded_after_completion=len(later),
        limitations=review['limitations'] + ['해당 스냅샷에 기록된 릴 범위만 검토합니다. 완료 후 생성된 기록과 기록되지 않은 촬영은 포함하지 않습니다.',
            '촬영 기록 생성 시각은 녹화 시작 시각이 아닙니다. 릴 번호는 물리 카드의 고유 ID가 아니므로 재사용 여부를 확인하세요.'])
