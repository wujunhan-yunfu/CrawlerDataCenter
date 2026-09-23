"""爬虫项目模型。"""

from __future__ import annotations

from sqlalchemy import JSON, BigInteger, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from ..base import Base, SoftDeleteMixin, TimestampMixin


class CrawlerProject(TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "crawler_projects"
    __table_args__ = (UniqueConstraint("crawler_id", name="uq_project_crawler_id"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    workspace_id: Mapped[int] = mapped_column(BigInteger, index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    description: Mapped[str | None] = mapped_column(String(512), nullable=True)
    source_type: Mapped[str] = mapped_column(
        String(16), default="custom", nullable=False
    )  # builtin / custom
    builtin_crawler_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    crawler_id: Mapped[str] = mapped_column(String(128), nullable=False)
    run_config_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)  # once/cron/headless/webhook
    status: Mapped[str] = mapped_column(String(16), default="active", nullable=False)