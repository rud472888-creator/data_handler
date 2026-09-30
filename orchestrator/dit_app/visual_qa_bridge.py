"""DIT app endpoints for the post-completion visual QA (separate from agent reviews)."""
from __future__ import annotations

import ipaddress
import secrets
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

from orchestrator.visual_qa import scheduler

_SERVED = ("report.html", "findings.json", "summary.json")
_IMAGE_SUFFIXES = {".jpg", ".jpeg"}
_CSP = "default-src 'none'; img-src 'self'; style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'"


class StartPayload(BaseModel):
    action: Literal["start", "retry", "rerun"] = "start"


class ProjectOption(BaseModel):
    enabled: bool


def create_router(runs_root: Path, registry) -> APIRouter:
    router = APIRouter()
    token = secrets.token_urlsafe(32)

    def local(request: Request) -> None:
        host = request.client.host if request.client else ""
        try:
            loopback = ipaddress.ip_address(host).is_loopback
        except ValueError:
            loopback = host == "testclient"
        if not loopback or request.url.hostname not in {"127.0.0.1", "localhost", "::1"}:
            raise HTTPException(403, "이 Mac의 앱에서만 사용할 수 있습니다.")
        origin = request.headers.get("origin")
        if request.headers.get("sec-fetch-site") in {"cross-site", "same-site"} or (
                origin and origin != str(request.base_url).rstrip("/")):
            raise HTTPException(403, "요청 출처가 일치하지 않습니다.")

    def authorized(request: Request) -> None:
        local(request)
        if not secrets.compare_digest(request.headers.get("x-dit-visual-qa", ""), token):
            raise HTTPException(401, "앱을 새로고침해 주세요.")

    def known_run(run_id: str) -> None:
        if Path(run_id).name != run_id or run_id in {".", ".."} or not any(
                r.get("run_id") == run_id for r in registry.load().get("runs", [])):
            raise HTTPException(404, "작업 기록이 없습니다.")

    @router.get("/api/visual-qa/session", dependencies=[Depends(local)])
    def session() -> JSONResponse:
        return JSONResponse({"token": token}, headers={"Cache-Control": "no-store"})

    @router.get("/api/library/cards/{run_id}/visual-qa")
    def summary(run_id: str) -> JSONResponse:
        known_run(run_id)
        return JSONResponse(scheduler.qa_summary(run_id, runs_root), headers={"Cache-Control": "no-store"})

    @router.post("/api/library/cards/{run_id}/visual-qa", dependencies=[Depends(authorized)])
    def start(run_id: str, payload: StartPayload) -> dict:
        known_run(run_id)
        try:
            result = scheduler.schedule_visual_qa(
                run_id, trigger="dit_app", manual=True, new_revision=payload.action == "rerun", runs_root=runs_root)
        except scheduler.ScheduleError as exc:
            raise HTTPException(409, str(exc)) from exc
        return {**result, "summary": scheduler.qa_summary(run_id, runs_root)}

    @router.post("/api/library/cards/{run_id}/visual-qa/{qa_id}/cancel", dependencies=[Depends(authorized)])
    def cancel(run_id: str, qa_id: str) -> dict:
        known_run(run_id)
        if not scheduler.request_cancel(run_id, qa_id, runs_root):
            raise HTTPException(404, "영상 QA 기록이 없습니다.")
        return {"status": "cancel_requested"}

    @router.post("/api/library/projects/{project_id}/visual-qa", dependencies=[Depends(authorized)])
    def project_option(project_id: str, payload: ProjectOption) -> dict:
        # Affects only cards imported afterwards; existing records are never re-inspected.
        with registry._locked():
            data = registry.load()
            project = next((p for p in data["projects"] if p["id"] == project_id), None)
            if project is None:
                raise HTTPException(404, "프로젝트를 찾을 수 없습니다.")
            project["visual_qa"] = payload.enabled
            registry.save(data)
        return {"project_id": project_id, "visual_qa": payload.enabled}

    @router.get("/api/library/visual-qa/{run_id}/{qa_id}/{name:path}")
    def files(run_id: str, qa_id: str, name: str) -> FileResponse:
        known_run(run_id)
        if not scheduler.is_valid_qa_id(qa_id):
            raise HTTPException(404, "영상 QA 기록이 없습니다.")
        base = (scheduler.visual_qa_root(run_id, runs_root) / qa_id).resolve()
        target = (base / name).resolve()
        relative = target.relative_to(base) if target.is_relative_to(base) else None
        allowed = relative is not None and target.is_file() and (
            relative.as_posix() in _SERVED
            or (relative.parts[:1] == ("evidence",) and len(relative.parts) == 3 and target.suffix.lower() in _IMAGE_SUFFIXES))
        if not allowed:
            raise HTTPException(404, "파일을 찾을 수 없습니다.")
        headers = {"Cache-Control": "no-store", "Content-Security-Policy": _CSP, "X-Content-Type-Options": "nosniff"}
        return FileResponse(target, headers=headers)

    return router
