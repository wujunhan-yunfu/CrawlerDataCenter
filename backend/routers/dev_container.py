"""开发容器路由: 拉起(Celery 异步任务) / 任务状态轮询 / 容器状态 / 回收。

`POST /projects/{id}/dev-container` 统一投递 Celery 任务 `cdc.dev_container.ensure`,
返回 `task_id`; 前端循环 `GET /projects/{id}/dev-container/tasks/{task_id}` 直到
`success / failed / timeout`。

开发模式(`settings.use_local_dev_container`)只是在**任务内部**跳过 Pod 拉起,
`dev_url` / 路由前缀 / 代理方式与 Pod 模式完全一致(上游指向本地 ACS)。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from ..api.deps import get_current_user, get_dev_service, get_dev_task_service
from ..api.errors import bad_request, not_found
from ..db.models import CrawlerProject, User
from ..db.session import get_db
from ..rbac.service import has_permission
from ..redis.client import Redis, redis
from ..schemas.webhook import DevContainerOut, DevContainerTaskOut
from ..services.dev_container import DevContainerService
from ..services.dev_container_task import DevContainerTaskService, resolve_status
from ..services.project import ProjectService

router = APIRouter(tags=["dev-container"])

_STATUS_MESSAGES = {
    "pending": "任务已提交，等待执行",
    "running": "容器拉起中，请稍候",
    "success": "开发容器已就绪",
    "failed": "开发容器拉起失败",
    "timeout": "开发容器拉起超时，可重试",
}


async def _project_for(db: AsyncSession, project_id: int, user: User) -> CrawlerProject:
    project = await ProjectService.get(db, project_id)
    if project is None:
        raise not_found("project_not_found", "项目不存在")
    if project.source_type != "custom":
        raise bad_request("builtin_no_container", "内置爬取器项目不提供开发容器")
    grant = await has_permission(db, user.id, "container:manage", workspace_id=project.workspace_id, project_id=project.id)
    if not grant.granted:
        from ..api.errors import forbidden

        raise forbidden("forbidden")
    return project


@router.post("/projects/{project_id}/dev-container", response_model=DevContainerTaskOut)
async def ensure_dev_container(
    project_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
    dev: DevContainerService = Depends(get_dev_service),
    tasks: DevContainerTaskService = Depends(get_dev_task_service),
):
    project = await _project_for(db, project_id, user)
    mode = "local" if dev.is_local_mode() else "k8s"

    row = await dev.get(db, project)
    if row.phase == "ready":
        if dev.is_local_mode():
            row = await dev.ensure_local(db, project)
        else:
            await dev.touch(db, project)
        return DevContainerTaskOut(
            task_id=None,
            project_id=project.id,
            status="success",
            phase=row.phase,
            mode=mode,
            dev_url=row.dev_url,
            pod_name=row.pod_name,
            message="开发容器已就绪",
            started_at=row.last_active_at,
            elapsed_ms=0,
        )

    try:
        task_id, started_at = await tasks.enqueue(project.id)
    except Exception as exc:  # noqa: BLE001
        from ..api.errors import service_unavailable

        raise service_unavailable("task_enqueue_failed", f"任务投递失败: {exc}")

    return DevContainerTaskOut(
        task_id=task_id,
        project_id=project.id,
        status="pending",
        phase="pending",
        mode=mode,
        dev_url=None,
        pod_name=row.pod_name,
        message=_STATUS_MESSAGES["pending"],
        started_at=started_at,
        elapsed_ms=0,
    )


@router.get(
    "/projects/{project_id}/dev-container/tasks/{task_id}",
    response_model=DevContainerTaskOut,
)
async def get_dev_container_task(
    project_id: int,
    task_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
    dev: DevContainerService = Depends(get_dev_service),
    tasks: DevContainerTaskService = Depends(get_dev_task_service),
):
    project = await _project_for(db, project_id, user)
    task = await tasks.get_task(task_id)
    # 任务元数据存在时校验归属, 防止跨项目窥探
    if task.project_id is not None and task.project_id != project.id:
        raise not_found("task_not_found", "任务不存在")

    row = await dev.get(db, project)
    status, error_code, elapsed = resolve_status(row, task)
    return DevContainerTaskOut(
        task_id=task_id,
        project_id=project.id,
        status=status,
        phase=row.phase if row else "absent",
        mode="local" if dev.is_local_mode() else "k8s",
        dev_url=row.dev_url if row else None,
        pod_name=row.pod_name if row else None,
        error_code=error_code,
        message=_STATUS_MESSAGES.get(status),
        started_at=task.started_at,
        elapsed_ms=elapsed,
    )


@router.get("/projects/{project_id}/dev-container", response_model=DevContainerOut)
async def poll_dev_container(
    project_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
    dev: DevContainerService = Depends(get_dev_service),
):
    project = await _project_for(db, project_id, user)
    row = await dev.poll(db, project)
    return row


@router.delete("/projects/{project_id}/dev-container")
async def recycle_dev_container(
    project_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
    dev: DevContainerService = Depends(get_dev_service),
):
    project = await _project_for(db, project_id, user)
    await dev.recycle(db, project)
    return {"ok": True}
