"""Same-origin desktop bridge. The persistent agent credential never reaches JS."""
from __future__ import annotations

import ipaddress
import json
import secrets
import urllib.error
import urllib.request
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field


class NewConversation(BaseModel):
    project_id: str | None = None


class ChatMessage(BaseModel):
    text: str = Field(min_length=1, max_length=6000)
    request_id: str = Field(pattern=r'^chat:[a-f0-9-]{36}$')


class ReviewRetry(BaseModel):
    phases: list[str] = Field(default_factory=lambda: ['copy', 'report', 'shooting'], min_length=1, max_length=3)


def create_router(pipeline_root: Path, runs_root: Path, registry, *, transport=None):
    router = APIRouter(prefix='/api/agent')
    session_token = secrets.token_urlsafe(32)

    def local(request: Request):
        host = request.client.host if request.client else ''
        try:
            permitted = ipaddress.ip_address(host).is_loopback
        except ValueError:
            permitted = host == 'testclient'
        if not permitted or request.url.hostname not in {'127.0.0.1', 'localhost', '::1'}:
            raise HTTPException(403, '에이전트 모드는 이 Mac에서만 사용할 수 있습니다.')
        if request.headers.get('sec-fetch-site') in {'cross-site', 'same-site'}:
            raise HTTPException(403, '다른 페이지에서 에이전트에 접근할 수 없습니다.')
        origin = request.headers.get('origin')
        if origin and origin != str(request.base_url).rstrip('/'):
            raise HTTPException(403, '요청 출처가 일치하지 않습니다.')

    def authorized(request: Request):
        local(request)
        if not secrets.compare_digest(request.headers.get('x-dit-agent', ''), session_token):
            raise HTTPException(401, '앱 연결을 새로고침해 주세요.')

    def call(path, payload=None):
        if transport:
            return transport(path, payload)
        try:
            config = json.loads((pipeline_root / 'agent/config.json').read_text())
            headers = {'Authorization': 'Bearer ' + config['api_token'], 'Content-Type': 'application/json'}
            port = int(config.get('api_port', 8766))
            if not 1024 <= port <= 65535:
                raise ValueError('Invalid local agent port')
            request = urllib.request.Request(f'http://127.0.0.1:{port}' + path, headers=headers,
                data=json.dumps(payload).encode() if payload is not None else None)
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
            with opener.open(request, timeout=5) as response:
                return json.load(response)
        except urllib.error.HTTPError as exc:
            try:
                detail = json.loads(exc.read()).get('detail', '요청을 처리하지 못했습니다.')
            except (ValueError, OSError):
                detail = '요청을 처리하지 못했습니다.'
            raise HTTPException(exc.code, detail)
        except (OSError, KeyError, ValueError):
            raise HTTPException(503, '로컬 에이전트에 연결하지 못했습니다. 잠시 후 다시 연결해 주세요.')

    @router.get('/session', dependencies=[Depends(local)])
    def session():
        from fastapi.responses import JSONResponse
        return JSONResponse({'token': session_token}, headers={'Cache-Control': 'no-store'})

    def review_folder(run_id):
        if Path(run_id).name != run_id or run_id in {'.', '..'} or not any(
                r.get('run_id') == run_id for r in registry.load().get('runs', [])):
            raise HTTPException(404, '작업을 찾을 수 없습니다.')
        return runs_root / run_id

    @router.post('/reviews/{run_id}/retry', dependencies=[Depends(authorized)])
    def retry_review(run_id: str, payload: ReviewRetry):
        from orchestrator.agent.reviews import request_retry
        try:
            request_retry(review_folder(run_id), payload.phases)
        except ValueError as exc:
            raise HTTPException(409, str(exc))
        return {'status': 'pending'}

    @router.get('/reviews/{run_id}/{phase}', dependencies=[Depends(local)])
    def review_artifact(run_id: str, phase: str):
        from orchestrator.agent.reviews import PHASES
        from fastapi.responses import FileResponse
        folder = review_folder(run_id)
        if phase not in PHASES or not (folder / 'agent/reviews' / f'{phase}.json').is_file():
            raise HTTPException(404, '검토 기록이 없습니다.')
        return FileResponse(folder / 'agent/reviews' / f'{phase}.json', media_type='application/json',
                            filename=f'{run_id}-{phase}-review.json', headers={'Cache-Control': 'no-store'})

    @router.get('/state', dependencies=[Depends(authorized)])
    def state():
        health = call('/health')
        return {'connected': health.get('ok', False),
                'inference_connected': health.get('inference_connected', False),
                'model_loaded': health.get('model_loaded', False),
                'model_loading': health.get('model_loading', False),
                'model_load_error': health.get('model_load_error'),
                'telegram_connected': health.get('telegram_connected', False),
                'telegram_paired': health.get('telegram_paired', False)}

    @router.post('/warmup', dependencies=[Depends(authorized)])
    def warmup():
        return call('/warmup', {})

    @router.get('/conversations', dependencies=[Depends(authorized)])
    def conversations():
        return call('/conversations')

    @router.post('/conversations', dependencies=[Depends(authorized)])
    def create(payload: NewConversation):
        return call('/conversations', payload.model_dump())

    @router.get('/conversations/{conversation_id}', dependencies=[Depends(authorized)])
    def conversation(conversation_id: str):
        import re
        if not re.fullmatch('[a-f0-9]{32}', conversation_id):
            raise HTTPException(404)
        result = call('/conversations/' + conversation_id)
        from orchestrator.dit_app.server import card_snapshot
        records = {r['run_id']: r for r in registry.load().get('runs', [])}
        for turn in result.get('turns', []):
            response = turn.get('result') or {}
            run_id = response.get('run_id')
            if run_id in records:
                response['execution'] = card_snapshot(records[run_id], runs_root)
        return result

    @router.post('/conversations/{conversation_id}/messages', dependencies=[Depends(authorized)])
    def message(conversation_id: str, payload: ChatMessage):
        import re
        if not re.fullmatch('[a-f0-9]{32}', conversation_id):
            raise HTTPException(404)
        return call('/conversations/' + conversation_id + '/messages', payload.model_dump())

    return router
