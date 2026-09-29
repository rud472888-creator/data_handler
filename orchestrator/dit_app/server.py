from __future__ import annotations

import re
import shutil
from pathlib import Path
from typing import Any
from uuid import uuid4
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from orchestrator import paths
from orchestrator.completion import workflow_succeeded
from orchestrator.app_front.server import create_app as create_engine_app
from orchestrator.jsonio import read_json
from orchestrator.run_state import utc_now
from orchestrator.spec import SpecError
from orchestrator.web.models import ConsoleProject
from orchestrator.web.registry import ConsoleRegistry, _validate_project_name
from orchestrator.web.server import _artifact_payloads

STATIC = Path(__file__).parent / "static"


class ProjectPayload(BaseModel):
    name: str


class DayReportPayload(BaseModel):
    shoot_date: str


_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")


def _roll_number(roll: Any) -> int:
    match = re.fullmatch(r"R#(\d+)", str(roll or ""))
    return int(match.group(1)) if match else 1 << 30


def card_snapshot(record: dict[str, Any], runs_root: Path) -> dict[str, Any]:
    """Read durable state and completion evidence, never infer verified bytes."""
    run_id = str(record["run_id"])
    if Path(run_id).name != run_id or run_id in {".", ".."}:
        raise ValueError("invalid run ID")
    folder = runs_root / run_id

    def read(name: str) -> dict[str, Any]:
        path = folder / name
        return read_json(path) if path.is_file() else {}

    state = read("state.json")
    request = read("request.json")
    copy = read("events/datamanager.done.json")
    report = read("events/datahelper.done.json")
    status = state.get("status", record.get("status", "unknown"))
    verified = copy.get("status") == "completed" and copy.get("replicas_complete") is True
    if copy.get("status") == "failed" or report.get("status") == "failed" or status == "failed":
        phase = "failed"
    elif report:
        phase = "reported" if workflow_succeeded(copy, report, request, read('agent/launch-error.json')) else "review"
    elif verified:
        phase = "reporting" if request.get("run_mode", "workflow") == "workflow" else "verified"
    elif copy:
        phase = "review"
    elif status in {"running", "started"}:
        phase = "copying"
    else:
        phase = "waiting"
    artifacts = _artifact_payloads(run_id, folder)
    from orchestrator.agent.reviews import review_messages
    reviews = review_messages(folder)
    if phase != 'failed' and any(r.get('status') == 'review_needed' for r in reviews):
        phase = 'review'
    for index, artifact in enumerate(artifacts):
        if artifact["available"] and Path(artifact["path"]).suffix.lower() == ".pdf":
            artifact["url"] = f"/api/library/reports/{run_id}/{index}"
    return {
        **record,
        "phase": phase,
        "verified": verified,
        "file_count": copy.get("file_count"),
        "updated_at": report.get("finished_at") or copy.get("finished_at") or state.get("updated_at") or record.get("updated_at") or record.get("created_at"),
        "error": state.get("last_error") or copy.get("error") or report.get("error") or record.get("error"),
        "failed_files": copy.get("failed_files", []),
        "destinations": list(copy.get("replica_footage_roots", {}).values()) or [
            str(Path(root) / request["project_name"] / ("001_Footage" if request.get("flat_card_layout") else "01_Footage") / request["footage_run_name"])
            for root in request.get("replica_roots", [])
            if request.get("project_name") and request.get("footage_run_name")
        ],
        "artifacts": artifacts,
        "replica_roots": [str(root) for root in request.get("replica_roots", [])],
        # The list carries review summaries only; the selected card loads its
        # findings from /api/library/cards/{run_id}/reviews.
        "agent_reviews": [review_summary(r) for r in reviews],
    }


def review_summary(review: dict[str, Any], findings: int = 0) -> dict[str, Any]:
    return {**{k: v for k, v in review.items() if k not in {'files', 'clips', 'findings'}},
            'findings': review.get('findings', [])[:findings],
            'finding_count': len(review.get('findings', []))}


def create_app(**engine_options: Any) -> FastAPI:
    registry_path = engine_options.get("registry_path") or paths.PIPELINE_ROOT / "console-registry.json"
    runs_root = engine_options.get("runs_root") or paths.RUNS_ROOT
    registry = ConsoleRegistry(registry_path)
    @asynccontextmanager
    async def lifespan(app):
        from orchestrator.agent.reviews import start_collector
        stopped, worker = start_collector(Path(registry_path).parent, runs_root, registry)
        yield
        stopped.set()

    app = FastAPI(title="Data Handler DIT", lifespan=lifespan)
    from orchestrator.dit_app.agent_bridge import create_router
    app.include_router(create_router(Path(registry_path).parent, Path(runs_root), registry))
    from orchestrator.dit_app.blackmagician_bridge import create_router as blackmagician_router
    app.include_router(blackmagician_router(Path(registry_path).parent, Path(runs_root), registry))
    app.mount("/workspace-static", StaticFiles(directory=STATIC), name="workspace-static")

    @app.get("/")
    def home() -> FileResponse:
        return FileResponse(STATIC / "index.html")

    @app.get("/api/projects")
    def projects() -> dict[str, Any]:
        data = registry.load()
        return {**data, "projects": [p for p in data["projects"] if not p.get("removed_at")]}

    @app.post("/api/library/projects/{project_id}/remove")
    def remove_project(project_id: str) -> dict[str, Any]:
        with registry._locked():
            data = registry.load()
            project = next((p for p in data["projects"] if p["id"] == project_id), None)
            if project is None:
                raise HTTPException(404, "프로젝트를 찾을 수 없습니다.")
            for record in data["runs"]:
                if record.get("project_id") != project_id:
                    continue
                folder = runs_root / record["run_id"]
                state_path = folder / "state.json"
                state = read_json(state_path) if state_path.is_file() else record
                completed = (folder / "events/datahelper.done.json").is_file()
                request_path = folder / "request.json"
                request = read_json(request_path) if request_path.is_file() else {}
                copy_only = request.get("run_mode") == "datamanager"
                terminal = state.get("status") == "failed" or completed or (
                    state.get("status") in {"completed", "done", "warn", "review-needed"}
                    and (copy_only or state.get("stage") == "done" or not request)
                )
                if not terminal:
                    raise HTTPException(409, "진행 중이거나 완료를 확인하지 못한 작업이 있습니다. 작업 완료 후 제거해 주세요.")
            project["removed_at"] = utc_now()
            registry.save(data)
        return {"removed": True, "project_id": project_id}

    @app.post("/api/library/projects/{project_id}/restore")
    def restore_project(project_id: str) -> dict[str, Any]:
        with registry._locked():
            data = registry.load()
            project = next((p for p in data["projects"] if p["id"] == project_id), None)
            if project is None:
                raise HTTPException(404, "프로젝트를 찾을 수 없습니다.")
            if any(p["id"] != project_id and not p.get("removed_at") and p["name"].casefold() == project["name"].casefold() for p in data["projects"]):
                raise HTTPException(409, "같은 이름의 프로젝트가 있어 복원할 수 없습니다.")
            project.pop("removed_at", None)
            registry.save(data)
        return {"project": project}

    @app.post("/api/library/projects", status_code=201)
    def create_project(payload: ProjectPayload) -> dict[str, Any]:
        name = payload.name.strip()
        try:
            _validate_project_name(name)
        except SpecError as exc:
            raise HTTPException(400, str(exc)) from exc
        now = utc_now()
        project = ConsoleProject(
            id=f"project-{uuid4().hex[:12]}", name=name, replica_roots=(),
            replica_project_roots=(), preset_name="dit", created_at=now, updated_at=now,
        )
        with registry._locked():
            data = registry.load()
            if any(not p.get("removed_at") and p["name"].casefold() == name.casefold() for p in data["projects"]):
                raise HTTPException(409, "같은 이름의 프로젝트가 있습니다. 기존 프로젝트를 열어 주세요.")
            data["projects"].append(project.to_payload())
            registry.save(data)
        return {"project": project.to_payload()}

    @app.get("/api/library/projects/{project_id}/cards")
    def cards(project_id: str) -> JSONResponse:
        data = registry.load()
        if not any(p["id"] == project_id for p in data["projects"]):
            raise HTTPException(404, "프로젝트를 찾을 수 없습니다.")
        # Polled every few seconds: the payload is plain JSON already, so skip
        # FastAPI's recursive encoder.
        return JSONResponse({"cards": [card_snapshot(r, runs_root) for r in data["runs"] if r.get("project_id") == project_id]})

    @app.get("/api/library/cards/{run_id}/reviews")
    def card_reviews(run_id: str) -> dict[str, Any]:
        from orchestrator.agent.reviews import review_messages

        if Path(run_id).name != run_id or run_id in {".", ".."}:
            raise HTTPException(404, "작업 기록이 없습니다.")
        if not any(r.get("run_id") == run_id for r in registry.load()["runs"]):
            raise HTTPException(404, "작업 기록이 없습니다.")
        return {"run_id": run_id,
                "agent_reviews": [review_summary(r, 100) for r in review_messages(Path(runs_root) / run_id)]}

    @app.get("/api/library/reports/{run_id}/{index}")
    def report_file(run_id: str, index: int) -> FileResponse:
        record = next((r for r in registry.load()["runs"] if r.get("run_id") == run_id), None)
        if record is None:
            raise HTTPException(404, "작업 기록이 없습니다.")
        artifacts = card_snapshot(record, runs_root)["artifacts"]
        if index < 0 or index >= len(artifacts):
            raise HTTPException(404, "리포트가 없습니다.")
        artifact = artifacts[index]
        if not artifact["available"] or Path(artifact["path"]).suffix.lower() != ".pdf":
            raise HTTPException(404, "PDF 파일을 사용할 수 없습니다.")
        return FileResponse(artifact["path"], filename=Path(artifact["path"]).name, media_type="application/pdf", content_disposition_type="inline")

    report_root = Path(registry_path).parent / "dit-reports"

    def day_report_path(project_id: str, shoot_date: str) -> Path:
        if not _DATE.fullmatch(shoot_date) or Path(project_id).name != project_id:
            raise HTTPException(400, "촬영일 형식이 올바르지 않습니다.")
        return report_root / project_id / f"DIT_Report_{shoot_date}.pdf"

    @app.post("/api/library/projects/{project_id}/dit-report")
    def create_day_report(project_id: str, payload: DayReportPayload) -> dict[str, Any]:
        from orchestrator.dit_report import card_rows, summary, write_day_report

        path = day_report_path(project_id, payload.shoot_date)
        data = registry.load()
        project = next((p for p in data["projects"] if p["id"] == project_id), None)
        if project is None:
            raise HTTPException(404, "프로젝트를 찾을 수 없습니다.")
        cards = [card_snapshot(r, runs_root) for r in data["runs"]
                 if r.get("project_id") == project_id and r.get("shoot_date") == payload.shoot_date]
        if not cards:
            raise HTTPException(404, "이 촬영일에 가져온 카드가 없습니다.")
        cards.sort(key=lambda c: _roll_number(c.get("roll")))
        rows = card_rows(cards, Path(runs_root))
        try:
            write_day_report(path, project=project["name"], shoot_date=payload.shoot_date, rows=rows)
        except ImportError as exc:
            raise HTTPException(503, "PDF 생성 모듈(reportlab)을 사용할 수 없습니다.") from exc
        # Hand the day report over with the footage: a copy beside every backup.
        saved, offline = [], []
        roots = dict.fromkeys(str(Path(root) / project["name"]) for c in cards for root in c.get("replica_roots", []))
        for root in roots:
            target = Path(root) / "00_Master" / "reports" / path.name
            try:
                if not Path(root).is_dir():
                    raise OSError(root)
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(path, target)
                saved.append(str(target))
            except OSError:
                offline.append(str(target))
        return {"url": f"/api/library/projects/{project_id}/dit-report/{payload.shoot_date}",
                "summary": summary(rows), "saved_to": saved, "unavailable": offline}

    @app.get("/api/library/projects/{project_id}/dit-report/{shoot_date}")
    def day_report(project_id: str, shoot_date: str) -> FileResponse:
        path = day_report_path(project_id, shoot_date)
        if not path.is_file():
            raise HTTPException(404, "DIT 리포트를 먼저 생성하세요.")
        return FileResponse(path, filename=path.name, media_type="application/pdf", content_disposition_type="inline")

    app.mount("/", create_engine_app(**engine_options, flat_card_layout=True))
    return app
