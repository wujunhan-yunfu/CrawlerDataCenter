"""RBAC 模型: 角色 / 角色-权限 / 用户-角色绑定。"""

from __future__ import annotations

from sqlalchemy import BigInteger, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from ..base import Base, TimestampMixin


class Role(TimestampMixin, Base):
    __tablename__ = "roles"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    name: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    scope: Mapped[str] = mapped_column(
        String(16), default="workspace", nullable=False
    )  # global / workspace / project
    description: Mapped[str | None] = mapped_column(String(255), nullable=True)
    builtin: Mapped[bool] = mapped_column(default=False, nullable=False)


class RolePermission(Base):
    __tablename__ = "role_permissions"
    __table_args__ = (UniqueConstraint("role_id", "permission", name="uq_role_perm"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    role_id: Mapped[int] = mapped_column(BigInteger, index=True, nullable=False)
    permission: Mapped[str] = mapped_column(String(64), nullable=False)


class RoleBinding(TimestampMixin, Base):
    """用户 → 角色绑定。scope 由 workspace_id/project_id 决定:
    (None, None) = global; (ws, None) = workspace; (ws, project) = project。
    """

    __tablename__ = "role_bindings"
    __table_args__ = (
        UniqueConstraint("user_id", "role_id", "workspace_id", "project_id", name="uq_binding"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    user_id: Mapped[int] = mapped_column(BigInteger, index=True, nullable=False)
    role_id: Mapped[int] = mapped_column(BigInteger, index=True, nullable=False)
    workspace_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True, index=True)
    project_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True, index=True)