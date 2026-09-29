"""Match session clip names to durable, file-level replication evidence.

This does not read copy-engine progress or extrapolate capture settings to old takes.
Checksums describe verification at completion, not a fresh disk-wide hash scan.
"""
from __future__ import annotations

import re
from collections import Counter
from pathlib import Path

from orchestrator.jsonio import read_json
from orchestrator.run_state import utc_now

MEDIA = {'.braw', '.r3d', '.mov', '.mp4', '.mxf', '.ari', '.arx', '.crm', '.cine', '.wav', '.aif', '.aiff'}
HASH = re.compile(r'^[a-fA-F0-9]{64}$')


def read_object(path):
    try:
        data = read_json(path)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def file_evidence(item, done, request, folder):
    expected = done.get('replica_path_ids', [])
    roots = done.get('replica_project_roots', {})
    replicas = item.get('replica_results') or []
    evidence = {'run_id': folder.name, 'file_id': item.get('file_id'),
                'source_relpath': item.get('source_relpath'), 'checksum_source': item.get('checksum_source'),
                'verified_at': done.get('finished_at'), 'completion_artifact': str(folder / 'events/datamanager.done.json'),
                'replicas': []}
    if (not isinstance(replicas, list) or any(not isinstance(r, dict) for r in replicas)
            or len(replicas) != len(expected) or type(item.get('size_bytes')) is not int
            or item['size_bytes'] < 0):
        return 'unverified', '복제본 개수 또는 파일 크기 기록이 올바르지 않습니다.', evidence
    if not HASH.fullmatch(str(item.get('checksum_source', ''))):
        return 'unverified', '원본 체크섬 근거가 없습니다.', evidence
    if len(expected) < 1 or len(set(expected)) != len(expected) or len(expected) != done.get('replica_count'):
        return 'unverified', '지정한 모든 백업 경로(1개 이상)에 대한 검증 근거가 필요합니다.', evidence
    if request.get('replica_roots'):
        approved = [str((Path(p) / request.get('project_name', '')).resolve()) for p in request['replica_roots']]
        actual = [str(Path(roots.get(f'path{i + 1}', '')).resolve()) for i in range(len(expected))]
        if approved != actual or len(set(actual)) != len(actual):
            return 'unverified', '실행 요청의 복제 위치와 검증 기록이 일치하지 않습니다.', evidence
    if done.get('status') != 'completed' or done.get('replicas_complete') is not True or item.get('status') != 'verified':
        return 'unverified', '복제 완료 또는 파일 검증이 확인되지 않았습니다.', evidence
    for i, path_id in enumerate(expected):
        matches = [r for r in replicas if r.get('path_id') == path_id]
        if len(matches) != 1:
            return 'unverified', '복제본별 검증 기록이 누락되거나 중복되었습니다.', evidence
        replica = matches[0]
        rel = Path(replica.get('dest_relpath') or '')
        root = roots.get(f'path{i + 1}')
        if not root or str(rel) == '.' or rel.is_absolute() or '..' in rel.parts:
            return 'unverified', '복제본 경로 근거가 올바르지 않습니다.', evidence
        destination = Path(root) / rel
        if not destination.resolve().is_relative_to(Path(root).resolve()):
            return 'unverified', '복제본 경로가 기록된 프로젝트를 벗어납니다.', evidence
        valid = replica.get('status') == 'verified' and HASH.fullmatch(str(replica.get('checksum', ''))) and replica['checksum'].lower() == item['checksum_source'].lower()
        evidence['replicas'].append({'path': str(destination), 'checksum': replica.get('checksum'), 'status': replica.get('status')})
        if not valid:
            return 'unverified', '복제본 체크섬이 원본과 일치하지 않습니다.', evidence
        try:
            if not destination.is_file() or destination.stat().st_size != item.get('size_bytes'):
                return 'unavailable', '현재 복제본 파일이 없거나 크기가 달라졌습니다. 볼륨과 파일을 확인하세요.', evidence
        except OSError:
            return 'unavailable', '복제본 볼륨 또는 파일에 접근할 수 없습니다.', evidence
    return 'verified', '완료 시점 원본·복제본 체크섬 일치, 현재 파일 존재·크기 확인.', evidence


def build_review(snapshot, connection, records, runs_root, local_project_id):
    files, issues = [], []
    for record in records:
        if record.get('project_id') != local_project_id:
            continue
        run_id = str(record.get('run_id', ''))
        if not run_id or Path(run_id).name != run_id or run_id in {'.', '..'}:
            continue
        folder = runs_root / run_id
        done = read_object(folder / 'events/datamanager.done.json')
        if not done:
            issues.append({'run_id': run_id, 'reason': '복제 완료 artifact 없음'})
            continue
        request = read_object(folder / 'request.json')
        manifest_path = folder / 'blackmagician/manifest.json'
        if not manifest_path.is_file():
            manifest_path = Path(done.get('reports', {}).get('manifest_json') or str(manifest_path))
        manifest = read_object(manifest_path)
        if not done.get('job_id') or manifest.get('job_id') != done['job_id'] or not isinstance(manifest.get('files'), list):
            issues.append({'run_id': run_id, 'reason': '이 작업에 속하는 파일 manifest 없음 (다른 카드의 manifest로 대체하지 않음)'})
            continue
        if len(manifest['files']) != done.get('file_count'):
            issues.append({'run_id': run_id, 'reason': '완료 파일 수와 manifest 수가 다름'})
            continue
        for item in manifest['files']:
            if not isinstance(item, dict) or not isinstance(item.get('source_relpath'), str):
                issues.append({'run_id': run_id, 'reason': '잘못된 파일 기록'})
                continue
            if item.get('job_id') != done['job_id']:
                issues.append({'run_id': run_id, 'reason': '파일이 다른 작업에 속함'})
                continue
            status, reason, evidence = file_evidence(item, done, request, folder)
            evidence['manifest_path'] = str(manifest_path)
            files.append({'item': item, 'status': status, 'reason': reason, 'evidence': evidence,
                          'camera_unit': record.get('camera_unit')})
    entries = (snapshot or {}).get('entries', [])
    names = Counter(e['data'].get('clipName') for e in entries if e['data'].get('clipName'))
    clips, used = [], set()
    for entry in entries:
        data = entry['data']
        name = data.get('clipName')
        clip = {'key': entry['key'], 'clip_name': name or '', 'scene': data.get('scene'),
                'take_result': data.get('takeResult'), 'entry_paths': entry['paths'], 'evidence': []}
        candidates = []
        if isinstance(name, str) and name.strip():
            for index, candidate in enumerate(files):
                path = Path(candidate['item']['source_relpath'])
                if name == path.name or (path.suffix.lower() in MEDIA and name == path.stem):
                    camera = data.get('cameraId')
                    if camera and candidate['camera_unit'] and camera != candidate['camera_unit']:
                        continue
                    candidates.append((index, candidate))
        if entry['conflicts']:
            status, reason = 'conflict', 'Blackmagician의 두 촬영 기록 사본이 다릅니다.'
        elif not name:
            status, reason = 'unknown', '촬영 기록에 파일과 대조할 clipName이 없습니다. clipToken으로 파일명을 추측하지 않습니다.'
        elif len(candidates) > 1 or names[name] > 1:
            status, reason = 'ambiguous', '같은 클립명이 여러 번 나타납니다. 카드·카메라·파일을 직접 확인하세요.'
        elif not candidates:
            status, reason = ('unknown', '완료된 파일 목록이 부족하여 백업 여부를 판단할 수 없습니다.') if issues or not files else ('missing', '이 프로젝트의 완료 파일 목록에 일치하는 클립이 없습니다.')
        else:
            status, reason = candidates[0][1]['status'], candidates[0][1]['reason']
        for index, candidate in candidates:
            used.add(index)
            clip['evidence'].append(candidate['evidence'])
        clips.append({**clip, 'status': status, 'reason': reason})
    counts = dict(Counter(c['status'] for c in clips))
    counts.update(total=len(clips), backup_files=len(files), extra_files=len(files) - len(used))
    counts['verified'] = counts.get('verified', 0)
    counts['unverified_backup_files'] = sum(f['status'] != 'verified' for f in files)
    current = connection and connection.get('status') == 'connected' and snapshot and snapshot.get('complete') and not snapshot.get('from_cache')
    clear = bool(clips) and all(c['status'] == 'verified' for c in clips) and not issues and current and not counts['unverified_backup_files']
    summary = f"촬영 기록 {len(clips)}개 중 {counts['verified']}개가 완료 시점 체크섬 근거와 일치합니다."
    if len(clips) - counts['verified']:
        summary += f" {len(clips) - counts['verified']}개는 확인이 필요합니다."
    if not current:
        summary += ' 저장된 세션 정보입니다. 새로 동기화한 뒤 검토하세요.'
    if not clips:
        summary += ' 촬영 기록이 없어 전체 백업 완료 여부를 판단할 수 없습니다.'
    if counts['unverified_backup_files']:
        summary += f" 백업 파일 {counts['unverified_backup_files']}개의 검증 또는 접근 상태를 확인하세요."
    return {'status': 'verified' if clear else 'review_needed', 'summary': summary, 'counts': counts,
            'clips': clips, 'issues': issues, 'reviewed_at': utc_now(),
            'session_snapshot_at': (snapshot or {}).get('fetched_at'),
            'project_id': local_project_id, 'connection': {k: connection.get(k) for k in ('project_id', 'session_id', 'status')} if connection else None,
            'limitations': ['검토 범위는 이 세션에 기록된 클립입니다. 기록되지 않은 촬영·오디오 파일의 존재는 알 수 없습니다.',
                '체크섬은 복제 완료 당시 기록이며 이번 검토는 파일 존재·크기를 확인합니다. 현재 데이터 전체를 다시 해시하지 않습니다.',
                '현재 카메라 설정을 과거 테이크에 적용하지 않습니다.'],
            'extra_files': [f['evidence'] for i, f in enumerate(files) if i not in used]}


def review_text(review):
    lines = [review['summary']]
    for clip in review['clips'][:80]:
        lines.append(f"{clip['clip_name'] or '(클립명 없음)'}: {clip['reason']}")
    if len(review['clips']) > 80:
        lines.append('나머지 클립은 앱의 전체 검토 결과에서 확인하세요.')
    lines.extend(i['reason'] for i in review['issues'][:8])
    lines.extend(review['limitations'])
    return '\n'.join(lines)
