"""数据条目(data.saved 落库)模型。"""

from __future__ import annotations

from sqlalchemy import JSON, BigInteger, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from ..base import Base, TimestampMixin


class DataItem(TimestampMixin, Base):
    """每次 data.saved 推送一行。幂等键 (run_id, save_id)。"""

    __tablename__ = "data_items"
    __table_args__ = (
        UniqueConstraint("run_id", "save_id", name="uq_data_run_save"),
        UniqueConstraint("run_id", "seq", name="uq_data_run_seq"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    run_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    crawler_id: Mapped[str] = mapped_column(String(128), index=True, nullable=False)
    project_id: Mapped[int] = mapped_column(BigInteger, index=True, nullable=False)
    workspace_id: Mapped[int] = mapped_column(BigInteger, index=True, nullable=False)
    save_id: Mapped[str] = mapped_column(String(64), nullable=False)
    seq: Mapped[int] = mapped_column(default=0, nullable=False)
    kind: Mapped[str] = mapped_column(String(16), default="content", nullable=False)
    fmt: Mapped[str] = mapped_column(String(16), default="json", nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    size: Mapped[int] = mapped_column(default=0, nullable=False)
    content_hash: Mapped[str | None] = mapped_column(String(128), nullable=True)
    content_type: Mapped[str | None] = mapped_column(String(128), nullable=True)
    encoding: Mapped[str] = mapped_column(String(16), default="utf-8", nullable=False)
    content: Mapped[str | None] = mapped_column(Text, nullable=True)
    storage_backend: Mapped[str] = mapped_column(String(16), default="inline", nullable=False)
    storage_path: Mapped[str | None] = mapped_column(String(512), nullable=True)
    source_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    collected_at: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    meta_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="stored", nullable=False)  # stored/failed