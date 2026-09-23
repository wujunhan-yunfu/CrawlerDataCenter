"""工作空间与成员路由。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from ..api.deps import get_client_ip, get_current_user, pagination_params, require_permission
from ..api.errors import forbidden, not_found
from ..db.models import User, Workspace
from ..db.session import get_db
from ..rbac.service import has_permission
from ..schemas.workspace import (
    MemberInviteIn,
    MemberOut,
    WorkspaceCreate,
    WorkspaceOut,
    WorkspaceUpdate,
)
from ..services.audit import audit_enqueue, audit_payload
from ..services.workspace import WorkspaceService
from ..redis.client import Redis, redis

router = APIRouter(tags=["workspaces"])


async def _get_ws(db: AsyncSession, ws_id: int) -> Workspace:
    ws = await WorkspaceService.get(db, ws_id)
    if ws is None or ws.deleted_at is not None:
        raise not_found("workspace_not_found", "工作空间不存在")
    return ws


@router.post("/workspaces", response_model=WorkspaceOut)
async def create_workspace(
    body: WorkspaceCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission("workspace:create")),
    rds: Redis = Depends(lambda: redis),
):
    ws = await WorkspaceService.create(db, user.id, body.name, body.quota)
    await audit_enqueue(
        rds,
        audit_payload(user.id, "workspace.create", "workspace", ws.id, ip=get_client_ip(request)),
    )
    return ws


@router.get("/workspaces", response_model=list[WorkspaceOut])
async def list_workspaces(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    return await WorkspaceService.list(db, user.id)


@router.get("/workspaces/{workspace_id}", response_model=WorkspaceOut)
async def get_workspace(
    workspace_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission("workspace:read")),
):
    return await _get_ws(db, workspace_id)


@router.patch("/workspaces/{workspace_id}", response_model=WorkspaceOut)
async def update_workspace(
    workspace_id: int,
    body: WorkspaceUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission("workspace:update")),
    rds: Redis = Depends(lambda: redis),
):
    ws = await _get_ws(db, workspace_id)
    ws = await WorkspaceService.update(db, ws, body.name, body.quota, body.status)
    await audit_enqueue(
        rds,
        audit_payload(user.id, "workspace.update", "workspace", ws.id, workspace_id=ws.id, ip=get_client_ip(request)),
    )
    return ws


@router.delete("/workspaces/{workspace_id}")
async def delete_workspace(
    workspace_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission("workspace:delete")),
    rds: Redis = Depends(lambda: redis),
):
    ws = await _get_ws(db, workspace_id)
    if ws.owner_id != user.id:
        grant = await has_permission(db, user.id, "workspace:delete", workspace_id=workspace_id)
        if grant.scope != "global":
            raise forbidden("forbidden", "仅所有者可删除工作空间")
    await WorkspaceService.delete(db, ws)
    await audit_enqueue(
        rds,
        audit_payload(user.id, "workspace.delete", "workspace", ws.id, workspace_id=ws.id, ip=get_client_ip(request)),
    )
    return {"ok": True}


@router.get("/workspaces/{workspace_id}/members", response_model=list[MemberOut])
async def list_members(
    workspace_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission("member:invite")),
):
    return await WorkspaceService.list_members(db, workspace_id)


@router.post("/workspaces/{workspace_id}/members", response_model=MemberOut)
async def add_member(
    workspace_id: int,
    body: MemberInviteIn,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission("member:invite")),
    rds: Redis = Depends(lambda: redis),
):
    await _get_ws(db, workspace_id)
    member = await WorkspaceService.add_member(db, workspace_id, body.username, body.role, body.project_id)
    if member is None:
        raise not_found("user_not_found", "用户不存在或角色非法")
    await audit_enqueue(
        rds,
        audit_payload(user.id, "member.invite", "user", member.user_id, workspace_id=workspace_id, ip=get_client_ip(request)),
    )
    return {
        "user_id": member.user_id,
        "username": body.username,
        "role": body.role,
        "scope": "workspace" if body.project_id is None else "project",
        "project_id": body.project_id,
    }


@router.delete("/workspaces/{workspace_id}/members/{user_id}")
async def remove_member(
    workspace_id: int,
    user_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
    actor: User = Depends(require_permission("member:remove")),
    rds: Redis = Depends(lambda: redis),
):
    await WorkspaceService.remove_member(db, workspace_id, user_id)
    await audit_enqueue(
        rds,
        audit_payload(actor.id, "member.remove", "user", user_id, workspace_id=workspace_id, ip=get_client_ip(request)),
    )
    return {"ok": True}