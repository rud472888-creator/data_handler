from __future__ import annotations

import hashlib
import json
import os
import re
import time
import shutil
from datetime import date
from pathlib import Path
from uuid import uuid4

import httpx
from pydantic import BaseModel, ConfigDict, Field

from orchestrator.agent.config import private_json
from orchestrator.agent.store import Store
from orchestrator.completion import workflow_succeeded
from orchestrator.jsonio import read_json
from orchestrator.web.registry import ConsoleRegistry
from orchestrator.web.server import _validate_replica_roots


class PlanInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    project_id: str
    source_path: str
    replica_paths: list[str] = Field(min_length=1)
    shoot_date: date
    camera_unit: str = Field(min_length=1, max_length=30, pattern=r'^[\w-]+$')


def _mounted_volumes() -> list[str]:
    # /Volumes is macOS-only and a disk can vanish mid-scan; never fail the chat.
    try:
        return [str(p) for p in Path('/Volumes').iterdir() if p.is_dir()]
    except OSError:
        return []


class AgentService:
    def __init__(self, root: Path, config: dict, *, starter=None):
        self.root, self.config = root, config
        self.store = Store(root / 'agent/queue.sqlite3')
        self.registry = ConsoleRegistry(root / 'console-registry.json')
        self.starter = starter

    def catalog(self) -> dict:
        projects = [p for p in self.registry.load()['projects'] if not p.get('removed_at')]
        from orchestrator.blackmagician.review import read_object
        from orchestrator.blackmagician.service import public_state
        sessions = {}
        for project in projects:
            state = public_state(read_object(self.root / 'blackmagician' / project['id'] / 'state.json'))
            if state['connection']:
                sessions[project['id']] = {k: state['connection'].get(k) for k in ('session_id', 'status', 'snapshot_at')}
                sessions[project['id']]['recorded_clips'] = len((state['snapshot'] or {}).get('entries', []))
        return {'projects': [{'id': p['id'], 'name': p['name'],
                             'source_paths': p.get('source_paths', []),
                             'replica_roots': p.get('replica_roots', [])} for p in projects],
                'mounted_volumes': _mounted_volumes(),
                'today': date.today().isoformat(), 'blackmagician_sessions': sessions}

    def safe_path(self, value: str) -> Path:
        path = Path(value).expanduser().resolve(strict=True)
        roots = [Path(p).expanduser().resolve() for p in self.config['allowed_roots']]
        if not path.is_dir() or not any(path.is_relative_to(r) for r in roots):
            raise ValueError('허용된 원본/복제 디렉터리가 아닙니다: ' + value)
        return path

    @staticmethod
    def identity(path: Path, *, source=False) -> dict:
        stat = path.stat()
        result = {'path': str(path), 'device': stat.st_dev, 'inode': stat.st_ino}
        if source:
            # Capture source inventory at preview and execution; never infer copy progress.
            digest = hashlib.sha256()
            count = 0
            for folder, directories, files in os.walk(path, followlinks=False):
                directories.sort()
                for name in sorted(directories + files):
                    child = Path(folder) / name
                    if child.is_symlink():
                        raise ValueError('원본의 심볼릭 링크는 원격 작업에서 지원하지 않습니다.')
                    st = child.stat()
                    digest.update(json.dumps([str(child.relative_to(path)), st.st_size,
                                              st.st_mtime_ns, st.st_ino]).encode())
                    count += 1
                    if count > 200000:
                        raise ValueError('원격 계획의 파일 수 제한을 초과했습니다.')
            result['inventory'] = digest.hexdigest()
        return result

    def preview(self, payload: dict, principal: str) -> dict:
        data = PlanInput.model_validate(payload)
        project = self.registry.find_project(data.project_id)
        if not project or project.get('removed_at'):
            raise ValueError('사용 가능한 프로젝트를 먼저 앱에서 생성해 주세요.')
        source = self.safe_path(data.source_path)
        replicas = tuple(self.safe_path(p) for p in data.replica_paths)
        _validate_replica_roots(replicas, (source,))
        all_paths = (source, *replicas)
        for i, path in enumerate(all_paths):
            for other in all_paths[i + 1:]:
                if path == other or path.is_relative_to(other) or other.is_relative_to(path):
                    raise ValueError('원본과 복제 경로는 서로 겹치면 안 됩니다.')
        preview = self.registry.preview_roll(data.project_id, str(data.shoot_date), data.camera_unit,
                                             replica_roots=replicas, flat_card_layout=True)
        plan_id = uuid4().hex[:24]
        plan = {'id': plan_id, 'project_id': data.project_id, 'project_name': project['name'],
                'source_path': str(source), 'replica_paths': [str(p) for p in replicas],
                'shoot_date': str(data.shoot_date), 'camera_unit': data.camera_unit,
                'roll': preview['roll'],
                'destinations': [str(p / project['name'] / '001_Footage' / preview['roll']) for p in replicas],
                'identities': [self.identity(p, source=i == 0) for i, p in enumerate(all_paths)]}
        with self.store.connect() as db:
            db.execute('INSERT INTO plans(id,payload,principal,created) VALUES(?,?,?,?)',
                       (plan_id, json.dumps(plan), principal, time.time()))
        return plan

    def execute(self, plan_id: str, principal: str, chat_id: int | None = None) -> dict:
        # Single transaction prevents duplicate confirmation claims. Crashes after claim
        # remain uncertain: never respawn a possibly started media job automatically.
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT * FROM plans WHERE id=? AND principal=?', (plan_id, principal)).fetchone()
            if not row:
                raise ValueError('본인이 만든 실행 계획을 찾을 수 없습니다.')
            if row['status'] != 'pending':
                return {'run_id': row['run_id'], 'status': row['status'], 'duplicate': True}
            if time.time() - row['created'] > 1800:
                raise ValueError('계획이 만료되었습니다. 경로를 다시 확인해 주세요.')
            plan = json.loads(row['payload'])
            current = [self.identity(self.safe_path(p), source=i == 0)
                       for i, p in enumerate([plan['source_path'], *plan['replica_paths']])]
            if current != plan['identities']:
                raise ValueError('원본 또는 디스크가 변경되었습니다. 계획을 다시 만들어 주세요.')
            project = self.registry.find_project(plan['project_id'])
            if not project or project.get('removed_at') or project['name'] != plan['project_name']:
                raise ValueError('프로젝트가 변경되었습니다.')
            run_id = 'run-agent-' + uuid4().hex[:12]
            db.execute("UPDATE plans SET status='claimed',run_id=? WHERE id=?", (run_id, plan_id))
            if chat_id is not None:
                db.execute('INSERT INTO subscriptions VALUES(?,?)', (run_id, chat_id))
        private_json(self.root / 'runs' / run_id / 'agent/approval.json',
                     {'principal': principal, 'plan': plan, 'confirmed_at': time.time()})
        try:
            replicas = tuple(Path(p) for p in plan['replica_paths'])
            record = self.registry.reserve_run(project_id=plan['project_id'],
                shoot_date=plan['shoot_date'], camera_unit=plan['camera_unit'], run_id=run_id,
                source_path=plan['source_path'], replica_roots=replicas, flat_card_layout=True)
            if record.roll != plan['roll']:
                raise ValueError('다른 작업이 카드 번호를 예약했습니다. 새 계획을 확인해 주세요.')
            if self.starter:
                self.starter(plan, run_id)
            else:
                from orchestrator.cli import start_run
                start_run(source=Path(plan['source_path']), replica_paths=replicas,
                          project_name=plan['project_name'], profile='macbook-dit-agent',
                          run_id=run_id, footage_run_name=record.roll, flat_card_layout=True,
                          visual_qa=bool((self.registry.find_project(plan['project_id']) or {}).get('visual_qa')))
            self.registry.mark_run_started(run_id)
            status = 'started'
        except Exception as exc:
            # A spawn might already have happened. Mark uncertain rather than retrying.
            with self.store.connect() as db:
                db.execute("UPDATE plans SET status='needs_review' WHERE id=?", (plan_id,))
            private_json(self.root / 'runs' / run_id / 'agent/launch-error.json',
                         {'status': 'needs_review', 'error_type': type(exc).__name__})
            raise
        with self.store.connect() as db:
            db.execute('UPDATE plans SET status=? WHERE id=?', (status, plan_id))
        return {'run_id': run_id, 'status': status}

    def status(self) -> dict:
        with self.store.connect() as db:
            rows = db.execute('SELECT id,status,run_id FROM plans ORDER BY created DESC LIMIT 20').fetchall()
        return {'plans': [dict(r) for r in rows], 'offline_execution': True,
                'telegram_paired': self.config.get('allowed_user_id') is not None}

    def health(self) -> dict:
        inference = False
        loaded = False
        loading = False
        load_error = None
        try:
            with httpx.Client(timeout=2, trust_env=False) as client:
                response = client.get(self.config['inference_url'] + '/health',
                    headers={'Authorization': 'Bearer ' + self.config['api_token']})
                response.raise_for_status()
                data = response.json()
                inference = data.get('ok') is True
                loaded = data.get('loaded') is True
                loading = data.get('loading') is True
                load_error = data.get('load_error')
        except (httpx.HTTPError, ValueError, KeyError):
            pass
        try:
            last = float(self.store.meta('telegram_last_connected', '0'))
        except ValueError:
            last = 0
        return {'ok': True, 'inference_connected': inference, 'model_loaded': loaded,
                'model_loading': loading, 'model_load_error': load_error,
                'telegram_connected': bool(self.config.get('allowed_user_id') and 0 <= time.time()-last < 90),
                **self.status()}

    def warmup(self):
        try:
            with httpx.Client(timeout=3, trust_env=False) as client:
                response = client.post(self.config['inference_url'] + '/warmup',
                    headers={'Authorization': 'Bearer ' + self.config['api_token']})
                response.raise_for_status()
            return {'accepted': True}
        except httpx.HTTPError:
            return {'accepted': False}

    def interpret(self, text: str, principal: str, *, history=None, project_id=None) -> dict:
        if text.strip() == '/backup-review':
            return self.backup_review(project_id)
        if text.strip() in {'/shooting', '/script-check'}:
            from orchestrator.blackmagician.assistant import shooting_summary
            context = self.shooting_state(project_id)
            return {'text': shooting_summary(context), 'shooting_evidence': self.shooting_evidence(context)}
        if text.strip() in {'/start', '/help', '도움말'}:
            return {'text': '프로젝트 목록: /projects\n완료 기록: /status\n'
                    '예: 프로젝트 OO, 원본 /Volumes/CARD, 백업 /Volumes/BACKUP으로 복제해줘. 경로는 필요한 만큼 추가할 수 있습니다.\n'
                    '경로가 포함된 계획을 확인한 뒤 실행하면 이후 검수·PDF 보고까지 자동 진행합니다.'}
        if text.strip() == '/projects':
            return {'text': json.dumps(self.catalog(), ensure_ascii=False, indent=2)}
        if text.strip() in {'/status', '상태'}:
            return {'text': json.dumps(self.status(), ensure_ascii=False, indent=2)}
        match = re.fullmatch(r'/approve ([a-f0-9]{24})', text.strip())
        if match:
            # Approval is only parsed from the user's original message, never model output.
            return {'approve': match[1]}
        catalog = self.catalog()
        catalog['selected_project_id'] = project_id
        shooting = self.shooting_state(project_id)
        if shooting.get('connection'):
            from orchestrator.blackmagician.assistant import shooting_context
            recent = ' '.join(str(h.get('content', h.get('text', '')))[:500] for h in (history or [])[-4:])
            catalog['shooting'] = shooting_context(shooting, text + ' ' + recent)
            history = [{k: str(v)[:500] for k, v in h.items()} for h in (history or [])[-4:]]
            # Preserve the question and full counts while dropping selected rows
            # when conversation/catalog text uses the local model's context budget.
            context = catalog['shooting']
            while context['entries'] and len(json.dumps({'text': text, 'catalog': catalog, 'history': history}, ensure_ascii=False)) > 17000:
                context['entries'].pop()
                context['entries_omitted'] += 1
        try:
            with httpx.Client(timeout=180, trust_env=False) as client:
                response = client.post(self.config['inference_url'] + '/infer',
                    headers={'Authorization': 'Bearer ' + self.config['api_token']},
                    json={'text': text, 'catalog': catalog, 'history': history or []})
                response.raise_for_status()
        except httpx.TimeoutException:
            raise ValueError('로컬 모델 응답 시간이 초과되었습니다. 모델 준비 상태를 확인하고 다시 요청해 주세요. 복제는 시작되지 않았습니다.') from None
        except httpx.HTTPError:
            raise ValueError('로컬 모델이 요청을 처리하지 못했습니다. 다시 연결한 뒤 경로를 명확히 지정해 주세요. 복제는 시작되지 않았습니다.') from None
        intent = response.json()['intent']
        if intent['action'] == 'shooting_answer':
            if not shooting.get('connection'):
                return {'text': '촬영 정보를 확인할 프로젝트를 선택하고 Blackmagician 세션을 연결해 주세요.'}
            answer = str(intent.get('explanation') or '기록에 필요한 정보가 없습니다. 씬이나 클립명을 알려 주세요.')[:5000]
            if (shooting.get('snapshot') or {}).get('from_cache', True):
                answer = '실시간 수신을 확인하지 못했습니다. 마지막 저장 기록 기준입니다.\n' + answer
            return {'text': answer, 'shooting_evidence': self.shooting_evidence(shooting)}
        if intent['action'] == 'backup_review':
            return self.backup_review(intent.get('project_id') or project_id)
        if intent['action'] == 'status':
            plans = self.status()['plans']
            if not plans:
                return {'text': '에이전트가 접수한 작업이 아직 없습니다. 원본과 백업 경로를 1개 이상 알려 주시면 계획을 준비하겠습니다.'}
            return {'text': '최근 에이전트 작업 기록입니다.\n' + '\n'.join(
                f"{p['run_id'] or '실행 전 계획'}: {p['status']}" for p in plans[:8])}
        if intent['action'] == 'help':
            return {'text': str(intent.get('explanation') or '프로젝트·원본·복제 경로를 알려 주세요.')[:3000]}
        values = {k: intent[k] for k in PlanInput.model_fields if k in intent}
        plan = self.preview(values, principal)
        return {'plan': plan, 'text': self.plan_text(plan),
                'reply_markup': {'inline_keyboard': [[{'text': '이 경로로 복제 시작',
                                                       'callback_data': 'approve:' + plan['id']}]]}}

    def shooting_state(self, project_id):
        if not project_id:
            return {}
        from orchestrator.blackmagician.service import IntegrationService
        return IntegrationService(self.root, self.root / 'runs', self.registry).get(project_id)

    @staticmethod
    def shooting_evidence(state):
        live = state.get('live') or {}
        return {'session_id': (state.get('connection') or {}).get('session_id'),
                'revision': live.get('revision'),
                'observed_at': live.get('last_observed_at') or (state.get('connection') or {}).get('snapshot_at'),
                'from_cache': (state.get('snapshot') or {}).get('from_cache', True)}

    def backup_review(self, project_id):
        from orchestrator.blackmagician.service import IntegrationService
        from orchestrator.blackmagician.review import review_text
        if not project_id:
            return {'text': '백업을 검토할 프로젝트를 선택해 주세요.'}
        service = IntegrationService(self.root, self.root / 'runs', self.registry)
        result = service.review(project_id)['review']
        return {'text': review_text(result), 'backup_review': result}

    @staticmethod
    def plan_text(plan):
        return (f"프로젝트: {plan['project_name']}\n원본: {plan['source_path']}\n"
                + '복제 위치:\n' + '\n'.join(plan['destinations'])
                + f"\n촬영일: {plan['shoot_date']} / 카메라: {plan['camera_unit']}\n"
                + f"확인 후 실행: /approve {plan['id']}\n계획 유효시간: 30분")

    def collect_reports(self) -> None:
        with self.store.connect() as db:
            rows = db.execute('SELECT * FROM subscriptions').fetchall()
        for row in rows:
            try:
                self._collect_run(row['run_id'], row['chat_id'])
            except (OSError, ValueError, KeyError):
                # A missing/offline artifact is retried independently of every other run.
                continue

    def _collect_run(self, run_id: str, chat_id: int) -> None:
        folder = self.root / 'runs' / run_id
        def read(name):
            path = folder / name
            return read_json(path) if path.is_file() else {}
        dm, dh = read('events/datamanager.done.json'), read('events/datahelper.done.json')
        preflight = read('events/media-preflight.done.json')
        helper_preflight = read('events/datahelper-preflight.done.json')
        verified = dm.get('status') == 'completed' and dm.get('replicas_complete') is True
        launch_error = read('agent/launch-error.json')
        terminal = bool(dh or launch_error or (dm and not verified) or preflight.get('status') == 'failed'
                        or helper_preflight.get('status') == 'failed')
        if not terminal:
            return
        evidence = {'copy': dm, 'review': dh, 'preflight': preflight, 'helper_preflight': helper_preflight,
                    'launch_error': launch_error}
        revision = hashlib.sha256(json.dumps(evidence, sort_keys=True).encode()).hexdigest()[:16]
        key = f'final:{run_id}:{revision}'
        spec = read('request.json')
        # Completion truth comes from durable engine evidence, not whether a drive
        # is still connected when a delayed Telegram delivery is attempted.
        success = workflow_succeeded(dm, dh, spec, launch_error)
        text = (f"{'작업 완료' if success else '작업 확인 필요'}: {spec.get('project_name', run_id)}\n"
                f"작업 ID: {run_id}\n복제 체크섬: {'검증 완료' if verified else '미완료 / 확인 필요'}\n"
                f"검수·PDF: {dh.get('status', '시작되지 않음')}\n파일 수: {dm.get('file_count', '확인 불가')}")
        report = folder / 'agent' / f'report-{revision}.md'
        report.parent.mkdir(parents=True, exist_ok=True)
        if not report.exists():
            report.write_text(text + '\n\n```json\n' + json.dumps(evidence, ensure_ascii=False, indent=2) + '\n```\n')
        self.store.out(key, chat_id, {'text': text})
        self.store.out(key + ':summary', chat_id, {'document': str(report), 'caption': '작업 결과 및 근거 기록',
                                                  'sha256': hashlib.sha256(report.read_bytes()).hexdigest()})
        candidates = []
        dm_reports = dm.get('reports', {})
        if isinstance(dm_reports, dict):
            candidates.extend(v for k, v in dm_reports.items() if k.endswith('pdf') and isinstance(v, str))
        for item in dh.get('reports', []) if isinstance(dh.get('reports'), list) else []:
            if isinstance(item, dict) and item.get('pdf_path'):
                candidates.append(item['pdf_path'])
        allowed = [folder.resolve()]
        if spec:
            allowed += [Path(p).resolve() / spec['project_name'] for p in spec.get('replica_roots', [])]
        for i, value in enumerate(dict.fromkeys(candidates)):
            path = Path(value).resolve()
            if path.suffix.lower() != '.pdf' or not any(path.is_relative_to(p) for p in allowed):
                continue
            if not path.is_file() or path.stat().st_size > 49 * 1024**2:
                continue
            snapshot = folder / 'agent' / f'attachment-{revision}-{i}.pdf'
            if not snapshot.exists():
                temporary = snapshot.with_suffix('.tmp')
                shutil.copyfile(path, temporary)
                temporary.replace(snapshot)
            self.store.out(key + f':pdf:{i}', chat_id, {'document': str(snapshot), 'caption': path.name,
                'sha256': hashlib.sha256(snapshot.read_bytes()).hexdigest()})
        with self.store.connect() as db:
            db.execute("UPDATE plans SET status=? WHERE run_id=?",
                       ('completed' if success else 'needs_review', run_id))
