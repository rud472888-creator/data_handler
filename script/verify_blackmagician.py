"""Opt-in, real Blackmagician emulator/API -> DIT -> media backup -> agent proof.

Start script/blackmagician_sandbox.mjs first. This only generates and copies its own
tiny media under --output and never discovers or starts work on user media.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
from pathlib import Path
from unittest.mock import patch

import httpx
from fastapi.testclient import TestClient


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    root = args.output.resolve()
    if root.exists():
        raise SystemExit('Choose a fresh output directory; existing verification data is preserved.')
    root.mkdir(parents=True)
    os.environ['DATA_HANDLER_BLACKMAGICIAN_SANDBOX'] = '1'
    os.environ['DATA_HANDLER_PIPELINE_ROOT'] = str(root)
    from orchestrator import cli, datahelper_worker, datamanager_worker, run_state, stages
    from orchestrator.agent.service import AgentService
    from orchestrator.app_front.settings import SettingsStore
    from orchestrator.blackmagician.client import BlackmagicianClient
    from orchestrator.dit_app.server import create_app
    from orchestrator.jsonio import write_json
    from orchestrator.web.registry import ConsoleRegistry

    first, second, source, source2 = [root / name for name in ('replica-one', 'replica-two', 'source-first-card', 'source-second-card')]
    for folder in (first, second, source, source2):
        folder.mkdir()
    for index in range(1, 4):
        folder = source if index < 3 else source2
        subprocess.run([shutil.which('ffmpeg'), '-v', 'error', '-f', 'lavfi', '-i',
            'color=c=blue:s=320x240:r=24', '-t', '0.25', '-c:v', 'libx264', '-pix_fmt', 'yuv420p',
            str(folder / f'A001_C00{index}.mp4')], check=True)
    app = TestClient(create_app(settings_store=SettingsStore(root/'settings.json'),
        registry_path=root/'console-registry.json', runs_root=root/'runs',
        source_roots=(root,), destination_roots=(root,)), base_url='http://127.0.0.1')
    project = app.post('/api/library/projects', json={'name':'Blackmagician 연동 샌드박스'}).json()['project']
    prefix = '/api/blackmagician/projects/' + project['id']
    app.headers['x-dit-blackmagician'] = app.get('/api/blackmagician/session').json()['token']
    response = app.post(prefix+'/connect', json={'mode':'invite','code':'DH11-TEST'})
    assert response.status_code == 200, response.text
    state = response.json()
    assert len(state['snapshot']['entries']) == 3
    assert state['snapshot']['display_fps'] == 23.98
    assert state['snapshot']['script']['sceneInfo'] == '데이터핸들러 전달 확인: 창가 장면'
    evidence = {'sandbox': True, 'firebase_project': 'demo-datahandler-blackmagician',
        'remote_project_id': 'datahandler-sandbox-20260911', 'session_id': 'DH-SANDBOX-0911',
        'invitation': 'DH11-TEST', 'local_project_id': project['id'], 'web_initial': state['snapshot'], 'runs': []}

    def backup(folder):
        payload = {'project_id':project['id'],'shoot_date':'2026-09-11','camera_unit':'A',
            'source_path':str(folder),'replica_roots':[str(first),str(second)]}
        assert app.post('/api/roll-preview', json=payload).status_code == 200
        # Run the actual engines synchronously on these generated fixtures.
        with patch.object(run_state, 'RUNS_ROOT', root/'runs'), patch.object(cli, 'spawn_python_module', return_value=1), patch.object(stages, 'spawn_python_module', return_value=1):
            started = app.post('/api/runs', json=payload)
            assert started.status_code == 200, started.text
            run_id = started.json()['run_id']
            copied = datamanager_worker.run_datamanager(run_id)
            assert copied['status'] == 'completed' and copied['replicas_complete']
            helper = datahelper_worker.run_datahelper(run_id)
            assert helper['status'] == 'completed', helper
        evidence['runs'].append({'run_id': run_id, 'source': str(folder), 'completion':copied})

    backup(source)
    missing = app.post(prefix+'/review').json()['review']
    assert missing['counts']['verified'] == 2 and missing['counts']['missing'] == 1, missing
    evidence['missing_clip_review'] = missing
    agent = AgentService(root, {})
    answer = agent.interpret('/backup-review', 'desktop:sandbox', project_id=project['id'])
    assert 'A001_C003' in answer['text'] and answer['backup_review']['counts']['missing'] == 1
    evidence['agent_missing_clip_response'] = answer

    backup(source2)
    all_backed = app.post(prefix+'/review').json()['review']
    assert all_backed['status'] == 'verified' and all_backed['counts']['verified'] == 3, all_backed
    evidence['all_clips_review'] = all_backed
    # First run evidence survives the second card replacing the engine manifest.
    assert all(Path(r['completion_artifact']).is_file() for c in all_backed['clips'] for r in c['evidence'])
    unavailable = Path(all_backed['clips'][0]['evidence'][0]['replicas'][1]['path'])
    parked = unavailable.with_suffix('.temporarily-unavailable')
    unavailable.rename(parked)
    try:
        result = app.post(prefix+'/review').json()['review']
        assert result['counts']['unavailable'] == 1 and result['status'] == 'review_needed'
        evidence['missing_replica_review'] = result
    finally:
        parked.rename(unavailable)

    firestore = BlackmagicianClient()
    base = firestore.firestore_url + '/projects/datahandler-sandbox-20260911'
    session = base + '/sessions/DH-SANDBOX-0911'
    with httpx.Client(trust_env=False) as remote:
        # Old memo edit and full snapshot replacement, including actual deletion.
        entries = [session+'/scriptEntries/legacy-document-1', base+'/takeRecords/dh-take-1']
        for url in entries:
            remote.patch(url, params={'updateMask.fieldPaths':'sceneInfo'}, json={'fields':{'sceneInfo':{'stringValue':'과거 메모 수정 전달 확인'}}}).raise_for_status()
        updated = app.post(prefix+'/refresh').json()['snapshot']
        assert next(e for e in updated['entries'] if e['data']['takeId']=='dh-take-1')['data']['sceneInfo'] == '과거 메모 수정 전달 확인'
        evidence['memo_update_received'] = True
        url = session+'/scriptEntries/legacy-document-3'
        original = remote.get(url).json()
        remote.delete(url).raise_for_status()
        try:
            deleted = app.post(prefix+'/refresh').json()['snapshot']
            assert len(deleted['entries']) == 2
            evidence['deleted_entry_removed'] = True
        finally:
            remote.patch(url, json={'fields':original['fields']}).raise_for_status()
        for url in entries:
            remote.patch(url, params={'updateMask.fieldPaths':'sceneInfo'}, json={'fields':{'sceneInfo':{'stringValue':'첫 테이크'}}}).raise_for_status()
        # Ended session history can still be loaded using the documented ID route.
        remote.patch(session, params={'updateMask.fieldPaths':'isSessionEnded'}, json={'fields':{'isSessionEnded':{'booleanValue':True}}}).raise_for_status()
        try:
            response = app.post(prefix+'/connect', json={'mode':'session','code':'DH-SANDBOX-0911'})
            assert response.status_code == 200, response.text
            ended = response.json()['snapshot']
            assert ended['camera']['isSessionEnded'] and len(ended['entries']) == 3 and not ended['conflicts']
            evidence['ended_history_received'] = True
        finally:
            remote.patch(session, params={'updateMask.fieldPaths':'isSessionEnded'}, json={'fields':{'isSessionEnded':{'booleanValue':False}}}).raise_for_status()
    firestore.close()
    final = app.post(prefix+'/refresh').json()
    assert len(final['snapshot']['entries']) == 3
    final = app.post(prefix+'/review').json()
    assert final['review']['status'] == 'verified'
    evidence['final_state'] = final
    evidence['agent_final_response'] = agent.interpret('/backup-review', 'desktop:sandbox', project_id=project['id'])
    write_json(root/'verification.json', evidence)
    print(json.dumps({'result':'PASS','local_project_id':project['id'],'clips':3,'replicas':2,
        'checks':['invite API','session ID REST','Korean script','23.98 fps','mirror dedup','two real media backup runs',
        'missing clip','missing replica','agent evidence','old memo edit','deletion replacement','ended history'],
        'evidence':str(root/'verification.json')}, ensure_ascii=False))


if __name__ == '__main__':
    main()
