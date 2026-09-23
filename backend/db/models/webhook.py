"""webhook 投递记录模型(入站/出站通用)。"""

from __future__ import annotations

from sqlalchemy import BigInteger, JSON, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from ..base import Base, TimestampMixin


class WebhookDelivery(TimestampMixin, Base):
    """入站接收记录。幂等键 (kind, event, delivery_id)。"""

    __tablename__ = "webhook_deliveries"
    __table_args__ = (
        UniqueConstraint("kind", "event", "delivery_id", name="uq_webhook_delivery"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    delivery_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)  # run / heartbeat / data
    event: Mapped[str] = mapped_column(String(32), nullable=False)
    run_id: Mapped[str | None] = mapped_column(String(64), index=True, nullable=True)
    save_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    attempt: Mapped[int] = mapped_column(default=1, nullable=False)
    status_code: Mapped[int | None] = mapped_column(nullable=True)
    response_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    error: Mapped[str | None] = mapped_column(String(512), nullable=True)
    source_ip: Mapped[str | None] = mapped_column(String(64), nullable=True)
    accepted: Mapped[bool | None] = mapped_column(nullable=True)
    next_retry_at: Mapped[int | None] = mapped_column(BigInteger, nullable=True)


class WebhookEvent(Base):
    """入站事件原始载荷(审计/重放排查用)。"""

    __tablename__ = "webhook_events"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    delivery_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    event: Mapped[str] = mapped_column(String(32), nullable=False)
    payload_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    received_at: Mapped[int] = mapped_column(BigInteger, nullable=False)