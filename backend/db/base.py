"""SQLAlchemy 声明基类与通用 Mixin。"""

from __future__ import annotations

import time
from datetime import datetime, timezone

from sqlalchemy import BigInteger, DateTime, Integer, String, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def _now_ts() -> int:
    return int(time.time() * 1000)


class Base(DeclarativeBase):
    pass


class IdMixin:
    """雪花式整数主键。"""

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)


class TimestampMixin:
    created_at: Mapped[int] = mapped_column(BigInteger, default=_now_ts, nullable=False)
    updated_at: Mapped[int] = mapped_column(
        BigInteger, default=_now_ts, onupdate=_now_ts, nullable=False
    )


class SoftDeleteMixin:
    deleted_at: Mapped[int | None] = mapped_column(BigInteger, nullable=True, default=None)

    def soft_delete(self) -> None:
        self.deleted_at = _now_ts()


class UTCTimestampMixin:
    """创建/更新时间(带时区), 供审计等场景。"""

    created_at_dt: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )