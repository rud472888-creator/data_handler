import json
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from orchestrator.agent.store import Store
from orchestrator.dit_app.agent_bridge import create_router


def test_chat_is_durable_ordered_and_idempotent(tmp_path):
    store = Store(tmp_path / 'chat.sqlite')
    first, second = uuid4().hex, uuid4().hex
    store.create_conversation(first, 'project')
    store.create_conversation(second, None)
    key = 'chat:' + str(uuid4())
    store.enqueue_turn(first, key, '원본 카드 준비')
    store.enqueue_turn(first, key, '원본 카드 준비')
    with pytest.raises(ValueError):
        store.enqueue_turn(second, key, '원본 카드 준비')
    with pytest.raises(ValueError):
        store.enqueue_turn(first, 'chat:' + str(uuid4()), '추가 요청')
    with store.connect() as db:
        payload = json.loads(db.execute('SELECT payload FROM inbox').fetchone()[0])
        assert payload['principal'] == 'desktop:' + first
        assert payload['project_id'] == 'project'
        db.execute("UPDATE inbox SET status='done',result=?", (json.dumps({'text':'경로를 알려 주세요'}),))
    store.enqueue_turn(first, 'chat:' + str(uuid4()), '두 곳에 복제')
    restored = Store(tmp_path / 'chat.sqlite').conversation(first)
    assert [t['text'] for t in restored['turns']] == ['원본 카드 준비', '두 곳에 복제']
    assert restored['turns'][0]['result']['text'] == '경로를 알려 주세요'
    assert store.conversation(second)['turns'] == []


def test_bridge_requires_local_origin_and_session(tmp_path):
    calls = []
    def transport(path, payload):
        calls.append((path, payload))
        return {'ok':True, 'telegram_paired':True, 'api_token':'must-not-reach-browser'}
    app = FastAPI()
    app.include_router(create_router(tmp_path, tmp_path, None, transport=transport))
    client = TestClient(app, base_url='http://127.0.0.1:8750')
    assert client.get('/api/agent/state').status_code == 401
    assert client.get('/api/agent/session', headers={'Origin':'https://evil.example'}).status_code == 403
    assert client.get('/api/agent/session', headers={'Sec-Fetch-Site':'cross-site'}).status_code == 403
    assert client.get('/api/agent/session', headers={'Host':'evil.example'}).status_code == 403
    session = client.get('/api/agent/session')
    assert session.headers['cache-control'] == 'no-store'
    headers = {'X-DIT-Agent':session.json()['token']}
    response = client.get('/api/agent/state', headers=headers)
    assert response.json() == {'connected':True,'telegram_paired':True,
        'inference_connected':False,'model_loaded':False,'telegram_connected':False,
        'model_loading':False,'model_load_error':None}
    assert 'must-not-reach-browser' not in response.text
    assert client.post('/api/agent/conversations/no/messages', headers=headers,
        json={'text':'test','request_id':'chat:'+str(uuid4())}).status_code == 404
    assert len(calls) == 1


def test_bridge_uninstalled_agent_is_recoverable(tmp_path):
    app = FastAPI()
    app.include_router(create_router(tmp_path, tmp_path, None))
    client = TestClient(app, base_url='http://localhost')
    token = client.get('/api/agent/session').json()['token']
    response = client.get('/api/agent/state', headers={'X-DIT-Agent':token})
    assert response.status_code == 503
    assert '다시 연결' in response.json()['detail']
