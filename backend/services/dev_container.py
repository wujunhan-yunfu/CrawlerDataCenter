"""开发容器编排服务: phase 状态机 + K8s 生命周期。

phase: absent → pending → starting → ready → stopping → absent
             └────────────→ failed
ready → stopping → absent (空闲 TTL 回收)
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..core.ids import snowflake_id
from ..db.models import CrawlerProject, DevContainer
from ..k8s.client import KubeClient
from ..k8s.templates import (
    DevPodSpec,
    build_dev_pod,
    build_dev_service,
    pod_name_for,
    service_name_for,
)
from ..redis.client import HotState

_DEV_STATE_TTL = 600
# 允许的迁移: 旧状态 -> {可迁移的新状态}
_ALLOWED = {
    "absent": {"pending"},
    "pending": {"starting", "failed"},
    "starting": {"ready", "failed"},
    "ready": {"stopping"},
    "stopping": {"absent", "failed"},
    "failed": {"pending"},
}


class DevContainerService:
    def __init__(self, kube: KubeClient, rds=None) -> None:
        self.kube = kube
        self.rds = rds

    async def _get_or_create_row(
        self, session: AsyncSession, project: CrawlerProject
    ) -> DevContainer:
        row = await session.scalar(
            select(DevContainer).where(DevContainer.project_id == project.id)
        )
        if row is None:
            row = DevContainer(
                id=snowflake_id(),
                project_id=project.id,
                workspace_id=project.workspace_id,
                crawler_id=project.crawler_id,
                phase="absent",
                namespace=settings.k8s_namespace,
            )
            session.add(row)
            await session.commit()
        return row

    @staticmethod
    def _transition(row: DevContainer, to: str, error_code: str | None = None) -> None:
        if row.phase not in _ALLOWED or to not in _ALLOWED[row.phase]:
            raise ValueError(f"非法容器状态迁移: {row.phase} -> {to}")
        row.phase = to
        row.error_code = error_code
        if to == "ready":
            row.last_active_at = int(time.time() * 1000)
            row.expires_at = row.last_active_at + settings.dev_container_idle_ttl * 1000
        if to == "failed":
            row.last_active_at = None
            row.expires_at = None

    async def ensure(
        self,
        session: AsyncSession,
        project: CrawlerProject,
    ) -> DevContainer:
        """确保 dev 容器就绪: 已 ready 直接返回; 否则创建 Pod 并轮询就绪。"""
        row = await self._get_or_create_row(session, project)
        if row.phase == "ready":
            self._touch(session, row)
            return row
        if row.phase == "failed":
            # 重试: 允许 failed -> pending, 同时重置计时基准, 避免复用旧 created_at 立即判超时
            row.phase = "absent"  # 通过 absent 中转以复用迁移规则
        if row.phase == "pending" or row.phase == "starting":
            # 已有容器在拉起中, 复用并轮询
            return row

        # absent -> pending
        row.created_at = int(time.time() * 1000)
        self._transition(row, "pending")
        await session.commit()

        # 配额校验
        quota = settings.workspace_container_quota
        ws_quota = (await self._workspace_quota(session, project.workspace_id)) or quota
        from ..services.project import ProjectService

        active = await ProjectService.count_active_containers(session, project.workspace_id)
        if active >= ws_quota:
            self._transition(row, "failed", "QUOTA_EXCEEDED")
            await session.commit()
            return row

        pod_spec = DevPodSpec(
            crawler_id=project.crawler_id,
            namespace=settings.k8s_namespace,
            image=settings.acs_image,
            mongo_uri=settings.mongo_uri if hasattr(settings, "mongo_uri") else "",
        )
        try:
            result = await self.kube.create_dev_pod(
                build_dev_pod(pod_spec),
                build_dev_service(project.crawler_id, settings.k8s_namespace),
            )
            row.pod_name = result.pod_name
            row.service_name = service_name_for(project.crawler_id)
        except Exception as exc:  # noqa: BLE001
            self._transition(row, "failed", "IMAGE_PULL_FAILED" if "ImagePull" in str(exc) else "CREATE_FAILED")
            await session.commit()
            return row

        self._transition(row, "starting")
        await session.commit()
        return row

    async def poll(
        self,
        session: AsyncSession,
        project: CrawlerProject,
        ttl: int | None = None,
    ) -> DevContainer:
        """就绪探针轮询: starting -> ready(探针通过) / failed(超时)。"""
        row = await self._get_or_create_row(session, project)

        # 开发模式不探测 Pod; 同时纠正历史数据里遗留的本地直连地址, 统一为代理路径
        if self.is_local_mode():
            if row.phase == "ready":
                expected = self.dev_url_for(project)
                if row.dev_url != expected:
                    row.dev_url = expected
                    row.pod_name = None
                    row.service_name = None
                    await session.commit()
            return row

        ttl = ttl if ttl is not None else settings.dev_container_timeout
        if row.phase != "starting" or not row.pod_name:
            return row

        try:
            status = await self.kube.get_pod_status(row.pod_name, row.namespace)
        except Exception:  # noqa: BLE001
            status = None

        if status is not None and status.ready:
            self._transition(row, "ready")
            row.dev_url = self.dev_url_for(project)
            await session.commit()
            if self.rds:
                await HotState(self.rds.client).set_json(
                    self._hot_key(row.project_id), self.to_dict(row), _DEV_STATE_TTL
                )
            return row

        if status is not None and status.phase == "Failed":
            self._transition(row, "failed", status.reason or "START_FAILED")
            await session.commit()
            return row

        # 超时判定
        created_ago = int(time.time() * 1000) - (row.created_at or 0)
        if created_ago > ttl * 1000:
            self._transition(row, "failed", "START_TIMEOUT")
            await session.commit()
            return row
        return row

    async def launch(
        self,
        session: AsyncSession,
        project: CrawlerProject,
        *,
        timeout: int | None = None,
        interval: float = 2.0,
        progress: Callable[[DevContainer], Awaitable[None] | None] | None = None,
    ) -> DevContainer:
        """拉起并阻塞轮询直到 ready/failed/超时(Celery 任务执行体)。

        与 `ensure` + 多次 `poll` 的组合等价, 但把"持续监听"收敛到服务层,
        便于异步任务一次执行到终态; 每次轮询可通过 progress 回调上报进度。

        开发模式下不创建 Pod, 直接置 ready 并返回与 Pod 模式**相同**的
        dev_url(经 CDC 代理访问), 仅代理上游指向本地 ACS。
        """
        if self.is_local_mode():
            row = await self.ensure_local(session, project)
            if progress is not None:
                result = progress(row)
                if asyncio.iscoroutine(result):
                    await result
            return row

        row = await self.ensure(session, project)
        limit = timeout if timeout is not None else settings.dev_container_timeout
        deadline = time.monotonic() + limit
        while row.phase in ("pending", "starting"):
            if progress is not None:
                result = progress(row)
                if asyncio.iscoroutine(result):
                    await result
            if time.monotonic() >= deadline:
                self._transition(row, "failed", "START_TIMEOUT")
                await session.commit()
                break
            await asyncio.sleep(interval)
            row = await self.poll(session, project, ttl=timeout)
        return row

    @staticmethod
    def is_local_mode() -> bool:
        """开发模式: 不拉起 K8s, 直接访问本地 ACS。"""
        return settings.use_local_dev_container

    @staticmethod
    def dev_url_for(project: CrawlerProject) -> str:
        """对外访问地址(与 Pod 模式一致, 经 CDC 反向代理)。"""
        return f"/dev/{project.workspace_id}/{project.id}"

    @staticmethod
    def upstream_url(project: CrawlerProject, row: DevContainer | None = None) -> str:
        """代理上游: 开发模式 -> 本地 ACS; 集群模式 -> K8s Service。

        对外 dev_url/路由前缀与代理方式不变, 仅上游目标不同。
        """
        if settings.use_local_dev_container:
            return settings.acs_local_url
        service = (row.service_name if row else None) or service_name_for(project.crawler_id)
        namespace = (row.namespace if row else None) or settings.k8s_namespace
        return f"http://{service}.{namespace}.svc.cluster.local:8080"

    async def ensure_local(
        self, session: AsyncSession, project: CrawlerProject
    ) -> DevContainer:
        """开发模式: 跳过 Pod 拉起, 直接置 ready(dev_url 与 Pod 模式相同)。"""
        row = await self._get_or_create_row(session, project)
        if row.phase in ("failed", "stopping"):
            row.phase = "absent"
        if row.phase == "absent":
            self._transition(row, "pending")
        if row.phase == "pending":
            self._transition(row, "starting")
        if row.phase == "starting":
            self._transition(row, "ready")
        elif row.phase == "ready":
            self._touch(session, row)
        row.dev_url = self.dev_url_for(project)
        row.pod_name = None
        row.service_name = None
        await session.commit()
        if self.rds:
            await HotState(self.rds.client).set_json(
                self._hot_key(row.project_id), self.to_dict(row), _DEV_STATE_TTL
            )
        return row

    def _touch(self, session: AsyncSession, row: DevContainer) -> None:
        row.last_active_at = int(time.time() * 1000)
        row.expires_at = row.last_active_at + settings.dev_container_idle_ttl * 1000
        session.add(row)

    async def touch(self, session: AsyncSession, project: CrawlerProject) -> None:
        row = await self._get_or_create_row(session, project)
        if row.phase == "ready":
            self._touch(session, row)
            await session.commit()

    async def stop(self, session: AsyncSession, project: CrawlerProject) -> DevContainer:
        row = await self._get_or_create_row(session, project)
        if row.phase == "ready":
            self._transition(row, "stopping")
            await session.commit()
        return row

    async def recycle(self, session: AsyncSession, project: CrawlerProject) -> None:
        """回收: 删除 Pod/Service, phase -> absent。"""
        row = await self._get_or_create_row(session, project)
        if row.pod_name:
            await self.kube.delete_pod(row.pod_name, row.namespace)
        if row.service_name:
            await self.kube.delete_service(row.service_name, row.namespace)
        row.pod_name = None
        row.service_name = None
        row.dev_url = None
        # 按状态机逐级迁移: ready -> stopping -> absent
        if row.phase in ("ready", "starting"):
            self._transition(row, "stopping")
            await session.flush()
        if row.phase == "stopping":
            self._transition(row, "absent")
        await session.commit()

    @staticmethod
    async def _workspace_quota(session: AsyncSession, ws_id: int) -> int | None:
        """预留: 从 Workspace.quota_json 读取容器并发配额。"""
        from ..db.models import Workspace

        ws = await session.get(Workspace, ws_id)
        if ws and ws.quota_json:
            val = ws.quota_json.get("container_quota")
            if isinstance(val, int) and val > 0:
                return val
        return None

    @staticmethod
    def _hot_key(project_id: int) -> str:
        return f"cdc:dev:{project_id}"

    @staticmethod
    def to_dict(row: DevContainer) -> dict:
        return {
            "project_id": row.project_id,
            "crawler_id": row.crawler_id,
            "phase": row.phase,
            "dev_url": row.dev_url,
            "pod_name": row.pod_name,
            "error_code": row.error_code,
            "last_active_at": row.last_active_at,
            "expires_at": row.expires_at,
        }

    async def get(self, session: AsyncSession, project: CrawlerProject) -> DevContainer:
        return await self._get_or_create_row(session, project)

    async def list_expired(self, session: AsyncSession) -> list[DevContainer]:
        now = int(time.time() * 1000)
        rows = (
            await session.execute(
                select(DevContainer).where(
                    DevContainer.phase == "ready",
                    DevContainer.expires_at.is_not(None),
                    DevContainer.expires_at < now,
                )
            )
        ).scalars().all()
        return list(rows)

    async def list_failed_timeout(self, session: AsyncSession) -> list[DevContainer]:
        """超时未就绪的 pending/starting 容器(monitor 兜底置 failed)。"""
        now = int(time.time() * 1000)
        rows = (
            await session.execute(
                select(DevContainer).where(
                    DevContainer.phase.in_(("pending", "starting")),
                    DevContainer.created_at < now - settings.dev_container_timeout * 1000,
                )
            )
        ).scalars().all()
        return list(rows)