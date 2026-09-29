from __future__ import annotations

import json
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

import pytest

from orchestrator.agent.service import AgentService
from orchestrator.agent.telegram import accept_update, deliver_once
from orchestrator.jsonio import write_json


def test_telegram_followup_retains_prior_context(service):
    import threading
    from orchestrator.agent.telegram import command_worker
    calls = []
    stopped = threading.Event()
    def interpret(text, principal, **kwargs):
        calls.append(kwargs['history'])
        if len(calls) == 2:
            stopped.set()
        return {'text': '원본을 알려 주세요'}
    service.interpret = interpret
    accept_update(service, update(text='프로젝트 Test', update_id=1))
    accept_update(service, update(text='원본 /Volumes/Card', update_id=2))
    command_worker(service, stopped)
    assert calls[0] == []
    assert calls[1] == [{'role':'user','text':'프로젝트 Test'},
                        {'role':'assistant','text':'원본을 알려 주세요'}]


def test_failed_launch_retains_chat_run_identity(service):
    import threading
    from orchestrator.agent.telegram import command_worker
    stopped = threading.Event()
    plan = service.preview(service.test_payload, 'desktop:test')
    def fail(plan, run):
        stopped.set()
        raise OSError('uncertain launch')
    service.starter = fail
    service.store.enqueue('approval-test', {'text':'/approve '+plan['id'], 'principal':'desktop:test'})
    command_worker(service, stopped)
    with service.store.connect() as db:
        result = json.loads(db.execute("SELECT result FROM inbox WHERE id='approval-test'").fetchone()[0])
        saved = db.execute('SELECT run_id FROM plans WHERE id=?',(plan['id'],)).fetchone()[0]
    assert result['run_id'] == saved
    assert result['status'] == 'needs_review'
    assert result['error'] is True


def test_health_distinguishes_inference_and_stale_telegram(service, monkeypatch):
    import httpx
    import time
    service.config['inference_url'] = 'http://127.0.0.1:8767'
    service.store.set_meta('telegram_last_connected', str(time.time()-100))
    def offline(*args, **kwargs):
        raise httpx.ConnectError('offline')
    monkeypatch.setattr(httpx.Client, 'get', offline)
    health = service.health()
    assert health['ok'] and health['telegram_paired']
    assert not health['inference_connected'] and not health['telegram_connected']
    service.store.set_meta('telegram_last_connected', str(time.time()))
    monkeypatch.setattr(httpx.Client, 'get', lambda *a, **k: httpx.Response(200,
        json={'ok':True,'loaded':False},request=httpx.Request('GET','http://localhost/health')))
    assert service.health()['inference_connected']
    assert service.health()['telegram_connected']


@pytest.mark.parametrize('reports', [[], [{'status':'completed','exit_code':0}],
    [{'status':'completed','exit_code':0,'pdf_path':'a.pdf','missing_artifacts':['csv']}]] )
def test_incomplete_review_never_displays_success(service, reports):
    from orchestrator.dit_app.server import card_snapshot
    folder = service.root / 'runs' / 'review-test'
    write_json(folder / 'request.json', {'project_name':'Test','replica_roots':['one','two']})
    write_json(folder / 'events/datamanager.done.json', {'status':'completed','replicas_complete':True})
    write_json(folder / 'events/datahelper.done.json', {'status':'completed','reports':reports})
    assert card_snapshot({'run_id':'review-test'},service.root/'runs')['phase'] == 'review'
    service._collect_run('review-test',123)
    with service.store.connect() as db:
        payload = json.loads(db.execute("SELECT payload FROM outbox WHERE id NOT LIKE '%:summary' ORDER BY rowid LIMIT 1").fetchone()[0])
    assert payload['text'].startswith('작업 확인 필요')


@pytest.fixture
def service(tmp_path):
    roots = [tmp_path / name for name in ('source', 'one', 'two')]
    for root in roots:
        root.mkdir()
    (roots[0] / 'clip.txt').write_text('sample')
    config = {'allowed_roots': [str(tmp_path)], 'allowed_user_id': 123, 'allowed_chat_id': 123,
              'api_token': 'test-only', 'telegram_token_file': str(tmp_path / 'absent')}
    agent = AgentService(tmp_path / 'pipeline', config, starter=lambda plan, run: None)
    agent.registry.save({'projects': [{'id': 'p1', 'name': 'Test', 'replica_roots': [],
        'replica_project_roots': [], 'preset_name': 'dit', 'created_at': '', 'updated_at': ''}], 'runs': []})
    agent.test_payload = {'project_id': 'p1', 'source_path': str(roots[0]),
        'replica_paths': list(map(str, roots[1:])), 'shoot_date': '2026-09-08', 'camera_unit': 'A'}
    return agent


def test_confirmation_is_owned_and_single_execution(service):
    called = []
    service.starter = lambda p, r: called.append(r)
    plan = service.preview(service.test_payload, 'telegram:123')
    with pytest.raises(ValueError):
        service.execute(plan['id'], 'telegram:456')
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: service.execute(plan['id'], 'telegram:123'), range(2)))
    assert len(called) == 1
    assert len({r['run_id'] for r in results}) == 1


def test_source_mutation_invalidates_plan(service):
    plan = service.preview(service.test_payload, 'local')
    (Path(plan['source_path']) / 'another.txt').write_text('new')
    with pytest.raises(ValueError, match='변경'):
        service.execute(plan['id'], 'local')


def test_nested_and_disallowed_paths(service, tmp_path):
    with pytest.raises(ValueError):
        service.preview({**service.test_payload, 'replica_paths': [str(tmp_path), service.test_payload['replica_paths'][0]]}, 'local')
    service.config['allowed_roots'] = [str(tmp_path / 'unrelated')]
    with pytest.raises(ValueError):
        service.preview(service.test_payload, 'local')


def test_symlink_in_source_rejected(service):
    (Path(service.test_payload['source_path']) / 'escape').symlink_to('/etc/passwd')
    with pytest.raises(ValueError, match='심볼릭'):
        service.preview(service.test_payload, 'local')


def update(uid=123, chat=123, text='/status', update_id=1, kind='private'):
    return {'update_id': update_id, 'message': {'from': {'id': uid},
            'chat': {'id': chat, 'type': kind}, 'text': text}}


def test_telegram_allowlist_and_deduplication(service):
    assert not accept_update(service, update(uid=456, chat=456))
    assert not accept_update(service, update(kind='group'))
    assert accept_update(service, update())
    assert accept_update(service, update())
    with service.store.connect() as db:
        assert db.execute('SELECT COUNT(*) FROM inbox').fetchone()[0] == 1


def test_pairing_requires_local_secret(service, monkeypatch, tmp_path):
    import orchestrator.agent.telegram as telegram
    monkeypatch.setattr(telegram, 'config_path', lambda: tmp_path / 'config.json')
    service.config.update(allowed_user_id=None, allowed_chat_id=None, pairing_code='long-secret')
    assert not accept_update(service, update(text='/start'))
    assert accept_update(service, update(text='/start long-secret'))
    assert service.config['allowed_user_id'] == 123
    assert service.config['pairing_code'] == ''
    assert not accept_update(service, update(uid=456, chat=456, text='/start long-secret'))


def test_failed_start_never_reexecuted(service):
    count = []
    def uncertain(p, r):
        count.append(r)
        raise OSError('ambiguous spawn')
    service.starter = uncertain
    plan = service.preview(service.test_payload, 'local')
    with pytest.raises(OSError):
        service.execute(plan['id'], 'local')
    result = service.execute(plan['id'], 'local')
    assert result['status'] == 'needs_review'
    assert len(count) == 1


def test_outbox_survives_offline_and_does_not_resend_success(service):
    class Offline:
        def call(self, *args, **kwargs):
            raise OSError('offline')
    class Online:
        sent = []
        def call(self, method, payload, **kwargs):
            self.sent.append(payload)
            return {'message_id': 7}
    service.store.out('notice', 123, {'text': 'done'})
    deliver_once(service, Offline())
    with service.store.connect() as db:
        row = db.execute('SELECT * FROM outbox').fetchone()
        assert row['status'] == 'pending' and row['attempts'] == 1
        db.execute('UPDATE outbox SET next_try=0')
    online = Online()
    deliver_once(service, online)
    deliver_once(service, online)
    assert len(online.sent) == 1


def test_report_is_derived_from_completion_and_snapshots_pdf(service):
    run = 'run-test'
    folder = service.root / 'runs' / run
    pdf = folder / 'review.pdf'
    folder.mkdir(parents=True)
    pdf.write_bytes(b'%PDF-1.4\ntest')
    write_json(folder / 'request.json', {'project_name': 'Test', 'replica_roots': []})
    with service.store.connect() as db:
        db.execute('INSERT INTO subscriptions VALUES(?,?)', (run, 123))
    service.collect_reports()
    with service.store.connect() as db:
        assert db.execute('SELECT COUNT(*) FROM outbox').fetchone()[0] == 0
    write_json(folder / 'events/datamanager.done.json', {'status': 'warn', 'replicas_complete': False})
    write_json(folder / 'events/datahelper.done.json', {'status': 'completed',
        'reports': [{'status': 'completed', 'exit_code': 0, 'pdf_path': str(pdf)}]})
    service.collect_reports()
    service.collect_reports()
    with service.store.connect() as db:
        payloads = [json.loads(r[0]) for r in db.execute('SELECT payload FROM outbox')]
    assert len(payloads) == 3
    assert '작업 확인 필요' in payloads[0]['text']
    assert Path(payloads[-1]['document']).parent == folder / 'agent'
    assert payloads[-1]['sha256']


def test_modified_attachment_not_transmitted(service):
    folder = service.root / 'runs' / 'run-test'
    folder.mkdir(parents=True)
    path = folder / 'report.pdf'
    path.write_bytes(b'%PDF secret')
    service.store.out('tampered', 123, {'document': str(path), 'sha256': 'wrong'})
    class RejectCalls:
        def call(self, *args, **kwargs):
            pytest.fail('Changed attachment must not be sent')
    deliver_once(service, RejectCalls())
    with service.store.connect() as db:
        assert db.execute('SELECT status FROM outbox').fetchone()[0] == 'pending'


def test_real_offline_agent_copy_review_and_report(service, monkeypatch):
    import hashlib
    import subprocess
    import time
    from orchestrator import run_state, processes
    from orchestrator.tests.test_real_media_e2e import _write_media
    import shutil
    ffmpeg = shutil.which('ffmpeg')
    assert ffmpeg
    source = Path(service.test_payload['source_path'])
    _write_media(ffmpeg, source / 'A001.mp4')
    monkeypatch.setattr(run_state, 'RUNS_ROOT', service.root / 'runs')
    monkeypatch.setattr(processes, 'LOG_ROOT', service.root / 'logs')
    monkeypatch.setenv('DATA_HANDLER_PIPELINE_ROOT', str(service.root))
    monkeypatch.setenv('HF_HUB_OFFLINE', '1')
    service.starter = None
    plan = service.preview(service.test_payload, 'local')
    result = service.execute(plan['id'], 'local', chat_id=123)
    folder = service.root / 'runs' / result['run_id']
    # Completion artifacts only; never read live progress/logs.
    deadline = time.monotonic() + 45
    done = folder / 'events/datahelper.done.json'
    while not done.is_file() and time.monotonic() < deadline:
        time.sleep(0.25)
    assert done.is_file(), 'DataHelper completion artifact missing'
    review = json.loads(done.read_text())
    assert review['status'] == 'completed', review
    copy = json.loads((folder / 'events/datamanager.done.json').read_text())
    assert copy['replicas_complete'] is True
    expected = hashlib.sha256((source / 'A001.mp4').read_bytes()).hexdigest()
    for dest in plan['destinations']:
        assert hashlib.sha256((Path(dest) / 'A001.mp4').read_bytes()).hexdigest() == expected
    service.collect_reports()
    with service.store.connect() as db:
        rows = [json.loads(r[0]) for r in db.execute('SELECT payload FROM outbox')]
    assert '작업 완료' in rows[0]['text']
    assert any(p.get('document', '').endswith('.pdf') for p in rows)
    # Simulated offline transport must leave complete reports queued.
    class Offline:
        def call(self, *args, **kwargs):
            raise OSError('network disconnected')
    deliver_once(service, Offline())
    with service.store.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM outbox WHERE status='sent'").fetchone()[0] == 0


def test_api_rejects_unauthenticated_mutations(service, monkeypatch):
    from fastapi.testclient import TestClient
    from orchestrator.agent import api
    monkeypatch.setattr(api, 'load_config', lambda: service.config)
    monkeypatch.setattr(api, 'PIPELINE_ROOT', service.root)
    client = TestClient(api.create_app())
    assert client.post('/plans', json=service.test_payload).status_code == 401
    assert client.get('/catalog').status_code == 401
    response = client.post('/plans', headers={'Authorization': 'Bearer test-only'}, json=service.test_payload)
    assert response.status_code == 200
    with service.store.connect() as db:
        assert db.execute('SELECT status FROM plans').fetchone()[0] == 'pending'


def test_inference_factory_health_requires_auth(service, monkeypatch):
    from fastapi.testclient import TestClient
    from orchestrator.agent import inference
    monkeypatch.setattr(inference, 'load_config', lambda: service.config)
    with TestClient(inference.create_app()) as client:
        assert client.get('/health').status_code == 401
        assert client.post('/warmup').status_code == 401
        result = client.get('/health', headers={'Authorization': 'Bearer test-only'})
        assert result.status_code == 200 and result.json()['loaded'] is False


def test_model_offline_gives_actionable_error_without_launch(service, monkeypatch):
    import httpx
    service.config['inference_url'] = 'http://127.0.0.1:8767'
    def fail(*args, **kwargs):
        raise httpx.ConnectError('secret URL must not leak')
    monkeypatch.setattr(httpx.Client, 'post', fail)
    with pytest.raises(ValueError, match='복제는 시작되지 않았습니다') as error:
        service.interpret('복제해줘','local')
    assert 'secret' not in str(error.value)
    assert service.registry.load()['runs'] == []
