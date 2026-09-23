"""审计服务: 敏感操作异步落库(经 Redis 队列由 worker 消费)。"""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.ids import snowflake_id
from ..db.models import AuditLog
from ..redis.client import TaskQueue


def audit_payload(
    actor_id: int | None,
    action: str,
    target_type: str | None = None,
    target_id: int | None = None,
    workspace_id: int | None = None,
    detail: dict | None = None,
    ip: str | None = None,
    user_agent: str | None = None,
) -> dict:
    return {
        "actor_id": actor_id,
        "action": action,
        "target_type": target_type,
        "target_id": target_id,
        "workspace_id": workspace_id,
        "detail": detail,
        "ip": ip,
        "user_agent": user_agent,
    }


async def audit_enqueue(rds, payload: dict) -> None:
    """异步入队审计(worker 落库), 避免阻塞主流程。"""
    await TaskQueue(rds.client).push("audit", payload)


async def audit_write(session: AsyncSession, payload: dict) -> None:
    import time

    session.add(
        AuditLog(
            id=snowflake_id(),
            actor_id=payload.get("actor_id"),
            action=payload.get("action", ""),
            target_type=payload.get("target_type"),
            target_id=payload.get("target_id"),
            workspace_id=payload.get("workspace_id"),
            detail_json=payload.get("detail"),
            ip=payload.get("ip"),
            user_agent=payload.get("user_agent"),
            created_at=int(time.time() * 1000),
        )
    )
    await session.commit()


async def list_audit(
    session: AsyncSession,
    workspace_id: int | None = None,
    actor_id: int | None = None,
    action: str | None = None,
    offset: int = 0,
    limit: int = 50,
) -> tuple[list[AuditLog], int]:
    stmt = select(AuditLog)
    if workspace_id is not None:
        stmt = stmt.where(AuditLog.workspace_id == workspace_id)
    if actor_id is not None:
        stmt = stmt.where(AuditLog.actor_id == actor_id)
    if action:
        stmt = stmt.where(AuditLog.action == action)
    total = await session.scalar(select(func.count()).select_from(stmt.subquery()))
    rows = (
        (await session.execute(stmt.order_by(AuditLog.id.desc()).offset(offset).limit(limit)))
        .scalars()
        .all()
    )
    return list(rows), int(total or 0)