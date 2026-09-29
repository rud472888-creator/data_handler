from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from orchestrator.blackmagician.client import BlackmagicianClient, IntegrationError, firestore_value, merge_entries
from orchestrator.blackmagician.review import build_review
from orchestrator.blackmagician.service import IntegrationService, private_json
from orchestrator.dit_app.blackmagician_bridge import create_router
from orchestrator.jsonio import write_json
from orchestrator.run_state import utc_now
from orchestrator.web.registry import ConsoleRegistry


def doc(path, fields):
    return {'name': 'projects/firebase/databases/(default)/documents/' + path, 'fields': fields}


def test_firestore_types_missing_and_nested():
    assert firestore_value({'mapValue': {'fields': {
        'count': {'integerValue': '9007199254740993'}, 'empty': {'stringValue': ''},
        'array': {'arrayValue': {'values': [{'nullValue': None}, {'booleanValue': False}, {'doubleValue': 23.98}]}},
        'timestamp': {'timestampValue': '2026-09-11T10:00:00Z'}}}}) == {
            'count': 9007199254740993, 'empty': '', 'array': [None, False, 23.98], 'timestamp': '2026-09-11T10:00:00Z'}
    with pytest.raises(IntegrationError):
        firestore_value({'unexpectedValue': 'do not silently drop'})


def test_resolve_paginated_case_sensitive_and_ambiguous():
    calls = []
    def handler(request):
        calls.append(str(request.url))
        path = request.url.path.split('/documents/')[-1]
        if path == 'projects':
            if request.url.params.get('pageToken'):
                assert request.url.params['pageToken'] == 'next/+='
                return httpx.Response(200, json={'documents': [doc('projects/p2', {})]})
            return httpx.Response(200, json={'documents': [doc('projects/p1', {})], 'nextPageToken': 'next/+='})
        if path.endswith('/sessions/MiXeD'):
            return httpx.Response(200, json=doc(path, {}))
        return httpx.Response(404)
    client = BlackmagicianClient(transport=httpx.MockTransport(handler))
    with pytest.raises(IntegrationError) as error:
        client.resolve(' MiXeD ')
    assert error.value.status == 409
    assert len(error.value.matches) == 2
    assert client.resolve('MiXeD', 'p2') == ('p2', 'MiXeD')
    with pytest.raises(IntegrationError) as error:
        client.resolve('mixed', 'p2')
    assert error.value.status == 404
    assert len(calls) == 6


@pytest.mark.parametrize('bad', ['', '/', '..', '.', 'a/b', 'a\x00b', 'a\nb'])
def test_bad_ids_rejected_before_network(bad):
    client = BlackmagicianClient(transport=httpx.MockTransport(lambda r: pytest.fail('network must not run')))
    with pytest.raises(IntegrationError):
        client.resolve(bad)


def test_dedup_legacy_ids_conflicts_and_missing_dates():
    documents = [
        {'path': 'projects/p/sessions/s/scriptEntries/legacy', 'data': {'takeId': 'take-1', 'sceneInfo': ''}},
        {'path': 'projects/p/takeRecords/take-1', 'data': {'takeId': 'take-1', 'sceneInfo': '수정'}},
        {'path': 'projects/p/sessions/s/scriptEntries/no-date', 'data': {'clipName': 'C2'}},
        {'path': 'projects/p/sessions/s/scriptEntries/date', 'data': {'clipName': 'C3', 'createdAt': 1000}},
    ]
    merged = merge_entries(documents, 'p', 's')
    assert len(merged) == 3
    item = next(e for e in merged if e['key'].endswith('/take-1'))
    assert len(item['paths']) == 2 and item['data']['sceneInfo'] == '수정'
    assert item['conflicts'][0]['field'] == 'sceneInfo'
    assert merged[-1]['data']['clipName'] == 'C3'


def test_full_firestore_snapshot_reads_ended_history_and_both_paths():
    def handler(request):
        path = request.url.path.split('/documents/')[-1]
        if path == 'projects/p/sessions/s':
            return httpx.Response(200, json=doc(path, {'fps': {'integerValue': '2398'}, 'isSessionEnded': {'booleanValue': True}}))
        if '/scriptEntries' in path or '/takeRecords' in path:
            return httpx.Response(200, json={'documents': [doc(path + '/different-id', {
                'takeId': {'stringValue': 'T1'}, 'sessionId': {'stringValue': 's'}, 'clipName': {'stringValue': 'A001'}})]})
        return httpx.Response(404)
    client = BlackmagicianClient(transport=httpx.MockTransport(handler))
    result = client.snapshot({'mode': 'session', 'project_id': 'p', 'session_id': 's'})
    assert result['complete'] and result['camera']['isSessionEnded']
    assert result['display_fps'] == 23.98 and result['camera']['fps'] == 2398
    assert len(result['entries']) == 1 and len(result['raw_documents']) == 3
    assert result['script'] is None


class Chunks(httpx.SyncByteStream):
    def __init__(self, data):
        self.data = data
    def __iter__(self):
        for i in range(0, len(self.data), 7):
            yield self.data[i:i+7]


def test_ndjson_chunk_boundaries_initialization_and_eof_reconnect(monkeypatch):
    monkeypatch.setattr('orchestrator.blackmagician.client.time.sleep', lambda _: None)
    count = 0
    def handler(request):
        nonlocal count
        count += 1
        events = [{'type': 'camera', 'data': {'scene': '창가'}}]
        if count > 1:
            events += [{'type': 'entries', 'data': [{'id': 'legacy', 'clipName': 'A001'}]},
                       {'type': 'script', 'data': {}}, {'type': 'access', 'data': {'sessionActive': False}}]
        return httpx.Response(200, stream=Chunks(('\n'.join(json.dumps(e, ensure_ascii=False) for e in events)+'\n').encode()))
    client = BlackmagicianClient(transport=httpx.MockTransport(handler))
    result = client.snapshot({'mode': 'invite', 'project_id': 'p', 'session_id': 's', 'token': 'SECRET'})
    assert count == 2 and result['complete'] and result['camera']['scene'] == '창가'
    assert len(result['entries']) == 1


def test_web_401_does_not_retry_or_treat_partial_as_complete():
    calls = []
    client = BlackmagicianClient(transport=httpx.MockTransport(lambda r: calls.append(r) or httpx.Response(401)))
    with pytest.raises(IntegrationError) as error:
        client.web_snapshot({'token': 'SECRET'})
    assert error.value.status == 401 and len(calls) == 1


def test_join_normalizes_invite_and_does_not_forward_token_to_events_url():
    def handler(request):
        assert json.loads(request.content) == {'code': 'ABCD1234'}
        return httpx.Response(200, json={'projectId': 'p', 'sessionId': 'MiXeD', 'token': 'SECRET',
            'expiresAt': 123, 'eventsUrl': 'https://untrusted.example/collect'})
    client = BlackmagicianClient(transport=httpx.MockTransport(handler))
    result = client.join(' abcd- 1234 ')
    assert result['events_url'] == client.api_url + '/api/events'


@pytest.fixture
def registry(tmp_path):
    registry = ConsoleRegistry(tmp_path / 'console-registry.json')
    data = registry.load()
    data['projects'] = [{'id': 'local', 'name': 'Test'}]
    registry.save(data)
    return registry


class FakeClient:
    def __init__(self):
        self.joins = 0
        self.failure = False
        self.entries = [{'key': 'p/s/T1', 'data': {'takeId': 'T1', 'clipName': 'A001'}, 'paths': ['p/T1'], 'conflicts': []}]
    def join(self, code):
        self.joins += 1
        return {'project_id': 'p', 'session_id': 's', 'token': 'NEVER-IN-BROWSER', 'expires_at': 10**15}
    def resolve(self, code, project=None):
        return 'p', code
    def snapshot(self, connection):
        if self.failure:
            raise IntegrationError('expired', 401)
        return {'camera': {}, 'script': {}, 'access': {}, 'entries': self.entries, 'conflicts': [],
                'complete': True, 'fetched_at': utc_now(), 'raw_documents': {}}
    def leave(self, connection):
        pass
    def close(self):
        pass


def test_service_credentials_persistence_replacement_and_stale(tmp_path, registry):
    client = FakeClient()
    service = IntegrationService(tmp_path, tmp_path / 'runs', registry, client_factory=lambda: client)
    connected = service.connect('local', 'invite', 'ABCD1234')
    assert 'NEVER-IN-BROWSER' not in json.dumps(connected)
    path = tmp_path / 'blackmagician/local/state.json'
    assert path.stat().st_mode & 0o777 == 0o600
    client.entries = []
    assert service.refresh('local')['snapshot']['entries'] == []
    assert client.joins == 1
    client.failure = True
    with pytest.raises(IntegrationError):
        service.refresh('local')
    result = service.get('local')
    assert result['connection']['status'] == 'reauth_required' and result['snapshot']['from_cache']
    with pytest.raises(IntegrationError):
        service.refresh('local')
    assert client.joins == 1
    assert service.disconnect('local')['connection'] is None
    assert 'NEVER-IN-BROWSER' not in path.read_text()


def test_failed_initial_read_keeps_join_for_refresh(tmp_path, registry):
    client = FakeClient()
    client.failure = True
    service = IntegrationService(tmp_path, tmp_path/'runs', registry, client_factory=lambda: client)
    with pytest.raises(IntegrationError):
        service.connect('local', 'invite', 'ABCD1234')
    assert json.loads((tmp_path/'blackmagician/local/state.json').read_text())['connection']['token'] == 'NEVER-IN-BROWSER'
    assert client.joins == 1


def evidence_fixture(tmp_path, registry):
    folder = tmp_path / 'runs/run-test'
    content = b'real fixture bytes'
    checksum = hashlib.sha256(content).hexdigest()
    roots = {f'path{i}': str(tmp_path / f'replica-{i}') for i in (1, 2)}
    replicas = []
    for i in (1, 2):
        dest = Path(roots[f'path{i}']) / '001_Footage/R#1/A001.mov'
        dest.parent.mkdir(parents=True)
        dest.write_bytes(content)
        replicas.append({'path_id': f'dest-{i}', 'dest_relpath': '001_Footage/R#1/A001.mov', 'checksum': checksum, 'status': 'verified'})
    item = {'file_id': 'f1', 'job_id': 'job1', 'source_relpath': 'A001.mov', 'size_bytes': len(content),
            'checksum_source': checksum, 'status': 'verified', 'replica_results': replicas}
    done = {'job_id': 'job1', 'status': 'completed', 'replicas_complete': True, 'file_count': 1,
            'replica_count': 2, 'replica_path_ids': ['dest-1', 'dest-2'], 'replica_project_roots': roots, 'finished_at': utc_now()}
    write_json(folder / 'events/datamanager.done.json', done)
    write_json(folder / 'blackmagician/manifest.json', {'job_id': 'job1', 'files': [item]})
    data = registry.load()
    data['runs'] = [{'project_id': 'local', 'run_id': 'run-test', 'camera_unit': 'A'}]
    registry.save(data)
    client = FakeClient()
    snapshot = client.snapshot({})
    snapshot['entries'].append({'key':'p/s/T2','data':{'clipName':'MISSING'},'paths':['p/T2'],'conflicts':[]})
    return folder, item, done, snapshot, data['runs']


def test_review_matches_checksums_detects_missing_and_unavailable(tmp_path, registry):
    folder, item, done, snapshot, records = evidence_fixture(tmp_path, registry)
    def review():
        return build_review(snapshot, {'status':'connected'}, records, tmp_path/'runs', 'local')
    result = review()
    assert [c['status'] for c in result['clips']] == ['verified', 'missing']
    assert result['status'] == 'review_needed'
    snapshot['entries'].pop()
    assert review()['status'] == 'verified'
    Path(done['replica_project_roots']['path2'], '001_Footage/R#1/A001.mov').write_bytes(b'corrupt')
    assert review()['clips'][0]['status'] == 'unavailable'


@pytest.mark.parametrize('problem', ['hash', 'missing_replica', 'bad_job', 'no_checksum', 'path_escape', 'bad_count'])
def test_review_never_passes_invalid_evidence(tmp_path, registry, problem):
    folder, item, done, snapshot, records = evidence_fixture(tmp_path, registry)
    if problem == 'hash': item['replica_results'][0]['checksum'] = '0'*64
    if problem == 'missing_replica': item['replica_results'].pop()
    if problem == 'bad_job': item['job_id'] = 'other-card'
    if problem == 'no_checksum': item['checksum_source'] = None
    if problem == 'path_escape': item['replica_results'][0]['dest_relpath'] = '../outside'
    if problem == 'bad_count': done['file_count'] = 5
    write_json(folder/'events/datamanager.done.json', done)
    write_json(folder/'blackmagician/manifest.json', {'job_id':'job1','files':[item]})
    result = build_review(snapshot, {'status':'connected'}, records, tmp_path/'runs', 'local')
    assert result['status'] == 'review_needed'
    assert result['counts']['verified'] == 0


def test_review_conflicts_ambiguous_unknown_and_stale(tmp_path, registry):
    folder, item, done, snapshot, records = evidence_fixture(tmp_path, registry)
    snapshot['entries'] = snapshot['entries'][:1]
    snapshot['entries'][0]['conflicts'] = [{'field':'sceneInfo'}]
    result = build_review(snapshot, {'status':'connected'}, records, tmp_path/'runs', 'local')
    assert result['clips'][0]['status'] == 'conflict'
    snapshot['entries'][0]['conflicts'] = []
    snapshot['entries'].append(copy.deepcopy(snapshot['entries'][0]))
    assert build_review(snapshot, {'status':'connected'}, records, tmp_path/'runs', 'local')['clips'][0]['status'] == 'ambiguous'
    snapshot['entries'].pop()
    assert build_review(snapshot, {'status':'stale'}, records, tmp_path/'runs', 'local')['status'] == 'review_needed'
    snapshot['entries'][0]['data'] = {'clipToken': 'A001'}
    assert build_review(snapshot, None, records, tmp_path/'runs', 'local')['clips'][0]['status'] == 'unknown'


def test_bridge_auth_errors_and_success(tmp_path, registry):
    app = FastAPI()
    app.include_router(create_router(tmp_path, tmp_path/'runs', registry, client_factory=FakeClient))
    client = TestClient(app, base_url='http://127.0.0.1')
    assert client.get('/api/blackmagician/projects/local').status_code == 401
    assert client.get('/api/blackmagician/session', headers={'origin':'https://evil.example'}).status_code == 403
    assert client.get('/api/blackmagician/session', headers={'host':'evil.example'}).status_code == 403
    token = client.get('/api/blackmagician/session').json()['token']
    client.headers['x-dit-blackmagician'] = token
    response = client.post('/api/blackmagician/projects/local/connect', json={'mode':'invite','code':'ABCD1234'})
    assert response.status_code == 200 and 'NEVER-IN-BROWSER' not in response.text
    assert client.post('/api/blackmagician/projects/local/review').json()['review']['counts']['total'] == 1
    assert client.get('/api/blackmagician/projects/absent').status_code == 404


def test_agent_review_uses_same_evidence_without_model_or_execution(tmp_path, registry):
    from orchestrator.agent.service import AgentService
    folder, item, done, snapshot, records = evidence_fixture(tmp_path, registry)
    private_json(tmp_path/'blackmagician/local/state.json', {'connection':{'status':'connected'},'snapshot':snapshot})
    service = AgentService(tmp_path, {}, starter=lambda *a: pytest.fail('review cannot start work'))
    result = service.interpret('/backup-review', 'desktop:test', project_id='local')
    assert result['backup_review']['counts']['verified'] == 1
    assert 'MISSING' in result['text'] and '확인' in result['text']
