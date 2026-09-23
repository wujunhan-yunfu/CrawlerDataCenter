"""开发容器编排服务: phase 状态机 + K8s 生命周期。

phase: absent → pending → starting → ready → stopping → absent
             └────────────→ failed
ready → stopping → absent (空闲 TTL 回收)
"""

from __future__ import annotations

import time

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
            # 重试: 允许 failed -> pending
            row.phase = "absent"  # 通过 absent 中转以复用迁移规则
        if row.phase == "pending" or row.phase == "starting":
            # 已有容器在拉起中, 复用并轮询
            return row

        # absent -> pending
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
        ttl = ttl or settings.dev_container_timeout
        if row.phase != "starting" or not row.pod_name:
            return row

        try:
            status = await self.kube.get_pod_status(row.pod_name, row.namespace)
        except Exception:  # noqa: BLE001
            status = None

        if status is not None and status.ready:
            self._transition(row, "ready")
            row.dev_url = f"/dev/{project.workspace_id}/{project.id}"
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
        """超时未就绪的 starting 容器(monitor 兜底置 failed)。"""
        now = int(time.time() * 1000)
        rows = (
            await session.execute(
                select(DevContainer).where(
                    DevContainer.phase == "starting",
                    DevContainer.created_at < now - settings.dev_container_timeout * 1000,
                )
            )
        ).scalars().all()
        return list(rows)