import copy
import hashlib
import json
import sys
import threading
import types
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from orchestrator.agent.review_evidence import copy_review, report_review, reel_review
from orchestrator.agent.reviews import ReviewCollector, request_retry, review_messages, model_review
from orchestrator.blackmagician.review import read_object
from orchestrator.jsonio import write_json
from orchestrator.run_state import utc_now
from orchestrator.web.registry import ConsoleRegistry


@pytest.fixture
def completed(tmp_path):
    root = tmp_path / 'pipeline'
    folder = root / 'runs/run-review'
    roots = {f'path{i}': str(tmp_path / f'backup{i}/Film') for i in (1, 2)}
    digest = hashlib.sha256(b'media').hexdigest()
    replicas = []
    for i in (1, 2):
        path = Path(roots[f'path{i}']) / '001_Footage/R#1/A001_C001.mov'
        path.parent.mkdir(parents=True)
        path.write_bytes(b'media')
        replicas.append(dict(path_id=f'dest{i}', dest_relpath='001_Footage/R#1/A001_C001.mov',
                             status='verified', checksum=digest))
    item = dict(file_id='f1', job_id='job1', source_path_id='src1', source_relpath='A001_C001.mov',
                size_bytes=5, checksum_source=digest, status='verified', replica_results=replicas)
    dm = dict(job_id='job1', run_id=folder.name, status='completed', replicas_complete=True,
        file_count=1, replica_count=2, replica_path_ids=['dest1','dest2'],
        replica_project_roots=roots, finished_at=utc_now())
    request = dict(run_id=folder.name, project_name='Film', source_path=str(tmp_path/'card'),
                   replica_roots=[str(Path(r).parent) for r in roots.values()])
    write_json(folder/'request.json', request)
    write_json(folder/'events/datamanager.done.json', dm)
    write_json(folder/'blackmagician/manifest.json', dict(job_id='job1', files=[item]))
    reports = []
    for label, destination in roots.items():
        input_path = Path(destination)/'001_Footage/R#1'
        path = folder/'agent/report-inputs'/f'{label}.json'
        data = dict(summary=dict(total_clips=1, success_count=1, status='success'), clips=[dict(
            clip=dict(clip_name='A001_C001.mov', source_path=str(input_path/'A001_C001.mov')),
            status='success', warnings=[], errors=[], captures=[dict(status='success', label='Start')])])
        write_json(path, data)
        reports.append(dict(label=label, input_path=str(input_path), review_json_path=str(path),
            json_path=str(path), pdf_path=str(path.with_suffix('.pdf')), exit_code=0, status='completed', missing_artifacts=[]))
    write_json(folder/'events/datahelper.done.json', dict(status='completed', reports=reports, finished_at=utc_now()))
    record = dict(run_id=folder.name, project_id='local', camera_unit='A', shoot_date='2026-09-12', roll='R#1')
    registry = ConsoleRegistry(root/'console-registry.json')
    registry.save(dict(projects=[dict(id='local', name='Film')], runs=[record]))
    entry = dict(key='p/s/t1', paths=['p/s/scriptEntries/t1'], conflicts=[], data=dict(
        clipName='A001_C001', shootDayKey='20260912', cameraId='A', reel='A001'))
    public = dict(connection=dict(status='connected', session_id='s', project_id='p'),
        snapshot=dict(entries=[entry], complete=True, from_cache=False, fetched_at=utc_now()))
    write_json(root/'blackmagician/local/state.json', public)
    return root, folder, record, public


def test_all_three_reviews_pass_on_complete_evidence(completed):
    root, folder, record, public = completed
    assert copy_review(folder)['status'] == 'verified'
    assert report_review(folder)['status'] == 'verified'
    review = reel_review(folder, record, public)
    assert review['status'] == 'verified'
    assert review['scope']['reel'] == 'A001'


@pytest.mark.parametrize('fault', ['missing', 'size', 'checksum', 'duplicate', 'wrong_root', 'extra_replica', 'count', 'job', 'manifest'])
def test_copy_review_never_passes_incomplete_evidence(completed, fault):
    _, folder, _, _ = completed
    dm = read_object(folder/'events/datamanager.done.json')
    manifest = read_object(folder/'blackmagician/manifest.json')
    item = manifest['files'][0]
    replica = item['replica_results'][0]
    dest = Path(dm['replica_project_roots']['path1'])/replica['dest_relpath']
    if fault == 'missing': dest.unlink()
    if fault == 'size': dest.write_bytes(b'bad')
    if fault == 'checksum': replica['checksum'] = '0'*64
    if fault == 'duplicate': manifest['files'].append(copy.deepcopy(item)); dm['file_count'] = 2
    if fault == 'wrong_root': dm['replica_project_roots']['path2'] = dm['replica_project_roots']['path1']
    if fault == 'extra_replica': item['replica_results'].append(copy.deepcopy(replica))
    if fault == 'count': dm['file_count'] = 2
    if fault == 'job': item['job_id'] = 'different-card'
    if fault == 'manifest': manifest = {}
    write_json(folder/'blackmagician/manifest.json', manifest)
    write_json(folder/'events/datamanager.done.json', dm)
    review = copy_review(folder)
    assert review['status'] == 'review_needed'
    assert all(f['action'] and f['cause'] and f['evidence'] for f in review['findings'])


@pytest.mark.parametrize('fault', ['decode', 'dependency', 'warning', 'capture', 'count', 'snapshot', 'identity', 'missing_clip', 'exit'])
def test_report_diagnoses_content_even_after_exit_zero(completed, fault):
    _, folder, _, _ = completed
    path = folder/'agent/report-inputs/path1.json'
    data = read_object(path)
    clip = data['clips'][0]
    if fault == 'decode': clip['captures'][0].update(status='decode_failed', errors=['invalid data'])
    if fault == 'dependency': clip.update(status='dependency_missing', errors=['BRAW SDK not found'])
    if fault == 'warning': clip['warnings'] = ['timecode is unavailable']
    if fault == 'capture': clip['captures'] = []
    if fault == 'count': data['summary']['total_clips'] = 10
    if fault == 'identity': clip['clip']['source_path'] = '/another/card/A001_C001.mov'
    if fault == 'missing_clip': clip['clip']['source_path'] = clip['clip']['source_path'].replace('C001', 'C002')
    write_json(path, data)
    if fault == 'snapshot':
        path.unlink()
        # A later card's report must not replace the missing preserved report.
        dh = read_object(folder/'events/datahelper.done.json')
        dh['reports'][0]['json_path'] = dh['reports'][1]['json_path']
        write_json(folder/'events/datahelper.done.json', dh)
    if fault == 'exit':
        dh = read_object(folder/'events/datahelper.done.json')
        dh['reports'][0].update(exit_code=1, status='failed', stderr='Permission denied')
        write_json(folder/'events/datahelper.done.json', dh)
    review = report_review(folder)
    assert review['status'] == 'review_needed'
    assert review['findings']
    if fault == 'dependency': assert any('SDK' in f['action'] for f in review['findings'])
    if fault == 'decode': assert any('제조사' in f['action'] for f in review['findings'])


def test_shooting_scope_excludes_other_days_cameras_reels_and_detects_missing(completed):
    _, folder, record, public = completed
    entry = public['snapshot']['entries'][0]
    for field, value in [('shootDayKey','20260913'), ('cameraId','B'), ('reel','A002')]:
        other = copy.deepcopy(entry)
        other['key'] = field
        other['data'].update(clipName='OTHER', **{field: value})
        public['snapshot']['entries'].append(other)
    assert reel_review(folder, record, public)['status'] == 'verified'
    missing = copy.deepcopy(entry)
    missing['key'] = 'p/s/t2'
    missing['data']['clipName'] = 'A001_C002'
    public['snapshot']['entries'].append(missing)
    review = reel_review(folder, record, public)
    assert review['status'] == 'review_needed'
    assert review['counts']['total'] == 2
    assert review['findings'][0]['file'] == 'A001_C002'


def test_future_record_does_not_become_missing_and_unknown_scope_blocks_pass(completed):
    _, folder, record, public = completed
    other = copy.deepcopy(public['snapshot']['entries'][0])
    other['key'] = 'future'
    other['data'].update(clipName='FUTURE', createdAt='2099-09-12T00:00:00Z')
    public['snapshot']['entries'].append(other)
    review = reel_review(folder, record, public)
    assert review['status'] == 'verified' and review['excluded_after_completion'] == 1
    del other['data']['createdAt']
    del other['data']['reel']
    assert reel_review(folder, record, public)['status'] == 'review_needed'


@pytest.mark.parametrize('fault', ['stale','scope','reused','conflict','duplicate','unconnected','incomplete'])
def test_shooting_uncertainty_never_passes(completed, fault):
    _, folder, record, public = completed
    entry = public['snapshot']['entries'][0]
    if fault == 'stale': public['snapshot']['from_cache'] = True
    if fault == 'scope': del entry['data']['reel']
    if fault == 'reused':
        other = copy.deepcopy(entry); other['data']['reel'] = 'A002'
        public['snapshot']['entries'].append(other)
    if fault == 'duplicate': public['snapshot']['entries'].append(copy.deepcopy(entry))
    if fault == 'conflict': entry['conflicts'] = [{'field':'reel'}]
    if fault == 'unconnected': public['connection'] = None
    if fault == 'incomplete': public['snapshot']['complete'] = False
    assert reel_review(folder, record, public)['status'] != 'verified'


def test_collector_new_context_per_phase_retry_and_restart(completed):
    root, folder, _, _ = completed
    write_json(root/'agent/config.json', dict(inference_url='http://127.0.0.1:8767', api_token='test'))
    calls = []
    def infer(config, session, phase, evidence):
        calls.append((session, phase, copy.deepcopy(evidence)))
        return f'{phase} 근거를 확인했습니다.'
    collector = ReviewCollector(root, inference=infer)
    collector.collect_once()
    assert len(calls) == len(set(c[0] for c in calls)) == 3
    for phase in ('copy','report','shooting'):
        review = read_object(folder/f'agent/reviews/{phase}.json')
        assert review['engine'] == 'local_model' and review['history_used'] is False
        request = read_object(Path(review['artifact']).with_name('request.json'))
        assert request['history'] == []
    collector.collect_once()
    ReviewCollector(root, inference=infer).collect_once()
    assert len(calls) == 3
    request_retry(folder, ['copy'])
    assert review_messages(folder)[0]['state'] == 'pending'
    collector.collect_once()
    assert len(calls) == len(set(c[0] for c in calls)) == 4
    assert calls[-1][1] == 'copy'
    assert 'analysis' not in calls[-1][2]
    assert len(list((folder/'agent/reviews/sessions').iterdir())) == 4


def test_model_failure_keeps_evidence_and_failed_session_is_retryable(completed):
    root, folder, record, _ = completed
    write_json(root/'agent/config.json', dict(inference_url='http://127.0.0.1:8767', api_token='test'))
    def offline(*args): raise TimeoutError('do not expose secret transport URL')
    collector = ReviewCollector(root, inference=offline)
    first = collector.review(folder, record, 'copy')
    assert first['status'] == 'verified' and first['engine'] == 'evidence'
    assert first['model_error'] == 'TimeoutError'
    assert 'secret transport' not in json.dumps(first)
    # Simulate interrupted generation: no completed revision means fresh replay.
    first['state'] = 'running'
    write_json(folder/'agent/reviews/copy.json', first)
    second = collector.review(folder, record, 'copy')
    assert second['session_id'] != first['session_id']


def test_two_collectors_do_not_generate_the_same_review(completed):
    root, folder, record, _ = completed
    write_json(root/'agent/config.json', dict(inference_url='http://127.0.0.1:8767', api_token='test'))
    entered, release = threading.Event(), threading.Event()
    def infer(*args): entered.set(); release.wait(5); return '확인'
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(ReviewCollector(root, inference=infer).review, folder, record, 'copy')
        assert entered.wait(3)
        second = pool.submit(ReviewCollector(root, inference=infer).review, folder, record, 'copy')
        assert second.result(timeout=3) is None
        release.set()
        assert first.result(timeout=3)['state'] == 'completed'


def test_no_review_before_completion(tmp_path):
    folder = tmp_path/'runs/active'
    write_json(folder/'progress.json', dict(status='completed'))
    ReviewCollector(tmp_path).collect_once()
    assert not (folder/'agent/reviews').exists()


def test_isolated_inference_rejects_history_and_builds_fresh_prompts(monkeypatch):
    from orchestrator.agent import inference
    monkeypatch.setattr(inference, 'load_config', lambda: dict(api_token='token',model_path='test'))
    prompts = []
    class Tokenizer:
        def encode(self, text): return list(range(100))
    processor = Tokenizer()
    fake = types.ModuleType('mlx_vlm')
    fake.load = lambda *a: (types.SimpleNamespace(config={}), processor)
    fake.generate = lambda *a, **kw: types.SimpleNamespace(text='{"analysis":"파일 근거 확인"}')
    core = types.ModuleType('mlx.core')
    core.set_memory_limit = core.set_cache_limit = lambda *a: None
    prompt_utils = types.ModuleType('mlx_vlm.prompt_utils')
    def template(processor, config, messages, **kw):
        prompts.append(messages)
        return json.dumps(messages)
    prompt_utils.apply_chat_template = template
    monkeypatch.setitem(sys.modules, 'mlx', types.ModuleType('mlx'))
    monkeypatch.setitem(sys.modules, 'mlx.core', core)
    monkeypatch.setitem(sys.modules, 'mlx_vlm', fake)
    monkeypatch.setitem(sys.modules, 'mlx_vlm.prompt_utils', prompt_utils)
    client = TestClient(inference.create_app())
    headers = {'Authorization':'Bearer token'}
    one = dict(session_id=uuid4().hex, phase='copy', evidence={'summary':'CARD_ONE secret'})
    assert client.post('/review', json=one).status_code == 401
    assert client.post('/review', json={**one, 'history':[{'text':'pollution'}]}, headers=headers).status_code == 422
    assert client.post('/review', json=one, headers=headers).json()['session_id'] == one['session_id']
    two = dict(session_id=uuid4().hex, phase='report', evidence={'summary':'CARD_TWO'})
    assert client.post('/review', json=two, headers=headers).status_code == 200
    assert len(prompts) == 2 and all(len(p) == 2 for p in prompts)
    assert 'CARD_ONE' not in json.dumps(prompts[1]) and 'pollution' not in json.dumps(prompts)


def test_model_transport_is_bounded_and_rejects_another_session(monkeypatch):
    import httpx
    captured = []
    real_client = httpx.Client
    mismatch = [False]
    def handler(request):
        data = json.loads(request.content)
        captured.append(data)
        return httpx.Response(200, json=dict(analysis='확인', session_id=uuid4().hex if mismatch[0] else data['session_id']))
    monkeypatch.setattr(httpx, 'Client', lambda **kw: real_client(transport=httpx.MockTransport(handler), **kw))
    evidence = dict(status='review_needed', summary='1000 errors', findings=[dict(evidence='x'*2000, cause='c'*2000, action='a'*2000)]*1000)
    config = dict(inference_url='http://127.0.0.1:8895', api_token='test')
    assert model_review(config, uuid4().hex, 'report', evidence) == '확인'
    data = captured[0]
    assert set(data) == {'session_id','phase','evidence'}
    assert len(json.dumps(data['evidence'], ensure_ascii=False)) <= 16000
    assert len(data['evidence']['findings']) + data['evidence']['findings_omitted'] == 1000
    mismatch[0] = True
    with pytest.raises(ValueError): model_review(config, uuid4().hex, 'copy', evidence)


def test_workspace_serves_reviews_retry_and_attention_without_agent_daemon(completed):
    from orchestrator.dit_app.server import create_app, card_snapshot
    from orchestrator.app_front.settings import SettingsStore
    root, folder, record, _ = completed
    ReviewCollector(root).collect_once()
    dm = read_object(folder/'events/datamanager.done.json')
    (Path(dm['replica_project_roots']['path1'])/'001_Footage/R#1/A001_C001.mov').unlink()
    request_retry(folder, ['copy'])
    ReviewCollector(root).collect_once()
    card = card_snapshot(record, root/'runs')
    assert card['phase'] == 'review' and card['verified'] is True
    client = TestClient(create_app(registry_path=root/'console-registry.json', runs_root=root/'runs',
        settings_store=SettingsStore(root/'settings.json'), source_roots=(root,), destination_roots=(root,)),
        base_url='http://127.0.0.1')
    assert 'reviewMessages' in client.get('/').text
    url = '/api/agent/reviews/run-review'
    assert client.get(url+'/copy').status_code == 200
    assert client.get(url+'/bad').status_code == 404
    assert client.post(url+'/retry', json={'phases':['copy']}).status_code == 401
    token = client.get('/api/agent/session').json()['token']
    headers = {'X-DIT-Agent':token}
    assert client.post(url+'/retry', json={'phases':['copy']}, headers=headers).status_code == 200
    assert client.post(url+'/retry', json={'phases':['invalid']}, headers=headers).status_code == 409
    assert client.post(url+'/retry', json={'phases':['copy']}, headers={**headers,'Origin':'https://evil.test'}).status_code == 403


def test_real_media_review_and_preserved_report(tmp_path, monkeypatch):
    # Use the existing actual copy + FrameProof + PDF flow, then review its output.
    from orchestrator.tests.test_dit_workspace import test_real_card_copy_and_pdf_through_workspace
    test_real_card_copy_and_pdf_through_workspace(tmp_path, monkeypatch)
    folder = next((tmp_path/'runs').iterdir())
    assert copy_review(folder)['status'] == 'verified'
    review = report_review(folder)
    assert review['counts']['reports'] == 2
    assert not any(f['code'] in {'report_content','report_identity','unreviewed_clip'} for f in review['findings'])
    dh = read_object(folder/'events/datahelper.done.json')
    for report in dh['reports']:
        assert Path(report['review_json_path']).is_file()
        Path(report['json_path']).write_text('{"next_card": true}')
    assert report_review(folder) == review


def test_failed_helper_launch_still_publishes_reviewable_completion(completed, monkeypatch):
    from orchestrator import datahelper_worker, run_state
    from orchestrator.spec import RunSpec
    root, folder, _, _ = completed
    source = root/'card'; source.mkdir()
    dm = read_object(folder/'events/datamanager.done.json')
    spec = RunSpec(run_id=folder.name, project_name='Film', source_path=source,
                   replica_roots=tuple(Path(p).parent for p in dm['replica_project_roots'].values()))
    monkeypatch.setattr(run_state, 'RUNS_ROOT', root/'runs')
    run_state.save_spec(spec)
    def fail(**kwargs): raise PermissionError('decoder Permission denied')
    monkeypatch.setattr(datahelper_worker, '_run_one', fail)
    result = datahelper_worker.run_datahelper(folder.name)
    assert result['status'] == 'failed'
    review = report_review(folder)
    assert review['status'] == 'review_needed'
    assert any('권한' in f['action'] for f in review['findings'])
