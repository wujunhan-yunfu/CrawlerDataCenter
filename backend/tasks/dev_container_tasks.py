"""开发容器异步拉起 Celery 任务。

页面点击"拉起 / 刷新容器" → API `POST /projects/{id}/dev-container` 投递本任务
→ 任务通过 K8s 创建/复用 dev Pod 并轮询就绪 → 页面轮询
`GET /projects/{id}/dev-container/tasks/{task_id}` 直到 success/failed/timeout。

任务在独立进程执行, 因此:
- 每次执行新建 async engine/session, 结束后释放(避免跨事件循环复用连接);
- 复用 `DevContainerService.launch` 的 phase 状态机与就绪探针逻辑;
- 通过 `update_state(PROGRESS)` 上报中间 phase。
"""

from __future__ import annotations

import asyncio
import logging

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ..config import settings
from ..db.models import CrawlerProject
from ..db.session import build_engine
from ..k8s.client import build_kube_client
from ..redis.client import Redis
from ..services.dev_container import DevContainerService
from .celery_app import celery_app

log = logging.getLogger("cdc.tasks.dev_container")


def _progress_payload(project_id: int, phase: str, error_code: str | None) -> dict:
    return {"project_id": project_id, "phase": phase, "error_code": error_code}


@celery_app.task(
    bind=True,
    name="cdc.dev_container.ensure",
    soft_time_limit=settings.celery_task_soft_time_limit,
    time_limit=settings.celery_task_time_limit,
)
def ensure_dev_container(self, project_id: int) -> dict:
    """拉起开发容器并阻塞到终态, 返回最终状态快照。"""
    try:
        return asyncio.run(_ensure_dev_container(self, project_id))
    except Exception:  # noqa: BLE001
        log.exception("开发容器拉起任务异常: project=%s", project_id)
        raise


async def _ensure_dev_container(task, project_id: int) -> dict:
    engine = build_engine()
    Session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    rds = Redis()
    try:
        kube = build_kube_client()
        async with Session() as session:
            project = await session.get(CrawlerProject, project_id)
            if project is None:
                raise ValueError(f"项目不存在: {project_id}")

            svc = DevContainerService(kube, rds=rds)

            async def report(row) -> None:
                task.update_state(
                    state="PROGRESS",
                    meta=_progress_payload(project_id, row.phase, row.error_code),
                )

            row = await svc.launch(session, project, progress=report)
            return {
                "project_id": project_id,
                "phase": row.phase,
                "status": "success" if row.phase == "ready" else "failed",
                "dev_url": row.dev_url,
                "error_code": row.error_code,
            }
    finally:
        await engine.dispose()
        await rds.close()
