"""RBAC 服务: 角色种子、权限查询、绑定管理。"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.ids import snowflake_id
from ..db.models import Role, RoleBinding, RolePermission
from .permissions import BUILTIN_ROLES


async def seed_roles(session: AsyncSession) -> None:
    """幂等写入内置角色。"""
    for name, spec in BUILTIN_ROLES.items():
        existing = await session.scalar(select(Role).where(Role.name == name))
        if existing is None:
            role = Role(id=snowflake_id(), name=name, scope=spec["scope"], builtin=True)
            session.add(role)
            await session.flush()
            for perm in sorted(spec["permissions"]):
                session.add(
                    RolePermission(id=snowflake_id(), role_id=role.id, permission=perm)
                )
    await session.commit()


async def get_role_by_name(session: AsyncSession, name: str) -> Role | None:
    return await session.scalar(select(Role).where(Role.name == name))


async def role_permissions(session: AsyncSession, role_id: int) -> set[str]:
    rows = await session.execute(
        select(RolePermission.permission).where(RolePermission.role_id == role_id)
    )
    return {r[0] for r in rows}


@dataclass
class Grant:
    """一次授权的解析结果。"""

    permission: str
    granted: bool
    scope: str = ""           # global / workspace / project
    workspace_id: int | None = None
    project_id: int | None = None
    role_name: str = ""


async def _effective_grants(
    session: AsyncSession,
    user_id: int,
    workspace_id: int | None,
    project_id: int | None,
) -> list[Grant]:
    """解析用户对 (workspace, project) 资源的全部授权, 按 scope 优先级排序。"""
    bindings = (
        await session.execute(
            select(RoleBinding).where(RoleBinding.user_id == user_id)
        )
    ).scalars().all()
    grants: list[Grant] = []
    for b in bindings:
        role = await session.get(Role, b.role_id)
        if role is None:
            continue
        # global 绑定: 覆盖所有空间
        if b.workspace_id is None and b.project_id is None:
            perms = await role_permissions(session, role.id)
            for p in perms:
                grants.append(Grant(p, True, "global", None, None, role.name))
            continue
        # workspace 绑定
        if b.workspace_id is not None and b.project_id is None:
            if workspace_id is not None and b.workspace_id != workspace_id:
                continue
            perms = await role_permissions(session, role.id)
            for p in perms:
                grants.append(Grant(p, True, "workspace", b.workspace_id, None, role.name))
            continue
        # project 绑定
        if b.project_id is not None:
            if project_id is not None and b.project_id != project_id:
                continue
            if workspace_id is not None and b.workspace_id not in (None, workspace_id):
                continue
            perms = await role_permissions(session, role.id)
            for p in perms:
                grants.append(Grant(p, True, "project", b.workspace_id, b.project_id, role.name))
    return grants


def _scope_rank(g: Grant) -> int:
    return {"project": 0, "workspace": 1, "global": 2}[g.scope]


async def has_permission(
    session: AsyncSession,
    user_id: int,
    permission: str,
    workspace_id: int | None = None,
    project_id: int | None = None,
) -> Grant:
    """校验用户是否具备某权限; 返回最具体的一条授权(project > workspace > global)。"""
    grants = [
        g
        for g in await _effective_grants(session, user_id, workspace_id, project_id)
        if g.permission == permission
    ]
    if not grants:
        return Grant(permission, False)
    best = sorted(grants, key=_scope_rank)[0]
    return Grant(permission, True, best.scope, best.workspace_id, best.project_id, best.role_name)


async def effective_permissions(
    session: AsyncSession,
    user_id: int,
    workspace_id: int | None = None,
    project_id: int | None = None,
) -> set[str]:
    grants = await _effective_grants(session, user_id, workspace_id, project_id)
    return {g.permission for g in grants}


async def bind_role(
    session: AsyncSession,
    user_id: int,
    role_id: int,
    workspace_id: int | None = None,
    project_id: int | None = None,
) -> None:
    existing = await session.scalar(
        select(RoleBinding).where(
            RoleBinding.user_id == user_id,
            RoleBinding.role_id == role_id,
            RoleBinding.workspace_id == workspace_id,
            RoleBinding.project_id == project_id,
        )
    )
    if existing is None:
        session.add(
            RoleBinding(
                id=snowflake_id(),
                user_id=user_id,
                role_id=role_id,
                workspace_id=workspace_id,
                project_id=project_id,
            )
        )
    await session.commit()


async def unbind_role(
    session: AsyncSession,
    user_id: int,
    role_id: int,
    workspace_id: int | None = None,
    project_id: int | None = None,
) -> None:
    await session.execute(
        delete(RoleBinding).where(
            RoleBinding.user_id == user_id,
            RoleBinding.role_id == role_id,
            RoleBinding.workspace_id == workspace_id,
            RoleBinding.project_id == project_id,
        )
    )
    await session.commit()


async def user_roles(
    session: AsyncSession,
    user_id: int,
    workspace_id: int | None = None,
) -> Sequence[tuple[Role, int | None, int | None]]:
    """返回用户角色(含 global + 指定空间的 workspace 绑定)。"""
    rows = await session.execute(
        select(Role, RoleBinding.workspace_id, RoleBinding.project_id)
        .join(RoleBinding, RoleBinding.role_id == Role.id)
        .where(
            RoleBinding.user_id == user_id,
            RoleBinding.project_id.is_(None),
            RoleBinding.workspace_id.is_(None) | (
                RoleBinding.workspace_id == workspace_id
            ),
        )
    )
    return list(rows.all())