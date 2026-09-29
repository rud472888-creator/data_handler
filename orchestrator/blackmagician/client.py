from __future__ import annotations

import json
import os
import re
import time
from datetime import datetime, timezone
from urllib.parse import quote

import httpx

FIRESTORE = 'https://firestore.googleapis.com/v1/projects/black-magician-2bc98/databases/(default)/documents'
WEB_API = 'https://blackmagician-web.vercel.app'


class IntegrationError(ValueError):
    def __init__(self, message, status=400, matches=None):
        super().__init__(message)
        self.status, self.matches = status, matches or []


def document_id(value):
    value = str(value).strip()
    if not value or value in {'.', '..'} or re.search(r'[/\x00-\x1f\x7f]', value) or len(value.encode()) > 1500:
        raise IntegrationError('세션 또는 프로젝트 ID가 올바르지 않습니다.')
    return value


def firestore_value(value):
    if 'nullValue' in value:
        return None
    for name in ('stringValue', 'booleanValue', 'timestampValue', 'referenceValue', 'bytesValue', 'geoPointValue'):
        if name in value:
            return value[name]
    if 'integerValue' in value:
        return int(value['integerValue'])
    if 'doubleValue' in value:
        number = value['doubleValue']
        # Preserve Firestore's non-finite string representation as JSON-safe data.
        return number if isinstance(number, str) else float(number)
    if 'arrayValue' in value:
        return [firestore_value(v) for v in value['arrayValue'].get('values', [])]
    if 'mapValue' in value:
        return {k: firestore_value(v) for k, v in value['mapValue'].get('fields', {}).items()}
    raise IntegrationError('지원하지 않는 Firestore 데이터 타입입니다.', 502)


def decode_document(doc):
    return {'path': doc['name'].split('/documents/', 1)[-1],
            'data': {k: firestore_value(v) for k, v in doc.get('fields', {}).items()},
            'create_time': doc.get('createTime'), 'update_time': doc.get('updateTime')}


def entry_sort(entry):
    value = entry['data'].get('createdAt')
    try:
        stamp = float(value) if isinstance(value, (int, float)) else datetime.fromisoformat(value.replace('Z', '+00:00')).timestamp() * 1000
    except (ValueError, TypeError, AttributeError):
        stamp = float('-inf')
    return stamp, entry['paths'][0].rsplit('/', 1)[-1]


def merge_entries(documents, project_id, session_id):
    merged = {}
    # Prefer project history while retaining every raw document and conflicting field.
    for doc in sorted(documents, key=lambda d: ('/takeRecords/' not in d['path'], d['path'])):
        data, path = doc['data'], doc['path']
        identity = data.get('takeId') or path.rsplit('/', 1)[-1]
        key = f'{project_id}/{session_id}/{identity}'
        if key not in merged:
            merged[key] = {'key': key, 'data': data, 'paths': [path], 'conflicts': []}
        else:
            item = merged[key]
            item['paths'].append(path)
            for field in sorted(set(item['data']) | set(data)):
                if (field in item['data']) != (field in data) or item['data'].get(field) != data.get(field):
                    item['conflicts'].append({'field': field, 'path': path,
                        'preferred_present': field in item['data'], 'other_present': field in data,
                        'preferred': item['data'].get(field), 'other': data.get(field)})
    return sorted(merged.values(), key=entry_sort)


class BlackmagicianClient:
    def __init__(self, *, firestore_url=FIRESTORE, api_url=WEB_API, transport=None):
        if os.environ.get('DATA_HANDLER_BLACKMAGICIAN_SANDBOX') == '1':
            firestore_url = 'http://127.0.0.1:8299/v1/projects/demo-datahandler-blackmagician/databases/(default)/documents'
            api_url = 'http://127.0.0.1:8899'
        self.firestore_url, self.api_url = firestore_url.rstrip('/'), api_url.rstrip('/')
        self.http = httpx.Client(timeout=httpx.Timeout(20, connect=8), trust_env=False,
                                 follow_redirects=False, transport=transport)

    def close(self):
        self.http.close()

    @staticmethod
    def check(response, *, missing=False):
        if response.status_code == 404 and missing:
            return None
        if response.is_error or response.is_redirect:
            messages = {401: '접속 자격이 만료되었습니다. 초대 코드로 다시 연결해 주세요.',
                403: 'Blackmagician 읽기 권한이 없습니다. Firestore 규칙 또는 접속 권한을 확인하세요.',
                404: '세션 또는 접속 코드를 찾을 수 없습니다.',
                410: '만료·소진된 코드이거나 종료된 세션입니다. 새 코드 또는 세션 ID를 사용하세요.',
                429: '접속 요청이 너무 많습니다. 다음 분에 다시 시도하세요.'}
            raise IntegrationError(messages.get(response.status_code, 'Blackmagician 서버 요청에 실패했습니다.'),
                                   response.status_code if response.status_code >= 400 else 502)
        return response

    def get_document(self, path):
        response = self.check(self.http.get(self.firestore_url + '/' + '/'.join(quote(p, safe='') for p in path.split('/'))), missing=True)
        return decode_document(response.json()) if response is not None else None

    def list_documents(self, path):
        result, seen, token = [], set(), None
        while True:
            params = {'pageSize': 100}
            if token:
                params['pageToken'] = token
            response = self.check(self.http.get(self.firestore_url + '/' + '/'.join(quote(p, safe='') for p in path.split('/')), params=params))
            data = response.json()
            result.extend(decode_document(d) for d in data.get('documents', []))
            token = data.get('nextPageToken')
            if not token:
                return result
            if token in seen:
                raise IntegrationError('Firestore 페이지 응답이 반복됩니다.', 502)
            seen.add(token)

    def resolve(self, session_id, project_id=None):
        session_id = document_id(session_id)
        if project_id:
            project_id = document_id(project_id)
            if self.get_document(f'projects/{project_id}/sessions/{session_id}') is None:
                raise IntegrationError('해당 프로젝트에 세션이 없습니다.', 404)
            return project_id, session_id
        matches = []
        for project in self.list_documents('projects'):
            pid = project['path'].rsplit('/', 1)[-1]
            if self.get_document(f'projects/{pid}/sessions/{session_id}') is not None:
                matches.append({'project_id': pid, 'session_id': session_id})
        if not matches:
            raise IntegrationError('세션을 찾을 수 없습니다. 프로젝트 ID를 알고 있다면 함께 입력하세요.', 404)
        if len(matches) != 1:
            raise IntegrationError('동일한 세션 ID가 있습니다. 프로젝트를 선택하세요.', 409, matches)
        return matches[0]['project_id'], session_id

    def join(self, code):
        code = re.sub(r'[\s-]', '', code).upper()
        if not re.fullmatch('[A-Z0-9]{8}', code):
            raise IntegrationError('초대 코드는 8자리 영문·숫자입니다.')
        result = self.check(self.http.post(self.api_url + '/api/join', json={'code': code})).json()
        return {'project_id': document_id(result['projectId']), 'session_id': document_id(result['sessionId']),
                'token': result['token'], 'expires_at': result['expiresAt'],
                # The local server only sends the bearer token to the configured API origin.
                'events_url': self.api_url + '/api/events'}

    def leave(self, connection):
        if connection.get('token'):
            response = self.http.post(self.api_url + '/api/leave', headers={'Authorization': 'Bearer ' + connection['token']})
            if response.status_code != 401:
                self.check(response)

    def snapshot(self, connection):
        pid, sid = connection['project_id'], connection['session_id']
        root, session = f'projects/{pid}', f'projects/{pid}/sessions/{sid}'
        if connection['mode'] == 'invite':
            data = self.web_snapshot(connection)
            docs = [{'path': f'{session}/scriptEntries/{d["id"]}', 'data': {k: v for k, v in d.items() if k != 'id'}} for d in data['entries']]
            camera, script, access = data['camera'], data['script'], data['access']
            raw = docs
        else:
            camera_doc = self.get_document(session)
            if camera_doc is None:
                raise IntegrationError('연결된 세션 문서가 없습니다.', 404)
            script_doc = self.get_document(session + '/script/state')
            access_doc = self.get_document(root + '/sessionAccess/' + sid)
            docs = self.list_documents(session + '/scriptEntries')
            # List and filter supports the documented no-new-index baseline, including pagination.
            docs += [d for d in self.list_documents(root + '/takeRecords') if d['data'].get('sessionId') == sid]
            camera, script = camera_doc['data'], script_doc['data'] if script_doc else None
            access = {'exists': access_doc is not None, 'sessionActive': access_doc['data'].get('sessionActive') if access_doc else None}
            raw = [d for d in [camera_doc, script_doc] if d] + docs
        entries = merge_entries(docs, pid, sid)
        return {'camera': camera, 'script': script, 'access': access, 'entries': entries,
                'raw_documents': {d['path']: d for d in raw}, 'complete': True, 'from_cache': False,
                'conflicts': [{'key': e['key'], 'differences': e['conflicts']} for e in entries if e['conflicts']],
                'fetched_at': datetime.now(timezone.utc).isoformat(),
                'scope': 'session_entries' if connection['mode'] == 'invite' else 'session_and_durable_entries',
                'display_fps': {2398: 23.98, 2997: 29.97, 5994: 59.94}.get((camera or {}).get('fps'), (camera or {}).get('fps'))}

    def web_snapshot(self, connection):
        # Each explicit sync obtains a complete initial snapshot, then closes the stream.
        # EOF before initialization reconnects; partial lists are never published.
        required = {'camera', 'script', 'entries', 'access'}
        for attempt in range(3):
            result, started = {}, time.monotonic()
            with self.http.stream('GET', connection.get('events_url', self.api_url + '/api/events'),
                    headers={'Authorization': 'Bearer ' + connection['token']}) as response:
                self.check(response)
                for line in response.iter_lines():
                    if time.monotonic() - started > 25:
                        break
                    if not line.strip():
                        continue
                    if len(line) > 16 * 1024 * 1024:
                        raise IntegrationError('세션 응답 크기 제한을 초과했습니다.', 502)
                    event = json.loads(line)
                    kind = event.get('type')
                    if kind == 'error':
                        raise IntegrationError('Blackmagician 스트림이 오류로 종료되었습니다. 다시 동기화해 주세요.', 502)
                    if kind in required:
                        result[kind] = event.get('data')
                    if required <= result.keys():
                        if not isinstance(result['entries'], list):
                            raise IntegrationError('촬영 기록 응답 형식이 올바르지 않습니다.', 502)
                        return result
            if attempt < 2:
                time.sleep(0.5 * (2 ** attempt))
        raise IntegrationError('전체 세션 정보를 받지 못했습니다. 다시 동기화해 주세요.', 502)

    def watch(self, connection, stopped):
        """The existing API sends full collection replacements as NDJSON, not SSE.

        Start every connection with a new initialization barrier. Never combine a
        partial reconnect with an old collection (which could resurrect deletes).
        None is a transport heartbeat, not a new camera observation.
        """
        required = {'camera', 'script', 'entries', 'access'}
        data = {}
        with self.http.stream('GET', self.api_url + '/api/events',
                headers={'Authorization': 'Bearer ' + connection['token']}) as response:
            self.check(response)
            started = time.monotonic()
            for line in response.iter_lines():
                if stopped.is_set():
                    return
                if not required <= data.keys() and time.monotonic() - started > 30:
                    raise IntegrationError('초기 촬영 정보를 모두 받지 못했습니다.', 502)
                if not line.strip():
                    continue
                if len(line) > 16 * 1024 * 1024:
                    raise IntegrationError('세션 응답 크기 제한을 초과했습니다.', 502)
                event = json.loads(line)
                kind, value = event.get('type'), event.get('data')
                if kind == 'error':
                    raise IntegrationError('촬영 스트림이 중단되었습니다. 다시 연결합니다.', 502)
                if kind == 'heartbeat':
                    if required <= data.keys():
                        yield None
                    continue
                if kind not in required:
                    continue
                if kind == 'entries':
                    if not isinstance(value, list) or any(not isinstance(e, dict) or not e.get('id') for e in value):
                        raise IntegrationError('촬영 기록 응답 형식이 올바르지 않습니다.', 502)
                elif value is not None and not isinstance(value, dict):
                    raise IntegrationError('촬영 상태 응답 형식이 올바르지 않습니다.', 502)
                if kind == 'camera' and value is None or kind == 'access' and (value or {}).get('exists') is False:
                    raise IntegrationError('연결된 촬영 세션이 삭제되었습니다. 세션을 다시 확인하세요.', 404)
                data[kind] = value
                if required <= data.keys():
                    pid, sid = connection['project_id'], connection['session_id']
                    docs = [{'path': f'projects/{pid}/sessions/{sid}/scriptEntries/{e["id"]}',
                             'data': {k: v for k, v in e.items() if k != 'id'}} for e in data['entries']]
                    entries = merge_entries(docs, pid, sid)
                    yield {'camera': data['camera'], 'script': data['script'], 'access': data['access'],
                           'entries': entries, 'raw_documents': {d['path']: d for d in docs},
                           'conflicts': [], 'complete': True, 'from_cache': False,
                           'scope': 'session_entries', 'fetched_at': datetime.now(timezone.utc).isoformat(),
                           'display_fps': {2398: 23.98, 2997: 29.97, 5994: 59.94}.get(
                               (data['camera'] or {}).get('fps'), (data['camera'] or {}).get('fps'))}
        if not stopped.is_set():
            raise IntegrationError('촬영 스트림 연결이 종료되었습니다. 다시 연결합니다.', 502)
