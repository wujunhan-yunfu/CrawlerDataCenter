"""心跳巡检: 判定定时进程失联/降级, 触发告警与重启(见 docs/scheduler-heartbeat-data.md)。"""

from __future__ import annotations

import time

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..db.models import RunProcess


class HeartbeatMonitor:
    def __init__(self, kube, max_degraded: int = 3) -> None:
        self.kube = kube
        self.max_degraded = max_degraded

    async def sweep(self, session: AsyncSession) -> list[dict]:
        """巡检一轮, 返回处理记录。"""
        now = int(time.time() * 1000)
        threshold = settings.heartbeat_unreachable_ms
        processes = (
            await session.execute(
                select(RunProcess).where(
                    RunProcess.status.in_(("alive", "running", "degraded")),
                    RunProcess.pod_name.is_not(None),
                )
            )
        ).scalars().all()

        events: list[dict] = []
        for p in processes:
            last = p.last_heartbeat_at
            if last is None or now - last > threshold:
                p.status = "unreachable"
                events.append({"process_id": p.process_id, "event": "unreachable"})
                if p.pod_name:
                    await self._restart(session, p)
                continue
            # 连续降级升级为重启
            if p.status == "degraded" and p.degraded_count >= self.max_degraded:
                events.append({"process_id": p.process_id, "event": "restart_after_degraded"})
                await self._restart(session, p)
                p.degraded_count = 0
        await session.commit()
        return events

    async def _restart(self, session: AsyncSession, p: RunProcess) -> None:
        """删除 Deployment Pod 以触发重建; 状态保持 unreachable, 等真实心跳恢复。"""
        if not p.pod_name:
            return
        try:
            await self.kube.delete_deployment(p.pod_name, settings.k8s_namespace)
        except Exception:  # noqa: BLE001
            return

    async def process_status(self, session: AsyncSession, process_id: str) -> RunProcess | None:
        return await session.scalar(select(RunProcess).where(RunProcess.process_id == process_id))