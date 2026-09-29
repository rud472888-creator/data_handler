from __future__ import annotations

import fcntl
import json
import secrets
import threading
from contextlib import asynccontextmanager
from uuid import uuid4

from fastapi import FastAPI, Header, HTTPException, Depends
from pydantic import BaseModel, Field

from orchestrator.agent.config import load_config
from orchestrator.agent.service import AgentService, PlanInput
from orchestrator.agent.telegram import receiver, sender, command_worker
from orchestrator.paths import PIPELINE_ROOT


class Message(BaseModel):
    text: str = Field(min_length=1, max_length=6000)


class ConversationInput(BaseModel):
    project_id: str | None = None


class ConversationMessage(Message):
    request_id: str = Field(pattern=r'^chat:[a-f0-9-]{36}$')


def create_app() -> FastAPI:
    config = load_config()
    service = AgentService(PIPELINE_ROOT, config)
    stopped = threading.Event()

    @asynccontextmanager
    async def lifespan(app):
        guard = (PIPELINE_ROOT / 'agent/service.lock').open('a')
        fcntl.flock(guard, fcntl.LOCK_EX | fcntl.LOCK_NB)
        threads = [threading.Thread(target=f, args=(service, stopped), daemon=True)
                   for f in (receiver, sender, command_worker)]
        for thread in threads:
            thread.start()
        from orchestrator.agent.reviews import start_collector
        review_stop, review_thread = start_collector(service.root, registry=service.registry)
        yield
        stopped.set()
        review_stop.set()
        guard.close()

    app = FastAPI(title='Data Handler Local Agent', lifespan=lifespan)

    def auth(authorization: str | None = Header(default=None)):
        if not secrets.compare_digest(authorization or '', 'Bearer ' + config['api_token']):
            raise HTTPException(401)

    @app.get('/health', dependencies=[Depends(auth)])
    def health():
        return service.health()

    @app.post('/warmup', dependencies=[Depends(auth)])
    def warmup():
        return service.warmup()

    @app.get('/catalog', dependencies=[Depends(auth)])
    def catalog():
        return service.catalog()

    @app.get('/conversations', dependencies=[Depends(auth)])
    def conversations():
        return {'conversations': service.store.conversations()}

    @app.post('/conversations', dependencies=[Depends(auth)])
    def new_conversation(payload: ConversationInput):
        if payload.project_id and not service.registry.find_project(payload.project_id):
            raise HTTPException(404, '프로젝트가 없습니다.')
        return service.store.create_conversation(uuid4().hex, payload.project_id)

    @app.get('/conversations/{conversation_id}', dependencies=[Depends(auth)])
    def conversation(conversation_id: str):
        try:
            result = service.store.conversation(conversation_id)
        except KeyError:
            raise HTTPException(404, '대화를 찾을 수 없습니다.')
        with service.store.connect() as db:
            for turn in result['turns']:
                plan = (turn.get('result') or {}).get('plan')
                if plan:
                    row = db.execute('SELECT status,created FROM plans WHERE id=?', (plan['id'],)).fetchone()
                    if row:
                        import time
                        plan['status'] = 'expired' if row['status'] == 'pending' and time.time()-row['created'] > 1800 else row['status']
        return result

    @app.post('/conversations/{conversation_id}/messages', dependencies=[Depends(auth)])
    def conversation_message(conversation_id: str, payload: ConversationMessage):
        try:
            return service.store.enqueue_turn(conversation_id, payload.request_id, payload.text)
        except KeyError:
            raise HTTPException(404, '대화를 찾을 수 없습니다.')
        except ValueError as exc:
            raise HTTPException(409, str(exc))

    @app.post('/messages', dependencies=[Depends(auth)])
    def messages(message: Message):
        key = 'local:' + uuid4().hex
        service.store.enqueue(key, {'text': message.text, 'principal': 'local'})
        return {'id': key, 'status': 'pending'}

    @app.get('/messages/{key}', dependencies=[Depends(auth)])
    def result(key: str):
        with service.store.connect() as db:
            row = db.execute('SELECT status,result FROM inbox WHERE id=?', (key,)).fetchone()
        if not row:
            raise HTTPException(404)
        return {'status': row['status'], 'result': json.loads(row['result']) if row['result'] else None}

    @app.post('/plans', dependencies=[Depends(auth)])
    def plans(payload: PlanInput):
        try:
            return service.preview(payload.model_dump(mode='json'), 'local')
        except (ValueError, OSError) as exc:
            raise HTTPException(400, str(exc))

    @app.post('/plans/{plan_id}/approve', dependencies=[Depends(auth)])
    def approve(plan_id: str):
        try:
            return service.execute(plan_id, 'local', config.get('allowed_chat_id'))
        except (ValueError, OSError) as exc:
            raise HTTPException(409, str(exc))

    return app
