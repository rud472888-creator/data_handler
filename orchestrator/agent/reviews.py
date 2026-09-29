"""Completion-artifact inbox with isolated, durable review sessions.

The collector only observes *.done.json, never engine progress. A lock and input
revision deduplicate desktop/daemon collectors; a crash is retried in a new session.
"""
from __future__ import annotations

import fcntl
import hashlib
import json
import logging
import threading
from pathlib import Path
from uuid import uuid4

import httpx

from orchestrator.agent.config import private_json
from orchestrator.agent.review_evidence import copy_review, report_review, reel_review, finding, result
from orchestrator.blackmagician.review import read_object
from orchestrator.blackmagician.service import public_state
from orchestrator.run_state import utc_now
from orchestrator.web.registry import ConsoleRegistry

PHASES = {'copy': 'datamanager', 'report': 'datahelper', 'shooting': 'datamanager'}
TITLES = {'copy': '복제 검토', 'report': '보고서 검토', 'shooting': '촬영 기록 대조'}
log = logging.getLogger(__name__)


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


_MESSAGES = {}
_MESSAGES_LIMIT = 2048


def review_messages(folder):
    """Saved review messages for a run, re-read only when their inputs change."""
    folder = Path(folder)
    signature = ReviewCollector._inputs(folder)
    cached = _MESSAGES.get(folder)
    if cached and cached[0] == signature:
        return cached[1]
    messages = _read_review_messages(folder)
    if len(_MESSAGES) >= _MESSAGES_LIMIT:
        _MESSAGES.clear()
    _MESSAGES[folder] = (signature, messages)
    return messages


def _read_review_messages(folder):
    messages = []
    for phase in PHASES:
        saved = read_object(folder / 'agent/reviews' / f'{phase}.json')
        if saved:
            event = read_object(folder / f'events/{PHASES[phase]}.done.json')
            revision = fingerprint([event, read_object(folder / 'request.json'),
                read_object(folder / 'agent/reviews' / f'{phase}.retry.json')])
            if saved.get('revision') != revision:
                saved = {**saved, 'state': 'pending', 'summary': '새 근거로 다시 검토할 예정입니다. 아래는 이전 검토 기록입니다.'}
            messages.append(saved)
        elif (folder / f'events/{PHASES[phase]}.done.json').is_file():
            messages.append(dict(phase=phase, title=TITLES[phase], state='pending',
                                 summary='완료 기록이 도착했습니다. 검토를 기다리고 있습니다.', findings=[]))
    return messages


def model_review(config, session_id, phase, evidence):
    """Separate endpoint has no conversation/history field and no tools."""
    # Full deterministic evidence remains on disk. Give the model a bounded
    # sample with explicit totals, never allow a sample to establish a pass.
    excerpt = {k: evidence[k] for k in ('status', 'summary', 'counts', 'scope', 'limitations') if k in evidence}
    excerpt['findings'] = [{k: str(v)[:1200] if isinstance(v, str) else v for k, v in f.items()}
                           for f in evidence.get('findings', [])[:12]]
    excerpt['findings_omitted'] = max(0, len(evidence.get('findings', [])) - 12)
    while len(json.dumps(excerpt, ensure_ascii=False)) > 16000 and excerpt['findings']:
        excerpt['findings'].pop()
        excerpt['findings_omitted'] += 1
    with httpx.Client(timeout=180, trust_env=False) as client:
        response = client.post(config['inference_url'] + '/review',
            headers={'Authorization': 'Bearer ' + config['api_token']},
            json=dict(session_id=session_id, phase=phase, evidence=excerpt))
        response.raise_for_status()
        answer = response.json()
    if answer.get('session_id') != session_id or not isinstance(answer.get('analysis'), str) or not answer['analysis'].strip():
        raise ValueError('Invalid isolated review response')
    return answer['analysis'][:6000]


class ReviewCollector:
    def __init__(self, root, runs_root=None, registry=None, *, inference=model_review):
        self.root = Path(root)
        self.runs_root = Path(runs_root) if runs_root is not None else self.root / 'runs'
        self.registry = registry or ConsoleRegistry(self.root / 'console-registry.json')
        self.inference = inference
        # Folders whose review inputs were unchanged at the last settled pass.
        self._settled = {}
        self._deferred = False

    @staticmethod
    def _inputs(folder):
        """Cheap stat signature of everything a review revision is derived from."""
        names = ['request.json', *(f'events/{e}.done.json' for e in sorted(set(PHASES.values()))),
                 *(f'agent/reviews/{phase}.retry.json' for phase in PHASES),
                 *(f'agent/reviews/{phase}.json' for phase in PHASES)]
        signature = []
        for name in names:
            try:
                stat = (folder / name).stat()
                signature.append((name, stat.st_size, stat.st_mtime_ns))
            except OSError:
                signature.append((name, None, None))
        return tuple(signature)

    def collect_once(self, stopped=None):
        records = {r['run_id']: r for r in self.registry.load().get('runs', [])}
        # CLI-only jobs still get copy/report reviews. Shooting needs a project.
        folders = sorted({p.parent.parent for p in self.runs_root.glob('*/events/*.done.json')})
        for folder in folders:
            before = self._inputs(folder)
            if self._settled.get(folder) == before:
                continue
            record = records.get(folder.name, {'run_id': folder.name})
            settled = True
            for phase, engine in PHASES.items():
                if stopped is not None and stopped.is_set():
                    return
                event = folder / f'events/{engine}.done.json'
                if event.is_file():
                    self._deferred = False
                    try:
                        self.review(folder, record, phase)
                        settled = settled and not self._deferred
                    except Exception:
                        settled = False
                        log.exception('Completion review deferred for %s / %s', folder.name, phase)
            if settled:
                self._settled[folder] = self._inputs(folder)
            else:
                self._settled.pop(folder, None)

    def review(self, folder, record, phase):
        directory = folder / 'agent/reviews'
        directory.mkdir(parents=True, exist_ok=True)
        with (directory / f'{phase}.lock').open('a') as guard:
            try:
                fcntl.flock(guard, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                self._deferred = True  # Another collector is reviewing; look again next pass.
                return
            event_path = folder / f'events/{PHASES[phase]}.done.json'
            event = read_object(event_path)
            request = read_object(folder / 'request.json')
            retry = read_object(directory / f'{phase}.retry.json')
            revision = fingerprint([event, request, retry])
            latest_path = directory / f'{phase}.json'
            previous = read_object(latest_path)
            if previous.get('revision') == revision and previous.get('state') == 'completed':
                return
            session_id = uuid4().hex
            session = directory / 'sessions' / session_id
            session.mkdir(parents=True)
            status = dict(session_id=session_id, run_id=folder.name, phase=phase,
                title=TITLES[phase], state='running', revision=revision, started_at=utc_now(),
                summary='완료 근거를 검토하고 있습니다.', findings=[], history_used=False,
                artifact=str(session / 'result.json'))
            private_json(latest_path, status)
            private_json(session / 'request.json', dict(session_id=session_id, phase=phase,
                run_id=folder.name, history=[], completion=event, request=request))
            try:
                if phase == 'copy':
                    evidence = copy_review(folder)
                elif phase == 'report':
                    evidence = report_review(folder)
                else:
                    project = record.get('project_id')
                    public = public_state(read_object(self.root / 'blackmagician' / project / 'state.json')) if project else {}
                    evidence = reel_review(folder, record, public)
            except Exception as exc:
                evidence = result('검토 근거를 읽지 못했습니다.', [finding('review_error', type(exc).__name__,
                    '완료 기록 형식 또는 파일 접근에 문제가 있습니다.', '완료 파일과 볼륨 상태를 확인하고 다시 검토하세요.')])
            private_json(session / 'evidence.json', evidence)
            status.update(evidence)
            status['engine'] = 'evidence'
            # Persist the useful evidence before potentially slow inference.
            private_json(latest_path, status)
            config = read_object(self.root / 'agent/config.json')
            if evidence['status'] != 'skipped':
                if config.get('inference_url') and config.get('api_token'):
                    try:
                        status['analysis'] = self.inference(config, session_id, phase, evidence)
                        status['engine'] = 'local_model'
                    except Exception as exc:
                        status['model_error'] = type(exc).__name__
                        status['model_notice'] = '로컬 모델 설명을 받지 못했습니다. 파일 근거 검토 결과를 표시합니다. 다시 검토할 수 있습니다.'
                else:
                    status['model_notice'] = '로컬 모델이 설정되지 않아 파일 근거 검토 결과를 표시합니다.'
            status.update(state='completed', finished_at=utc_now())
            private_json(session / 'result.json', status)
            private_json(latest_path, status)
            return status


def request_retry(folder, phases):
    for phase in phases:
        if phase not in PHASES or not (folder / f'events/{PHASES[phase]}.done.json').is_file():
            raise ValueError('검토할 완료 기록이 없습니다.')
    for phase in phases:
        private_json(folder / 'agent/reviews' / f'{phase}.retry.json', dict(id=uuid4().hex, requested_at=utc_now()))


def start_collector(root, runs_root=None, registry=None):
    stopped = threading.Event()
    collector = ReviewCollector(root, runs_root, registry)

    def run():
        while not stopped.is_set():
            try:
                collector.collect_once(stopped)
            except Exception:
                log.exception('Completion review collection deferred')
            stopped.wait(3)

    worker = threading.Thread(target=run, daemon=True, name='completion-reviews')
    worker.start()
    return stopped, worker
