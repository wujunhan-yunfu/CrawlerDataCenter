"""开发容器状态模型。"""

from __future__ import annotations

from sqlalchemy import BigInteger, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from ..base import Base, TimestampMixin


class DevContainer(TimestampMixin, Base):
    """一个项目最多一个 dev Pod(scale-to-zero)。phase 状态机见 docs/k8s-orchestration.md。"""

    __tablename__ = "dev_containers"
    __table_args__ = (UniqueConstraint("project_id", name="uq_dev_project"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    project_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True, nullable=False)
    workspace_id: Mapped[int] = mapped_column(BigInteger, index=True, nullable=False)
    crawler_id: Mapped[str] = mapped_column(String(128), index=True, nullable=False)
    pod_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    service_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    namespace: Mapped[str] = mapped_column(String(64), default="cdc", nullable=False)
    dev_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    phase: Mapped[str] = mapped_column(
        String(16), default="absent", nullable=False
    )  # absent/pending/starting/ready/stopping/failed
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    last_active_at: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    expires_at: Mapped[int | None] = mapped_column(BigInteger, nullable=True)