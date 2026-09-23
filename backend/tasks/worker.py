"""后台任务 worker: 审计落库消费 + monitor(心跳巡检/容器回收)。

入口: python -m backend.worker [--monitor]
"""

from __future__ import annotations

import asyncio
import json
import logging

from ..config import settings
from ..db.session import SessionLocal
from ..redis.client import Redis, redis, TaskQueue
from ..services.audit import audit_write

log = logging.getLogger("cdc.worker")


async def consume_audit(rds: Redis, stop_event: asyncio.Event) -> None:
    q = TaskQueue(rds.client)
    queue = "audit"
    while not stop_event.is_set():
        try:
            await q.promote_delayed(queue)
            await q.recover_stale(queue)
            task = await q.lease(queue, timeout=5)
        except Exception as exc:  # noqa: BLE001
            log.warning("audit 队列读取失败: %s", exc)
            await asyncio.sleep(1)
            continue
        if task is None:
            continue
        try:
            async with SessionLocal() as session:
                await audit_write(session, task.payload)
            await q.ack(task)
        except Exception as exc:  # noqa: BLE001
            log.error("审计落库失败: %s", exc)
            outcome = await q.nack(task, max_attempts=5, delay_ms=2_000)
            if outcome == "dead":
                log.error("审计任务进入死信: %s", task.payload.get("_id"))


async def monitor_loop(kube, stop_event: asyncio.Event) -> None:
    """每 heartbeat_monitor_every 秒巡检: 失联进程 + 空闲容器回收。"""
    from ..services.dev_container import DevContainerService
    from ..services.heartbeat import HeartbeatMonitor

    dev_svc = DevContainerService(kube, rds=redis)
    hb_mon = HeartbeatMonitor(kube)
    while not stop_event.is_set():
        try:
            async with SessionLocal() as session:
                events = await hb_mon.sweep(session)
                for e in events:
                    log.info("heartbeat monitor: %s", e)

                # 空闲回收
                expired = await dev_svc.list_expired(session)
                for dc in expired:
                    from ..db.models import CrawlerProject

                    project = await session.get(CrawlerProject, dc.project_id)
                    if project:
                        log.info("回收空闲容器: project=%s phase=%s", project.id, dc.phase)
                        await dev_svc.recycle(session, project)

                # 超时未就绪兜底
                stuck = await dev_svc.list_failed_timeout(session)
                for dc in stuck:
                    if dc.phase == "starting":
                        dc.phase = "failed"
                        dc.error_code = "START_TIMEOUT"
                if stuck:
                    await session.commit()
        except Exception as exc:  # noqa: BLE001
            log.warning("monitor 巡检异常: %s", exc)
        await asyncio.sleep(settings.heartbeat_monitor_every)


async def run_worker(monitor: bool = False) -> None:
    stop_event = asyncio.Event()
    from ..k8s.client import FakeKubeClient, RealKubeClient

    try:
        kube = RealKubeClient(settings.k8s_namespace)
    except Exception:  # noqa: BLE001
        kube = FakeKubeClient()

    tasks = [asyncio.create_task(consume_audit(redis, stop_event))]
    if monitor:
        tasks.append(asyncio.create_task(monitor_loop(kube, stop_event)))
    try:
        await asyncio.gather(*tasks)
    finally:
        stop_event.set()
        await redis.close()


def main() -> None:
    import argparse
    import sys

    parser = argparse.ArgumentParser(description="CDC worker")
    parser.add_argument("--monitor", action="store_true", help="同时启动 monitor 巡检")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    try:
        asyncio.run(run_worker(monitor=args.monitor))
    except KeyboardInterrupt:
        sys.exit(0)


if __name__ == "__main__":
    main()