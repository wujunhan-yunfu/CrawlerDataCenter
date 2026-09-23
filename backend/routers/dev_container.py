"""开发容器路由: 确保拉起 / 轮询状态 / 回收。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from ..api.deps import get_current_user, get_dev_service, get_kube
from ..api.errors import bad_request, not_found
from ..db.models import CrawlerProject, User
from ..db.session import get_db
from ..rbac.service import has_permission
from ..redis.client import Redis, redis
from ..schemas.webhook import DevContainerOut
from ..services.dev_container import DevContainerService
from ..services.project import ProjectService

router = APIRouter(tags=["dev-container"])


async def _project_for(db: AsyncSession, project_id: int, user: User) -> CrawlerProject:
    project = await ProjectService.get(db, project_id)
    if project is None:
        raise not_found("project_not_found", "项目不存在")
    if project.source_type != "custom":
        raise bad_request("builtin_no_container", "内置爬取器项目不提供开发容器")
    grant = await has_permission(db, user.id, "container:manage", workspace_id=project.workspace_id, project_id=project.id)
    if not grant.granted:
        from ..api.errors import forbidden

        raise forbidden("forbidden")
    return project


@router.post("/projects/{project_id}/dev-container", response_model=DevContainerOut)
async def ensure_dev_container(
    project_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
    dev: DevContainerService = Depends(get_dev_service),
):
    project = await _project_for(db, project_id, user)
    row = await dev.ensure(db, project)
    return row


@router.get("/projects/{project_id}/dev-container", response_model=DevContainerOut)
async def poll_dev_container(
    project_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
    dev: DevContainerService = Depends(get_dev_service),
):
    project = await _project_for(db, project_id, user)
    row = await dev.poll(db, project)
    return row


@router.delete("/projects/{project_id}/dev-container")
async def recycle_dev_container(
    project_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
    dev: DevContainerService = Depends(get_dev_service),
):
    project = await _project_for(db, project_id, user)
    await dev.recycle(db, project)
    return {"ok": True}