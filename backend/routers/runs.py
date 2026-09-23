"""运行触发与查询路由(once/cron/login) + 定时进程状态。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from ..api.deps import get_current_user, get_kube, pagination_params
from ..api.errors import bad_request, not_found
from ..db.models import CrawlerProject, User
from ..db.session import get_db
from ..rbac.service import has_permission
from ..redis.client import Redis, redis
from ..schemas.webhook import RunDetailOut, RunOut, RunProcessOut, RunTrigger
from ..services.run import RunService

router = APIRouter(tags=["runs"])


def _run_service(request: Request) -> RunService:
    return RunService(request.app.state.kube)


async def _project_for(db: AsyncSession, project_id: int, user: User) -> CrawlerProject:
    project = await (await _lazy_project_service()).get(db, project_id)
    if project is None:
        raise not_found("project_not_found", "项目不存在")
    grant = await has_permission(db, user.id, "run:trigger", workspace_id=project.workspace_id, project_id=project.id)
    if not grant.granted:
        from ..api.errors import forbidden

        raise forbidden("forbidden")
    return project


async def _lazy_project_service():
    from ..services.project import ProjectService

    return ProjectService


@router.post("/projects/{project_id}/runs", response_model=RunOut)
async def trigger_run(
    project_id: int,
    body: RunTrigger,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    project = await _project_for(db, project_id, user)
    svc = _run_service(request)
    try:
        if body.trigger == "cron":
            process = await svc.trigger_cron(db, project, body.cron or "", body.headless, body.webhook_secret)
            return RunOut(
                run_id=process.process_id,
                project_id=project.id,
                crawler_id=project.crawler_id,
                workspace_id=project.workspace_id,
                mode="run",
                trigger="cron",
                cron=body.cron,
                status="running",
                started_at=process.started_at,
            )
        run = await svc.trigger_once(db, project, body.headless, body.webhook_secret)
        return run
    except ValueError as exc:
        raise bad_request("invalid_cron", str(exc))


@router.get("/projects/{project_id}/runs", response_model=list[RunOut])
async def list_runs(
    project_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
    offset: int = 0,
    limit: int = 50,
):
    project = await _project_for(db, project_id, user)
    svc = _run_service(request)
    runs, _ = await svc.list_runs(db, project_id=project.id, offset=offset, limit=limit)
    return runs


@router.get("/runs/{run_id}", response_model=RunDetailOut)
async def get_run_detail(
    run_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    svc = _run_service(request)
    detail = await svc.get_run_detail(db, run_id)
    if detail is None:
        raise not_found("run_not_found", "运行记录不存在")
    run = await svc.get_run(db, run_id)
    grant = await has_permission(db, user.id, "run:read", workspace_id=run.workspace_id, project_id=run.project_id)
    if not grant.granted:
        from ..api.errors import forbidden

        raise forbidden("forbidden")
    return detail


@router.get("/projects/{project_id}/run-process", response_model=RunProcessOut | None)
async def get_run_process(
    project_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    project = await _project_for(db, project_id, user)
    svc = _run_service(request)
    return await svc.get_process(db, project.id)


@router.delete("/projects/{project_id}/run-process")
async def stop_run_process(
    project_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    project = await _project_for(db, project_id, user)
    svc = _run_service(request)
    process = await svc.stop_cron(db, project)
    if process is None:
        raise not_found("process_not_found", "定时进程不存在")
    return {"ok": True}