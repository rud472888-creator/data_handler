"""Exercise arbitrary destination counts through the same paths used by the app."""
import copy
import hashlib
import shutil
import subprocess
from pathlib import Path

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from orchestrator import cli, datahelper_worker, datamanager_worker, run_state, stages
from orchestrator.agent.service import AgentService
from orchestrator.agent.review_evidence import copy_review
from orchestrator.blackmagician.review import file_evidence
from orchestrator.jsonio import read_json
from orchestrator.tests.test_dit_workspace import client
from orchestrator.web.server import _selected_replica_roots


@pytest.mark.parametrize('count', [1, 2, 100])
def test_workspace_copies_verifies_and_reports_every_destination(tmp_path, monkeypatch, count):
    source = tmp_path / 'card'
    source.mkdir()
    roots = [tmp_path / f'backup-{i}' for i in range(count)]
    for root in roots:
        root.mkdir()
    subprocess.run([shutil.which('ffmpeg'), '-v', 'error', '-f', 'lavfi', '-i',
        'color=c=blue:s=160x120:r=24', '-t', '0.125', '-c:v', 'libx264',
        '-pix_fmt', 'yuv420p', str(source / 'A001.mp4')], check=True)
    monkeypatch.setattr(run_state, 'RUNS_ROOT', tmp_path / 'runs')
    # The workers are called synchronously below; no production/background jobs.
    monkeypatch.setattr(cli, 'spawn_python_module', lambda *args: 1)
    monkeypatch.setattr(stages, 'spawn_python_module', lambda *args: 1)
    app = client(tmp_path)
    project = app.post('/api/library/projects', json={'name': 'Multi backup'}).json()['project']
    payload = dict(project_id=project['id'], shoot_date='2026-09-14', camera_unit='A',
                   source_path=str(source), replica_roots=list(map(str, roots)))
    preview = app.post('/api/roll-preview', json=payload)
    assert preview.status_code == 200, preview.text
    assert preview.json()['replica_destinations'] == [str(r / 'Multi backup/001_Footage/R#1') for r in roots]
    response = app.post('/api/runs', json=payload)
    assert response.status_code == 200, response.text
    run_id = response.json()['run_id']
    folder = tmp_path / 'runs' / run_id
    request = read_json(folder / 'request.json')
    assert request['replica_roots'] == payload['replica_roots']
    done = datamanager_worker.run_datamanager(run_id)
    assert done['replicas_complete'] is True
    assert done['replica_count'] == count
    assert len(done['replica_path_ids']) == count
    original = hashlib.sha256((source / 'A001.mp4').read_bytes()).hexdigest()
    for root in roots:
        assert hashlib.sha256((root / 'Multi backup/001_Footage/R#1/A001.mp4').read_bytes()).hexdigest() == original
    manifest = read_json(folder / 'blackmagician/manifest.json')
    item = manifest['files'][0]
    assert file_evidence(item, done, request, folder)[0] == 'verified'
    assert copy_review(folder)['status'] == 'verified'
    incomplete = copy.deepcopy(item)
    incomplete['replica_results'].pop()
    assert file_evidence(incomplete, done, request, folder)[0] == 'unverified'
    bad_checksum = copy.deepcopy(item)
    bad_checksum['replica_results'][-1]['checksum'] = '0' * 64
    assert file_evidence(bad_checksum, done, request, folder)[0] == 'unverified'
    report = datahelper_worker.run_datahelper(run_id)
    assert report['status'] == 'completed', report
    assert len(report['reports']) == count
    cards = app.get(f'/api/library/projects/{project["id"]}/cards').json()['cards']
    assert cards[0]['verified'] is True and cards[0]['phase'] == 'reported'
    assert len(cards[0]['destinations']) == count
    pdfs = [a for a in cards[0]['artifacts'] if a['path'].endswith('.pdf')]
    assert len(pdfs) == count + 1
    for pdf in pdfs:
        download = app.get(pdf['url'])
        assert download.status_code == 200 and download.content.startswith(b'%PDF')


@pytest.mark.parametrize('count', [1, 2, 100, 101])
def test_agent_plan_preserves_all_destinations_through_execution(tmp_path, count):
    source = tmp_path / 'card'
    source.mkdir()
    roots = [tmp_path / f'backup-{i}' for i in range(count)]
    for root in roots:
        root.mkdir()
    called = []
    service = AgentService(tmp_path / 'pipeline', {'allowed_roots': [str(tmp_path)]},
                           starter=lambda plan, run: called.append(plan))
    service.registry.save({'projects': [{'id': 'p', 'name': 'Film', 'replica_roots': [],
        'replica_project_roots': [], 'preset_name': 'dit', 'created_at': '', 'updated_at': ''}], 'runs': []})
    payload = dict(project_id='p', source_path=str(source), replica_paths=list(map(str, roots)),
                   shoot_date='2026-09-14', camera_unit='A')
    plan = service.preview(payload, 'local')
    assert plan['replica_paths'] == payload['replica_paths']
    assert len(plan['destinations']) == count
    assert service.execute(plan['id'], 'local')['status'] == 'started'
    assert called[0]['replica_paths'] == payload['replica_paths']
    with pytest.raises(ValidationError):
        service.preview({**payload, 'replica_paths': []}, 'local')
    with pytest.raises(ValueError, match='겹치면'):
        service.preview({**payload, 'replica_paths': [str(roots[0]), str(roots[0])]}, 'local')


@pytest.mark.parametrize('requested', [[], [''], ['   '], ['first', 'first/.']])
def test_invalid_destination_list_never_falls_back_to_project_defaults(tmp_path, requested):
    with pytest.raises(HTTPException) as exc:
        _selected_replica_roots({'replica_roots': [str(tmp_path)]}, requested)
    assert exc.value.status_code == 400


def test_omitted_destinations_keep_legacy_project_defaults(tmp_path):
    assert _selected_replica_roots({'replica_roots': [str(tmp_path)]}, None) == (tmp_path,)
