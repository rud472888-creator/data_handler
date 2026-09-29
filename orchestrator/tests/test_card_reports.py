"""Every card keeps its own reports; a later card never replaces an earlier one."""
import shutil
import subprocess

import pytest

from orchestrator import cli, datahelper_worker, datamanager_worker, run_state, stages
from orchestrator.jsonio import read_json
from orchestrator.tests.test_dit_workspace import client

pytestmark = pytest.mark.skipif(not shutil.which('ffmpeg'), reason='ffmpeg is required')


def _card(folder, color):
    folder.mkdir()
    subprocess.run([shutil.which('ffmpeg'), '-v', 'error', '-f', 'lavfi', '-i',
                    f'color=c={color}:s=160x120:r=24', '-t', '0.125', '-c:v', 'libx264',
                    '-pix_fmt', 'yuv420p', str(folder / f'{color}.mp4')], check=True)
    return folder


def test_second_card_keeps_first_card_reports(tmp_path, monkeypatch):
    backups = [tmp_path / 'backup-a', tmp_path / 'backup-b']
    for root in backups:
        root.mkdir()
    monkeypatch.setattr(run_state, 'RUNS_ROOT', tmp_path / 'runs')
    monkeypatch.setattr(cli, 'spawn_python_module', lambda *args: 1)
    monkeypatch.setattr(stages, 'spawn_python_module', lambda *args: 1)
    app = client(tmp_path)
    project = app.post('/api/library/projects', json={'name': 'Night'}).json()['project']
    runs = []
    for color in ('red', 'blue'):
        payload = dict(project_id=project['id'], shoot_date='2026-09-14', camera_unit='A',
                       source_path=str(_card(tmp_path / color, color)),
                       replica_roots=list(map(str, backups)))
        run_id = app.post('/api/runs', json=payload).json()['run_id']
        done = datamanager_worker.run_datamanager(run_id)
        assert done['replicas_complete'] is True
        assert datahelper_worker.run_datahelper(run_id)['status'] == 'completed'
        runs.append((run_id, done))

    (first, first_done), (second, second_done) = runs
    assert first_done['card_report_relpath'] == '00_Master/reports/R#1'
    assert second_done['card_report_relpath'] == '00_Master/reports/R#2'
    assert first_done['reports']['checksum_pdf'] != second_done['reports']['checksum_pdf']
    # Every backup drive carries the card's own checksum report and manifest.
    for root in backups:
        for roll, (_, done) in zip(('R#1', 'R#2'), runs):
            folder = root / 'Night/00_Master/reports' / roll
            assert (folder / 'checksum.pdf').read_bytes().startswith(b'%PDF')
            assert read_json(folder / 'manifest.json')['job_id'] == done['job_id']
    first_report = read_json(tmp_path / 'runs' / first / 'events/datahelper.done.json')
    clip = read_json(tmp_path / 'runs' / first / 'agent/report-inputs/path1.json')['clips'][0]
    assert 'red' in clip['clip']['source_path']
    assert all('/R#1/' in r['pdf_path'] for r in first_report['reports'])

    # The chain closes locally without an external watcher.
    for run_id in (first, second):
        assert (tmp_path / 'runs' / run_id / 'final-report.md').is_file()
        assert read_json(tmp_path / 'runs' / run_id / 'state.json')['stage'] == 'done'

    cards = {c['run_id']: c for c in app.get(f'/api/library/projects/{project["id"]}/cards').json()['cards']}
    first_pdfs = sorted(a['path'] for a in cards[first]['artifacts'] if a['path'].endswith('.pdf'))
    second_pdfs = sorted(a['path'] for a in cards[second]['artifacts'] if a['path'].endswith('.pdf'))
    assert len(first_pdfs) == 3 and not set(first_pdfs) & set(second_pdfs)

    # The shooting-day DIT report summarizes both cards and travels with every backup.
    created = app.post(f'/api/library/projects/{project["id"]}/dit-report', json={'shoot_date': '2026-09-14'})
    assert created.status_code == 200, created.text
    body = created.json()
    assert body['summary']['cards'] == 2 and body['summary']['verified'] == 2
    assert sorted(body['saved_to']) == [str(root / 'Night/00_Master/reports/DIT_Report_2026-09-14.pdf') for root in backups]
    pdf = app.get(body['url'])
    assert pdf.status_code == 200 and pdf.content.startswith(b'%PDF')
    assert app.post(f'/api/library/projects/{project["id"]}/dit-report', json={'shoot_date': '2026-09-15'}).status_code == 404
    assert app.post(f'/api/library/projects/{project["id"]}/dit-report', json={'shoot_date': '../x'}).status_code == 400


def test_collector_skips_settled_runs_and_list_omits_findings(tmp_path):
    from orchestrator.agent.reviews import ReviewCollector
    from orchestrator.jsonio import write_json

    runs = tmp_path / 'runs'
    folder = runs / 'run-a'
    write_json(folder / 'request.json', {'project_name': 'P', 'replica_roots': [str(tmp_path / 'gone')]})
    write_json(folder / 'events/datamanager.done.json', {'status': 'completed', 'replicas_complete': True})
    collector = ReviewCollector(tmp_path, runs, inference=lambda *a: 'x')
    calls = []
    original = collector.review
    collector.review = lambda *args: calls.append(args[2]) or original(*args)
    collector.collect_once()
    assert sorted(calls) == ['copy', 'shooting']
    collector.collect_once()
    assert len(calls) == 2  # unchanged inputs are not reviewed again
    write_json(folder / 'events/datamanager.done.json', {'status': 'completed', 'replicas_complete': True, 'x': 1})
    collector.collect_once()
    assert len(calls) == 4

    app = client(tmp_path)
    project = app.post('/api/library/projects', json={'name': 'P'}).json()['project']
    registry = read_json(tmp_path / 'registry.json')
    registry['runs'].append({'project_id': project['id'], 'run_id': 'run-a', 'roll': 'R#1',
                             'shoot_date': '2026-09-14', 'camera_unit': 'A', 'source_path': '/x'})
    write_json(tmp_path / 'registry.json', registry)
    card = app.get(f'/api/library/projects/{project["id"]}/cards').json()['cards'][0]
    copy = next(r for r in card['agent_reviews'] if r['phase'] == 'copy')
    assert copy['finding_count'] > 0 and copy['findings'] == []
    detail = app.get('/api/library/cards/run-a/reviews').json()['agent_reviews']
    assert len(next(r for r in detail if r['phase'] == 'copy')['findings']) == copy['finding_count']
    assert app.get('/api/library/cards/run-missing/reviews').status_code == 404
