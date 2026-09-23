"""爬虫项目路由。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from ..api.deps import get_client_ip, get_current_user, pagination_params
from ..api.errors import bad_request, not_found
from ..db.models import CrawlerProject, User
from ..db.session import get_db
from ..rbac.service import has_permission
from ..redis.client import Redis, redis
from ..schemas.workspace import ProjectCreate, ProjectOut, ProjectUpdate
from ..services.audit import audit_enqueue, audit_payload
from ..services.project import ProjectService
from ..services.workspace import WorkspaceService

router = APIRouter(tags=["projects"])


async def _get_project(db: AsyncSession, project_id: int) -> CrawlerProject:
    project = await ProjectService.get(db, project_id)
    if project is None:
        raise not_found("project_not_found", "项目不存在")
    return project


@router.get("/workspaces/{workspace_id}/projects", response_model=list[ProjectOut])
async def list_projects(
    workspace_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    grant = await has_permission(db, user.id, "project:read", workspace_id=workspace_id)
    if not grant.granted:
        from ..api.errors import forbidden

        raise forbidden("forbidden")
    projects, _ = await ProjectService.list(db, workspace_id)
    return projects


@router.post("/workspaces/{workspace_id}/projects", response_model=ProjectOut)
async def create_project(
    workspace_id: int,
    body: ProjectCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
    rds: Redis = Depends(lambda: redis),
):
    grant = await has_permission(db, user.id, "project:create", workspace_id=workspace_id)
    if not grant.granted:
        from ..api.errors import forbidden

        raise forbidden("forbidden")
    try:
        project = await ProjectService.create(
            db,
            workspace_id,
            body.name,
            body.source_type,
            body.description,
            body.builtin_crawler_id,
            body.run_config,
        )
    except ValueError as exc:
        raise bad_request("invalid_source_type", str(exc))
    await audit_enqueue(
        rds,
        audit_payload(user.id, "project.create", "project", project.id, workspace_id=workspace_id, ip=get_client_ip(request)),
    )
    return project


@router.get("/projects/{project_id}", response_model=ProjectOut)
async def get_project(
    project_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    project = await _get_project(db, project_id)
    grant = await has_permission(db, user.id, "project:read", workspace_id=project.workspace_id, project_id=project.id)
    if not grant.granted:
        from ..api.errors import forbidden

        raise forbidden("forbidden")
    return project


@router.patch("/projects/{project_id}", response_model=ProjectOut)
async def update_project(
    project_id: int,
    body: ProjectUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
    rds: Redis = Depends(lambda: redis),
):
    project = await _get_project(db, project_id)
    grant = await has_permission(db, user.id, "project:update", workspace_id=project.workspace_id, project_id=project.id)
    if not grant.granted:
        from ..api.errors import forbidden

        raise forbidden("forbidden")
    project = await ProjectService.update(db, project, body.name, body.description, body.run_config, body.status)
    await audit_enqueue(
        rds,
        audit_payload(user.id, "project.update", "project", project.id, workspace_id=project.workspace_id, ip=get_client_ip(request)),
    )
    return project


@router.delete("/projects/{project_id}")
async def delete_project(
    project_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
    rds: Redis = Depends(lambda: redis),
):
    project = await _get_project(db, project_id)
    grant = await has_permission(db, user.id, "project:delete", workspace_id=project.workspace_id, project_id=project.id)
    if not grant.granted:
        from ..api.errors import forbidden

        raise forbidden("forbidden")
    await ProjectService.delete(db, project)
    await audit_enqueue(
        rds,
        audit_payload(user.id, "project.delete", "project", project.id, workspace_id=project.workspace_id, ip=get_client_ip(request)),
    )
    return {"ok": True}