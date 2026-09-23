"""运行记录 / 定时进程 / 运行结果模型。"""

from __future__ import annotations

from sqlalchemy import JSON, BigInteger, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from ..base import Base, TimestampMixin


class Run(TimestampMixin, Base):
    __tablename__ = "runs"
    __table_args__ = (UniqueConstraint("run_id", name="uq_run_id"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    run_id: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    project_id: Mapped[int] = mapped_column(BigInteger, index=True, nullable=False)
    crawler_id: Mapped[str] = mapped_column(String(128), index=True, nullable=False)
    workspace_id: Mapped[int] = mapped_column(BigInteger, index=True, nullable=False)
    mode: Mapped[str] = mapped_column(String(16), default="run", nullable=False)  # login / run
    trigger: Mapped[str] = mapped_column(String(16), default="once", nullable=False)  # once / cron
    run_type: Mapped[str] = mapped_column(String(16), default="once", nullable=False)
    cron: Mapped[str | None] = mapped_column(String(128), nullable=True)
    process_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    attempt: Mapped[int] = mapped_column(default=1, nullable=False)
    status: Mapped[str] = mapped_column(
        String(16), default="pending", nullable=False
    )  # pending/running/succeeded/failed/skipped
    started_at: Mapped[int] = mapped_column(BigInteger, nullable=False)
    finished_at: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    error_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)  # {type,message,detail,stage}
    next_run_at: Mapped[int | None] = mapped_column(BigInteger, nullable=True)


class RunProcess(TimestampMixin, Base):
    """cron 常驻进程元数据, 由心跳更新。"""

    __tablename__ = "run_processes"
    __table_args__ = (UniqueConstraint("process_id", name="uq_process_id"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    process_id: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    project_id: Mapped[int] = mapped_column(BigInteger, index=True, nullable=False)
    crawler_id: Mapped[str] = mapped_column(String(128), index=True, nullable=False)
    workspace_id: Mapped[int] = mapped_column(BigInteger, index=True, nullable=False)
    run_type: Mapped[str] = mapped_column(String(16), default="cron", nullable=False)
    cron: Mapped[str | None] = mapped_column(String(128), nullable=True)
    pod_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    status: Mapped[str] = mapped_column(
        String(16), default="alive", nullable=False
    )  # alive/running/degraded/stopping/stopped/unreachable
    pid: Mapped[int | None] = mapped_column(nullable=True)
    started_at: Mapped[int] = mapped_column(BigInteger, nullable=False)
    last_heartbeat_at: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    uptime_ms: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    next_run_at: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    last_run_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    health_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    degraded_count: Mapped[int] = mapped_column(default=0, nullable=False)


class RunResult(Base):
    """运行产物索引(run 结束事件汇总写入)。"""

    __tablename__ = "run_results"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    run_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    kind: Mapped[str] = mapped_column(String(16), default="content", nullable=False)
    size: Mapped[int] = mapped_column(default=0, nullable=False)
    save_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    delivery: Mapped[str] = mapped_column(String(16), default="local", nullable=False)
    remote_path: Mapped[str | None] = mapped_column(String(512), nullable=True)
    content_hash: Mapped[str | None] = mapped_column(String(128), nullable=True)