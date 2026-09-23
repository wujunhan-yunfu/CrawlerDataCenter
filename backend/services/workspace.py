"""工作空间与成员服务。"""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.ids import snowflake_id
from ..db.models import Role, RoleBinding, User, Workspace, WorkspaceMember
from ..rbac.service import bind_role, get_role_by_name, user_roles


class WorkspaceService:
    @staticmethod
    async def create(
        session: AsyncSession,
        owner_id: int,
        name: str,
        quota: dict | None = None,
    ) -> Workspace:
        ws = Workspace(id=snowflake_id(), name=name, owner_id=owner_id, quota_json=quota)
        session.add(ws)
        await session.flush()

        owner_role = await get_role_by_name(session, "workspace_owner")
        if owner_role:
            await bind_role(session, owner_id, owner_role.id, workspace_id=ws.id)
            session.add(
                WorkspaceMember(
                    id=snowflake_id(),
                    workspace_id=ws.id,
                    user_id=owner_id,
                    role_id=owner_role.id,
                    joined_at=__import__("time").time_ns() // 1_000_000,
                )
            )
        await session.commit()
        return ws

    @staticmethod
    async def list(session: AsyncSession, user_id: int) -> list[Workspace]:
        ws_ids = set()
        bindings = (await session.execute(select(RoleBinding).where(RoleBinding.user_id == user_id))).scalars().all()
        for b in bindings:
            if b.workspace_id is not None:
                ws_ids.add(b.workspace_id)
        if not ws_ids:
            return []
        rows = (await session.execute(select(Workspace).where(Workspace.id.in_(ws_ids), Workspace.deleted_at.is_(None)))).scalars().all()
        return list(rows)

    @staticmethod
    async def get(session: AsyncSession, ws_id: int) -> Workspace | None:
        return await session.get(Workspace, ws_id)

    @staticmethod
    async def update(session: AsyncSession, ws: Workspace, name: str | None, quota: dict | None, status: str | None) -> Workspace:
        if name is not None:
            ws.name = name
        if quota is not None:
            ws.quota_json = quota
        if status is not None:
            ws.status = status
        await session.commit()
        return ws

    @staticmethod
    async def delete(session: AsyncSession, ws: Workspace) -> None:
        ws.soft_delete()
        ws.status = "deleted"
        await session.commit()

    # ---- 成员 ----

    @staticmethod
    async def add_member(
        session: AsyncSession,
        ws_id: int,
        username: str,
        role_name: str,
        project_id: int | None = None,
    ) -> WorkspaceMember | None:
        user = await session.scalar(select(User).where(User.username == username))
        if user is None:
            return None
        role = await get_role_by_name(session, role_name)
        if role is None or (project_id is not None and role.scope == "workspace"):
            # project 绑定需要 project 级角色; 简化: 允许 workspace 角色在单项目上也生效
            pass
        if role is None:
            return None
        await bind_role(session, user.id, role.id, workspace_id=ws_id, project_id=project_id)
        member = WorkspaceMember(
            id=snowflake_id(),
            workspace_id=ws_id,
            user_id=user.id,
            role_id=role.id,
            joined_at=__import__("time").time_ns() // 1_000_000,
        )
        existing = await session.scalar(
            select(WorkspaceMember).where(WorkspaceMember.workspace_id == ws_id, WorkspaceMember.user_id == user.id)
        )
        if existing is None:
            session.add(member)
        await session.commit()
        return member

    @staticmethod
    async def remove_member(session: AsyncSession, ws_id: int, user_id: int) -> None:
        from sqlalchemy import delete

        await session.execute(
            delete(WorkspaceMember).where(
                WorkspaceMember.workspace_id == ws_id, WorkspaceMember.user_id == user_id
            )
        )
        await session.execute(
            delete(RoleBinding).where(
                RoleBinding.workspace_id == ws_id, RoleBinding.user_id == user_id
            )
        )
        await session.commit()

    @staticmethod
    async def list_members(session: AsyncSession, ws_id: int) -> list[dict]:
        rows = (await session.execute(select(WorkspaceMember).where(WorkspaceMember.workspace_id == ws_id))).scalars().all()
        out = []
        for m in rows:
            user = await session.get(User, m.user_id)
            role = await session.get(Role, m.role_id)
            out.append(
                {
                    "user_id": m.user_id,
                    "username": user.username if user else str(m.user_id),
                    "role": role.name if role else "",
                    "scope": role.scope if role else "",
                    "project_id": m.project_id,
                }
            )
        return out

    @staticmethod
    async def member_count(session: AsyncSession, ws_id: int) -> int:
        return await session.scalar(
            select(func.count(WorkspaceMember.id)).where(WorkspaceMember.workspace_id == ws_id)
        ) or 0