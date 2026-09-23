"""审计与健康路由。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from ..api.deps import get_current_user
from ..db.models import User
from ..db.session import get_db
from ..rbac.service import has_permission
from ..schemas.webhook import AuditOut
from ..services.audit import list_audit

router = APIRouter(tags=["system"])


@router.get("/audit", response_model=list[AuditOut])
async def audit_logs(
    workspace_id: int | None = None,
    actor_id: int | None = None,
    action: str | None = None,
    offset: int = 0,
    limit: int = 50,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    grant = await has_permission(db, user.id, "audit:read", workspace_id=workspace_id)
    if not grant.granted:
        from ..api.errors import forbidden

        raise forbidden("forbidden")
    rows, _ = await list_audit(db, workspace_id, actor_id, action, offset, min(200, max(1, limit)))
    return rows