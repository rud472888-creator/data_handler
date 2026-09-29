from __future__ import annotations

import copy
import json
import threading
import time
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from orchestrator.blackmagician.assistant import shooting_context
from orchestrator.blackmagician.client import BlackmagicianClient, IntegrationError
from orchestrator.blackmagician.live import LiveSessions
from orchestrator.blackmagician.service import IntegrationService, private_json, public_state
from orchestrator.dit_app.blackmagician_bridge import create_router
from orchestrator.tests.test_blackmagician import FakeClient, Chunks, registry


def connected(tmp_path, registry):
    client = FakeClient()
    service = IntegrationService(tmp_path, tmp_path/'runs', registry, client_factory=lambda: client)
    service.connect('local', 'invite', 'ABCD1234')
    return service, client


def saved(tmp_path):
    return json.loads((tmp_path/'blackmagician/local/state.json').read_text())


def test_watch_full_initialization_replacements_heartbeat_and_no_join():
    messages = [
        {'type':'camera', 'data':{'scene':'24A'}},
        {'type':'heartbeat','data':{}},
        {'type':'entries','data':[{'id':'one','takeId':'T1','clipName':'A001'}]},
        {'type':'script','data':{'sceneInfo':'창가'}},
        {'type':'access','data':{'sessionActive':True}},
        {'type':'entries','data':[{'id':'one','takeId':'T1','clipName':'A001','sceneInfo':'수정'}]},
        {'type':'entries','data':[]},
        {'type':'heartbeat','data':{}},
    ]
    def handler(request):
        assert request.url.path == '/api/events'
        assert request.headers['authorization'] == 'Bearer SECRET'
        return httpx.Response(200, stream=Chunks(('\n'.join(json.dumps(m) for m in messages)+'\n').encode()))
    client = BlackmagicianClient(transport=httpx.MockTransport(handler))
    received = []
    with pytest.raises(IntegrationError, match='종료'):
        for snapshot in client.watch({'project_id':'p','session_id':'s','token':'SECRET','events_url':'https://evil.example'}, threading.Event()):
            received.append(copy.deepcopy(snapshot))
    assert len(received) == 4
    assert received[0]['entries'][0]['data']['clipName'] == 'A001'
    assert received[1]['entries'][0]['data']['sceneInfo'] == '수정'
    assert received[2]['entries'] == [] and received[3] is None


@pytest.mark.parametrize('status', [401, 403, 404, 410])
def test_stream_terminal_error_does_not_retry_join(status):
    client = BlackmagicianClient(transport=httpx.MockTransport(lambda r: httpx.Response(status)))
    with pytest.raises(IntegrationError) as failure:
        next(client.watch({'token':'SECRET'}, threading.Event()))
    assert failure.value.status == status


def test_partial_stream_never_published():
    data = b'{"type":"entries","data":[]}\n{"type":"heartbeat","data":{}}\n'
    client = BlackmagicianClient(transport=httpx.MockTransport(lambda r: httpx.Response(200, content=data)))
    with pytest.raises(IntegrationError):
        next(client.watch({'token':'SECRET'}, threading.Event()))


def test_live_generation_blocks_old_stream_after_pause_disconnect_and_replace(tmp_path, registry):
    service, client = connected(tmp_path, registry)
    live = LiveSessions(service)
    generation = saved(tmp_path)['connection']['generation']
    snapshot = copy.deepcopy(client.snapshot({}))
    snapshot['entries'] = []
    service.configure_live('local', False)
    assert not live.commit('local', generation, snapshot)
    assert len(service.get('local')['snapshot']['entries']) == 1
    service.configure_live('local', True)
    assert not live.commit('local', generation, snapshot)
    generation = saved(tmp_path)['connection']['generation']
    assert live.commit('local', generation, snapshot)
    assert service.get('local')['snapshot']['entries'] == []
    service.disconnect('local')
    assert not live.commit('local', generation, snapshot)
    assert service.get('local')['connection'] is None


def test_observer_notes_conflict_reflection_delete_and_reconnect(tmp_path, registry):
    service, client = connected(tmp_path, registry)
    question = next(q for q in service.get('local')['questions'] if q['field'] == 'takeResult')
    original = copy.deepcopy(client.entries[0]['data'])
    result = service.confirm_note('local', question['id'], 'OK', question['entry_revision'])
    assert result['confirmations'][0]['status'] == 'local'
    assert result['snapshot']['entries'][0]['data'] == original
    service.connect('local', 'invite', 'ABCD1234')
    assert service.get('local')['confirmations'][0]['value'] == 'OK'
    client.entries[0]['data']['sceneInfo'] = '수정된 메모'
    result = service.refresh('local')
    assert result['confirmations'][0]['status'] == 'conflict'
    with pytest.raises(IntegrationError, match='변경'):
        service.confirm_note('local', question['id'], 'NG', question['entry_revision'])
    client.entries[0]['data']['takeResult'] = 'OK'
    assert service.refresh('local')['confirmations'][0]['status'] == 'reflected'
    client.entries = []
    assert service.refresh('local')['confirmations'][0]['status'] == 'obsolete'
    assert len(list((tmp_path/'blackmagician/local/history').glob('*.json'))) == 1


def test_duplicate_snapshots_keep_revision_and_questions(tmp_path, registry):
    service, client = connected(tmp_path, registry)
    first = service.get('local')
    next_state = service.refresh('local')
    assert next_state['live']['revision'] == first['live']['revision']
    assert next_state['questions'] == first['questions']
    client.entries[0]['data']['takeResult'] = 'NG'
    assert service.refresh('local')['live']['revision'] == first['live']['revision'] + 1


def test_fresh_heartbeat_keeps_idle_stream_live_but_not_after_crash(tmp_path, registry):
    service, _ = connected(tmp_path, registry)
    state = saved(tmp_path)
    old = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
    state['snapshot']['fetched_at'] = old
    assert not public_state(state)['snapshot']['from_cache']
    state['live']['last_received_at'] = old
    assert public_state(state)['snapshot']['from_cache']
    assert public_state(state)['live']['status'] == 'reconnecting'
    state['live'].update(enabled=False, status='paused')
    assert public_state(state)['snapshot']['from_cache']


def test_model_receives_latest_scoped_records_and_evidence(tmp_path, registry, monkeypatch):
    from orchestrator.agent.service import AgentService
    service, remote = connected(tmp_path, registry)
    remote.entries[0]['data'].update(scene='24A', takeResult='OK')
    service.refresh('local')
    requests = []
    def handler(request):
        payload = json.loads(request.content)
        requests.append(payload)
        context = payload['catalog']['shooting']
        assert context['entries'][0]['data']['takeResult'] == 'OK'
        assert 'NEVER-IN-BROWSER' not in request.content.decode()
        assert context['recorded_total'] == 1
        return httpx.Response(200, json={'intent':{'action':'shooting_answer','explanation':'A001의 씬은 24A, 결과는 OK입니다.'}})
    real_client = httpx.Client
    monkeypatch.setattr('orchestrator.agent.service.httpx.Client', lambda **kwargs: real_client(transport=httpx.MockTransport(handler)))
    agent = AgentService(tmp_path, {'inference_url':'http://127.0.0.1:8767','api_token':'local'})
    reply = agent.interpret('최근 테이크 알려줘', 'desktop:test', project_id='local')
    assert '24A' in reply['text'] and reply['shooting_evidence']['revision'] == 2
    assert len(requests) == 1
    service.configure_live('local', False)
    assert agent.interpret('/shooting', 'desktop:test', project_id='local')['shooting_evidence']['from_cache']


def test_context_has_full_count_and_bounded_search_results(tmp_path, registry):
    service, client = connected(tmp_path, registry)
    client.entries = [dict(key=f'p/s/{i}', data={'clipName':f'CLIP_{i}', 'sceneInfo':'메모'*500}, paths=[], conflicts=[]) for i in range(200)]
    context = shooting_context(service.refresh('local'), 'CLIP_12')
    assert context['recorded_total'] == 200 and context['entries_omitted'] > 0
    assert context['entries'][0]['data']['clipName'].startswith('CLIP_12')


def test_lifespan_resumes_live_without_browser_or_model(tmp_path, registry):
    class Feed(FakeClient):
        updates = threading.Event()
        entered = threading.Event()
        def watch(self, connection, stopped):
            self.entered.set()
            while not stopped.wait(.02):
                if self.updates.is_set():
                    self.updates.clear()
                    yield copy.deepcopy(self.snapshot(connection))
    feed = Feed()
    service = IntegrationService(tmp_path, tmp_path/'runs', registry, client_factory=lambda: feed)
    service.connect('local', 'invite', 'ABCD1234')
    app = FastAPI()
    app.include_router(create_router(tmp_path, tmp_path/'runs', registry, client_factory=lambda: feed))
    with TestClient(app, base_url='http://127.0.0.1'):
        assert feed.entered.wait(2)
        feed.entries = []
        feed.updates.set()
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline and service.get('local')['snapshot']['entries']:
            time.sleep(.02)
        assert service.get('local')['snapshot']['entries'] == []
    assert feed.joins == 1


def test_note_and_live_endpoints_require_auth_and_revision(tmp_path, registry):
    app = FastAPI()
    app.include_router(create_router(tmp_path, tmp_path/'runs', registry, client_factory=FakeClient))
    client = TestClient(app, base_url='http://127.0.0.1')
    path = '/api/blackmagician/projects/local'
    assert client.post(path+'/live', json={'enabled':True}).status_code == 401
    client.headers['x-dit-blackmagician'] = client.get('/api/blackmagician/session').json()['token']
    result = client.post(path+'/connect', json={'mode':'invite','code':'ABCD1234'}).json()
    q = result['questions'][0]
    assert client.post(path+'/questions/'+q['id'], json={'value':'24A','entry_revision':'a'*24}).status_code == 409
    answer = client.post(path+'/questions/'+q['id'], json={'value':'24A','entry_revision':q['entry_revision']})
    assert answer.status_code == 200 and answer.json()['confirmations'][0]['remote_applied'] is False
    assert client.post(path+'/live', json={'enabled':False}).json()['live']['status'] == 'paused'


def test_paused_state_downgrades_existing_review_and_shutdown_blocks_commit(tmp_path, registry):
    service, client = connected(tmp_path, registry)
    state = saved(tmp_path)
    state['review'] = {'status':'verified', 'summary':'일치'}
    state['live'].update(enabled=False, status='paused')
    assert public_state(state)['review']['status'] == 'review_needed'
    live = LiveSessions(service)
    live.close()
    assert not live.commit('local', state['connection']['generation'], client.snapshot({}))


def test_deleted_camera_stops_stream_without_erasing_last_snapshot():
    client = BlackmagicianClient(transport=httpx.MockTransport(lambda r: httpx.Response(200,
        content=b'{"type":"camera","data":null}\n')))
    with pytest.raises(IntegrationError) as error:
        next(client.watch({'token':'SECRET'}, threading.Event()))
    assert error.value.status == 404


def test_project_scope_never_reads_another_connection(tmp_path, registry):
    from orchestrator.agent.service import AgentService
    service, _ = connected(tmp_path, registry)
    data=registry.load()
    data['projects'].append({'id':'other','name':'Other'})
    registry.save(data)
    agent=AgentService(tmp_path,{})
    assert agent.shooting_state('other')['snapshot'] is None
    reply=agent.interpret('/shooting','desktop:other',project_id='other')
    assert '먼저 연결' in reply['text']
    assert reply['shooting_evidence']['session_id'] is None


def test_resuming_legacy_connection_enables_background_worker(tmp_path, registry):
    service, _ = connected(tmp_path, registry)
    state=saved(tmp_path)
    state.pop('live')
    state['connection'].pop('generation')
    private_json(tmp_path/'blackmagician/local/state.json',state)
    result=service.configure_live('local',True)
    assert result['live']['enabled'] is True
    assert saved(tmp_path)['connection']['generation']
