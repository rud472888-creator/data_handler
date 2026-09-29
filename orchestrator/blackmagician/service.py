from __future__ import annotations

import fcntl
import json
import os
import tempfile
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import httpx

from orchestrator.blackmagician.client import BlackmagicianClient, IntegrationError, document_id
from orchestrator.blackmagician.review import build_review, read_object
from orchestrator.blackmagician.assistant import update_observations, digest, FIELDS


def private_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, name = tempfile.mkstemp(dir=path.parent, prefix='.blackmagician-')
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            json.dump(data, stream, ensure_ascii=False, indent=2, allow_nan=False)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def public_state(state):
    # Credential and raw server documents stay in the local 0600 store.
    connection = state.get('connection')
    connection = {k: connection.get(k) for k in ('mode', 'project_id', 'session_id', 'status', 'last_error', 'snapshot_at', 'expires_at')} if connection else None
    snapshot = state.get('snapshot')
    if snapshot:
        snapshot = {k: v for k, v in snapshot.items() if k != 'raw_documents'}
        snapshot = json.loads(json.dumps(snapshot))
        if connection and connection.get('status') == 'connected':
            try:
                live = state.get('live') or {}
                freshness = live.get('last_received_at') if live.get('enabled') else snapshot['fetched_at']
                age = (datetime.now(timezone.utc) - datetime.fromisoformat(freshness)).total_seconds()
                if age > (35 if live.get('enabled') else 120):
                    connection['status'] = 'stale'
            except (ValueError, KeyError, TypeError):
                connection['status'] = 'stale'
        snapshot['from_cache'] = not connection or connection.get('status') != 'connected'
    live = dict(state.get('live') or {})
    live.pop('fingerprint', None)
    if live.get('enabled') and live.get('status') in {'live', 'polling', 'connecting', 'ended'}:
        try:
            age = (datetime.now(timezone.utc) - datetime.fromisoformat(live['last_received_at'])).total_seconds()
            if age > 35:
                live['status'] = 'reconnecting'
        except (ValueError, KeyError, TypeError):
            live['status'] = 'connecting'
    if snapshot and live and live.get('status') not in {'live', 'polling', 'ended'}:
        snapshot['from_cache'] = True
    review = state.get('review')
    if review and snapshot and snapshot.get('from_cache'):
        review = {**review, 'status': 'review_needed',
                  'summary': review['summary'] + ' 마지막 저장 정보로 검토한 결과입니다. 세션을 새로 동기화하세요.'}
    return {'connection': connection, 'snapshot': snapshot, 'review': review, 'live': live,
            'questions': state.get('questions', []),
            'confirmations': list(state.get('confirmations', {}).values()),
            'capabilities': {'live_read': True, 'local_script_notes': True, 'remote_write': False}}


class IntegrationService:
    def __init__(self, root: Path, runs_root: Path, registry, *, client_factory=BlackmagicianClient):
        self.root, self.runs_root, self.registry = root, runs_root, registry
        self.client_factory = client_factory

    def folder(self, project_id):
        document_id(project_id)
        if not any(p['id'] == project_id and not p.get('removed_at') for p in self.registry.load()['projects']):
            raise IntegrationError('Data Handler 프로젝트를 찾을 수 없습니다.', 404)
        return self.root / 'blackmagician' / project_id

    @contextmanager
    def locked(self, project_id):
        folder = self.folder(project_id)
        folder.mkdir(parents=True, exist_ok=True, mode=0o700)
        with (folder / '.lock').open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            yield folder

    def get(self, project_id):
        return public_state(read_object(self.folder(project_id) / 'state.json'))

    @staticmethod
    def environment():
        return 'sandbox' if os.environ.get('DATA_HANDLER_BLACKMAGICIAN_SANDBOX') == '1' else 'production'

    def _leave(self, client, connection, folder):
        if connection and connection.get('token'):
            if connection.get('environment', 'production') != self.environment():
                return
            try:
                client.leave(connection)
            except (httpx.HTTPError, IntegrationError):
                pending = read_object(folder / 'leave.pending.json').get('connections', [])
                if not any(c.get('token') == connection.get('token') for c in pending):
                    pending.append(connection)
                private_json(folder / 'leave.pending.json', {'connections': pending})

    def _retry_leaves(self, client, folder):
        path = folder / 'leave.pending.json'
        pending = read_object(path).get('connections', [])
        remaining = []
        for connection in pending:
            if connection.get('environment', 'production') != self.environment():
                remaining.append(connection)
                continue
            try:
                client.leave(connection)
            except (httpx.HTTPError, IntegrationError):
                remaining.append(connection)
        if remaining:
            private_json(path, {'connections': remaining})
        elif path.exists():
            path.unlink()

    def connect(self, project_id, mode, code, remote_project_id=None):
        with self.locked(project_id) as folder:
            state = read_object(folder / 'state.json')
            client = self.client_factory()
            try:
                self._retry_leaves(client, folder)
                if mode == 'invite':
                    target = client.join(code)
                elif mode == 'session':
                    pid, sid = client.resolve(code, remote_project_id)
                    target = {'project_id': pid, 'session_id': sid}
                else:
                    raise IntegrationError('연결 방식을 선택하세요.')
                self._leave(client, state.get('connection'), folder)
                previous = state
                old_connection = previous.get('connection') or {}
                same_session = old_connection.get('environment', 'production') == self.environment() and all(
                    old_connection.get(k) == target.get(k) for k in ('project_id', 'session_id'))
                if old_connection:
                    private_json(folder / 'history' / (digest([old_connection.get('project_id'), old_connection.get('session_id')]) + '.json'), public_state(previous))
                state = {'connection': {**target, 'mode': mode, 'status': 'connecting', 'environment': self.environment(),
                         'generation': uuid4().hex}, 'snapshot': None, 'review': None,
                         'live': {'enabled': True, 'status': 'connecting', 'transport': 'ndjson' if mode == 'invite' else 'poll',
                                  'poll_interval_seconds': 3}}
                if same_session:
                    state.update(snapshot=previous.get('snapshot'), confirmations=previous.get('confirmations', {}))
                # Persist a successful join before any read: retry must not consume another code.
                private_json(folder / 'state.json', state)
                self._sync(client, state, folder)
            finally:
                client.close()
            return public_state(state)

    def _sync(self, client, state, folder):
        try:
            snapshot = client.snapshot(state['connection'])
            self.apply_snapshot(state, snapshot)
        except (httpx.HTTPError, IntegrationError, ValueError, KeyError, TypeError) as exc:
            message = str(exc) if isinstance(exc, IntegrationError) else 'Blackmagician 정보를 읽지 못했습니다. 저장된 기록은 유지됩니다. 다시 동기화해 주세요.'
            state['connection'].update(status='reauth_required' if getattr(exc, 'status', None) == 401 else 'stale', last_error=message)
            private_json(folder / 'state.json', state)
            raise IntegrationError(message, getattr(exc, 'status', 502)) from None
        private_json(folder / 'state.json', state)

    @staticmethod
    def apply_snapshot(state, snapshot):
        if snapshot.get('complete') is not True:
            raise IntegrationError('불완전한 촬영 기록은 반영하지 않습니다.', 502)
        update_observations(state, snapshot)
        state['snapshot'] = snapshot
        state['connection'].update(status='connected', last_error=None, snapshot_at=snapshot['fetched_at'])
        live = state['live']
        ended = (snapshot.get('camera') or {}).get('isSessionEnded') is True
        live.update(last_received_at=snapshot['fetched_at'], last_observed_at=snapshot['fetched_at'],
                    status='paused' if live.get('enabled') is False else 'ended' if ended else ('live' if state['connection']['mode'] == 'invite' else 'polling'),
                    last_error=None)

    def configure_live(self, project_id, enabled):
        with self.locked(project_id) as folder:
            state = read_object(folder / 'state.json')
            if not state.get('connection'):
                raise IntegrationError('먼저 Blackmagician 세션을 연결하세요.', 409)
            live = state.setdefault('live', {})
            live.update(enabled=enabled, status='connecting' if enabled else 'paused')
            # In-flight data must not resurrect a paused or replaced connection.
            state['connection']['generation'] = uuid4().hex
            private_json(folder / 'state.json', state)
            return public_state(state)

    def confirm_note(self, project_id, question_id, value, entry_revision):
        value = value.strip()
        if not value or len(value) > 1000:
            raise IntegrationError('확인 내용을 1~1000자로 입력하세요.')
        with self.locked(project_id) as folder:
            state = read_object(folder / 'state.json')
            question = next((q for q in state.get('questions', []) if q['id'] == question_id), None)
            if not state.get('connection') or not question or question.get('field') not in FIELDS:
                raise IntegrationError('현재 확인 가능한 질문을 찾을 수 없습니다.', 409)
            if question['entry_revision'] != entry_revision:
                raise IntegrationError('촬영 기록이 변경되었습니다. 최신 질문을 확인하세요.', 409)
            answer = {'id': question_id, 'entry_key': question['entry_key'], 'field': question['field'],
                      'value': value, 'expected': question.get('expected'), 'entry_revision': entry_revision,
                      'session_id': state['connection']['session_id'], 'project_id': state['connection']['project_id'],
                      'status': 'local', 'confirmed_at': datetime.now(timezone.utc).isoformat(),
                      'source': 'operator', 'remote_applied': False}
            state.setdefault('confirmations', {})[question_id] = answer
            question['status'] = 'answered'
            private_json(folder / 'state.json', state)
            return public_state(state)

    def refresh(self, project_id):
        with self.locked(project_id) as folder:
            state = read_object(folder / 'state.json')
            if not state.get('connection'):
                raise IntegrationError('먼저 Blackmagician 세션을 연결하세요.', 409)
            if state['connection'].get('status') == 'reauth_required':
                raise IntegrationError('초대 코드로 다시 연결해 주세요.', 401)
            if state['connection'].get('environment', 'production') != self.environment():
                raise IntegrationError('이 연결은 다른 실행 환경에서 생성되었습니다. 현재 환경의 코드로 다시 연결하세요.', 409)
            client = self.client_factory()
            try:
                self._retry_leaves(client, folder)
                self._sync(client, state, folder)
            finally:
                client.close()
            return public_state(state)

    def disconnect(self, project_id):
        with self.locked(project_id) as folder:
            state = read_object(folder / 'state.json')
            client = self.client_factory()
            try:
                self._retry_leaves(client, folder)
                self._leave(client, state.get('connection'), folder)
            finally:
                client.close()
            connection = state.get('connection') or {}
            if connection:
                private_json(folder / 'history' / (digest([connection.get('project_id'), connection.get('session_id')]) + '.json'), public_state(state))
            state.update(connection=None, review=None, questions=[], confirmations={},
                         live={**state.get('live', {}), 'enabled': False, 'status': 'disconnected'})
            private_json(folder / 'state.json', state)
            return public_state(state)

    def review(self, project_id):
        with self.locked(project_id) as folder:
            state = read_object(folder / 'state.json')
            public = public_state(state)
            review = build_review(public['snapshot'], public['connection'], self.registry.load()['runs'], self.runs_root, project_id)
            state['review'] = review
            private_json(folder / 'review.json', review)
            private_json(folder / 'state.json', state)
            return public_state(state)
