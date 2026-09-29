"""Loopback, same-origin bridge; web credentials never leave Python."""
import ipaddress
import secrets
from contextlib import asynccontextmanager
from typing import Literal

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from orchestrator.blackmagician.client import IntegrationError
from orchestrator.blackmagician.service import IntegrationService
from orchestrator.blackmagician.live import LiveSessions


class ConnectPayload(BaseModel):
    mode: Literal['invite', 'session']
    code: str = Field(min_length=1, max_length=1500)
    project_id: str | None = Field(default=None, max_length=1500)


class LivePayload(BaseModel):
    enabled: bool


class NotePayload(BaseModel):
    value: str = Field(min_length=1, max_length=1000)
    entry_revision: str = Field(min_length=24, max_length=24)


def create_router(root, runs_root, registry, *, client_factory=None):
    service = IntegrationService(root, runs_root, registry, **({'client_factory': client_factory} if client_factory else {}))
    live = LiveSessions(service)
    running = False

    @asynccontextmanager
    async def lifespan(app):
        nonlocal running
        running = True
        live.resume()
        try:
            yield
        finally:
            running = False
            live.close()

    router = APIRouter(prefix='/api/blackmagician', lifespan=lifespan)
    token = secrets.token_urlsafe(32)

    def local(request: Request):
        host = request.client.host if request.client else ''
        try:
            loopback = ipaddress.ip_address(host).is_loopback
        except ValueError:
            loopback = host == 'testclient'
        if not loopback or request.url.hostname not in {'127.0.0.1', 'localhost', '::1'}:
            raise HTTPException(403, '이 Mac의 앱에서만 연결할 수 있습니다.')
        if request.headers.get('sec-fetch-site') in {'cross-site', 'same-site'} or (request.headers.get('origin') and request.headers['origin'] != str(request.base_url).rstrip('/')):
            raise HTTPException(403, '요청 출처가 일치하지 않습니다.')

    def authorized(request: Request):
        local(request)
        if not secrets.compare_digest(token, request.headers.get('x-dit-blackmagician', '')):
            raise HTTPException(401, '앱을 새로고침해 주세요.')

    def call(method, *args):
        try:
            return JSONResponse(method(*args), headers={'Cache-Control': 'no-store'})
        except IntegrationError as exc:
            raise HTTPException(exc.status, {'message': str(exc), 'matches': exc.matches}) from None
        except (httpx.HTTPError, ValueError, KeyError, TypeError):
            raise HTTPException(502, 'Blackmagician 서버에 연결하지 못했습니다. 잠시 후 다시 시도하세요.') from None

    @router.get('/session', dependencies=[Depends(local)])
    def session():
        return JSONResponse({'token': token}, headers={'Cache-Control': 'no-store'})

    @router.get('/projects/{project_id}', dependencies=[Depends(authorized)])
    def state(project_id: str):
        if running:
            try:
                live.ensure(project_id)
            except IntegrationError as exc:
                raise HTTPException(exc.status, str(exc)) from None
        return call(service.get, project_id)

    @router.post('/projects/{project_id}/connect', dependencies=[Depends(authorized)])
    def connect(project_id: str, payload: ConnectPayload):
        try:
            return call(service.connect, project_id, payload.mode, payload.code, payload.project_id)
        finally:
            if running:
                live.ensure(project_id)

    @router.post('/projects/{project_id}/live', dependencies=[Depends(authorized)])
    def live_mode(project_id: str, payload: LivePayload):
        response = call(service.configure_live, project_id, payload.enabled)
        if running:
            live.ensure(project_id)
        return response

    @router.post('/projects/{project_id}/questions/{question_id}', dependencies=[Depends(authorized)])
    def confirm_note(project_id: str, question_id: str, payload: NotePayload):
        return call(service.confirm_note, project_id, question_id, payload.value, payload.entry_revision)

    @router.post('/projects/{project_id}/refresh', dependencies=[Depends(authorized)])
    def refresh(project_id: str):
        return call(service.refresh, project_id)

    @router.post('/projects/{project_id}/disconnect', dependencies=[Depends(authorized)])
    def disconnect(project_id: str):
        return call(service.disconnect, project_id)

    @router.post('/projects/{project_id}/review', dependencies=[Depends(authorized)])
    def review(project_id: str):
        return call(service.review, project_id)

    return router
