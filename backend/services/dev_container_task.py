"""开发容器异步任务调度/状态查询。

- `enqueue`: 投递 Celery 任务并记录任务↔项目/开始时间(Redis 热状态), 供超时判定。
- `get_task`: 读取 Celery 任务状态(通过线程执行, 避免阻塞事件循环)。
- `resolve_status`: 结合 DB phase + Celery state + 超时, 归一化为前端状态机:
  `pending / running / success / failed / timeout`。
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass

from ..config import settings
from ..db.models import DevContainer
from ..redis.client import HotState, redis

log = logging.getLogger("cdc.services.dev_container_task")

_TERMINAL = {"success", "failed", "timeout"}
_TASK_TTL_EXTRA = 300  # 任务元数据在超时后多保留的时间(秒)


@dataclass
class DevContainerTaskState:
    task_id: str
    state: str  # Celery state: PENDING/STARTED/PROGRESS/RETRY/SUCCESS/FAILURE/REVOKED
    info: dict | None
    project_id: int | None
    started_at: int | None


class DevContainerTaskService:
    def __init__(self, rds=None) -> None:
        self.rds = rds or redis

    # ---- Redis key ----
    @staticmethod
    def _key(task_id: str) -> str:
        return redis.k("devtask", task_id)

    # ---- 投递 ----
    @staticmethod
    def _enqueue_sync(project_id: int):
        from ..tasks.dev_container_tasks import ensure_dev_container

        return ensure_dev_container.apply_async(args=[project_id])

    async def enqueue(self, project_id: int) -> tuple[str, int]:
        """投递任务, 返回 (task_id, started_at 毫秒)。"""
        started_at = int(time.time() * 1000)
        result = await asyncio.to_thread(self._enqueue_sync, project_id)
        task_id = result.id
        try:
            await HotState(self.rds.client).set_json(
                self._key(task_id),
                {"project_id": project_id, "started_at": started_at},
                settings.dev_container_timeout + _TASK_TTL_EXTRA,
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("记录开发容器任务元数据失败: %s", exc)
        return task_id, started_at

    # ---- 状态 ----
    @staticmethod
    def _state_sync(task_id: str) -> tuple[str, dict | None]:
        from ..tasks.celery_app import celery_app

        result = celery_app.AsyncResult(task_id)
        info = result.info if result.ready() and isinstance(result.info, dict) else None
        return result.state, info

    async def get_task(self, task_id: str) -> DevContainerTaskState:
        meta = await HotState(self.rds.client).get_json(self._key(task_id)) or {}
        try:
            state, info = await asyncio.to_thread(self._state_sync, task_id)
        except Exception as exc:  # noqa: BLE001
            log.warning("读取 Celery 任务状态失败: %s", exc)
            state, info = "PENDING", None
        return DevContainerTaskState(
            task_id=task_id,
            state=state,
            info=info,
            project_id=meta.get("project_id"),
            started_at=meta.get("started_at"),
        )


def resolve_status(
    row: DevContainer | None, task: DevContainerTaskState | None
) -> tuple[str, str | None, int | None]:
    """归一化任务状态。

    返回 (status, error_code, elapsed_ms)。优先级:
    DB phase(权威) > Celery 终态 > 超时 > 进行中。
    """
    now = int(time.time() * 1000)
    started_at = task.started_at if task else None
    if started_at is None and row is not None:
        started_at = row.created_at
    elapsed = now - started_at if started_at else None

    if row is not None and row.phase == "ready":
        return "success", None, elapsed
    if row is not None and row.phase == "failed":
        code = row.error_code or "START_FAILED"
        return ("timeout" if code == "START_TIMEOUT" else "failed"), code, elapsed

    if task is not None and task.state == "FAILURE":
        return "failed", "TASK_FAILED", elapsed
    if elapsed is not None and elapsed > settings.dev_container_timeout * 1000:
        return "timeout", "START_TIMEOUT", elapsed
    if task is not None and task.state in ("STARTED", "PROGRESS", "RETRY"):
        return "running", None, elapsed
    if task is not None and task.state == "SUCCESS":
        info = task.info or {}
        if info.get("status") == "success":
            return "success", None, elapsed
        return "failed", info.get("error_code") or "START_FAILED", elapsed
    return "pending", None, elapsed


def is_terminal(status: str) -> bool:
    return status in _TERMINAL
