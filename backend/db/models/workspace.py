"""工作空间与成员模型。"""

from __future__ import annotations

from sqlalchemy import JSON, BigInteger, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from ..base import Base, SoftDeleteMixin, TimestampMixin


class Workspace(TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "workspaces"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    owner_id: Mapped[int] = mapped_column(BigInteger, index=True, nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="active", nullable=False)
    quota_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)  # 容器并发/数据容量


class WorkspaceMember(Base):
    __tablename__ = "workspace_members"
    __table_args__ = (
        UniqueConstraint("workspace_id", "user_id", name="uq_ws_member"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    workspace_id: Mapped[int] = mapped_column(BigInteger, index=True, nullable=False)
    user_id: Mapped[int] = mapped_column(BigInteger, index=True, nullable=False)
    role_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    project_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    joined_at: Mapped[int] = mapped_column(BigInteger, nullable=False)