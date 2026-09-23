"""调度 / 心跳巡检 / 审计队列测试。"""

from __future__ import annotations

import time

import pytest

from backend.services.cron import next_run_ms, validate_cron


def test_validate_cron():
    assert validate_cron("*/30 * * * *")
    assert validate_cron("0 9 * * 1-5")
    assert not validate_cron("not a cron")
    assert not validate_cron("")


def test_next_run_ms_in_future():
    now = int(time.time() * 1000)
    nxt = next_run_ms("*/1 * * * *")
    assert nxt > now


async def test_audit_queue_roundtrip(client, rds, monkeypatch):
    from backend.redis.client import TaskQueue
    from backend.tasks import worker as worker_module
    from backend.tasks.worker import consume_audit
    import asyncio

    ac, session_factory, _ = client
    # worker 使用全局 SessionLocal, 测试中替换为内存库会话工厂
    monkeypatch.setattr(worker_module, "SessionLocal", session_factory)
    q = TaskQueue(rds.client)
    await q.push("audit", {"actor_id": 1, "action": "test", "created_at": int(time.time() * 1000)})

    stop = asyncio.Event()

    async def _stop_after():
        await asyncio.sleep(1)
        stop.set()

    stop_task = asyncio.create_task(_stop_after())
    await consume_audit(rds, stop)
    await stop_task

    from backend.db.models import AuditLog
    from sqlalchemy import select

    async with session_factory() as session:
        row = await session.scalar(select(AuditLog).where(AuditLog.action == "test"))
        assert row is not None
        assert row.actor_id == 1


async def test_heartbeat_monitor_marks_unreachable(client, session_factory, kube):
    from backend.core.ids import snowflake_id
    from backend.db.models import CrawlerProject, RunProcess
    from backend.services.heartbeat import HeartbeatMonitor

    async with session_factory() as session:
        project = CrawlerProject(id=snowflake_id(), workspace_id=snowflake_id(), name="p", crawler_id="proj_m")
        session.add(project)
        await session.flush()
        # 很久没有心跳的进程
        session.add(
            RunProcess(
                id=snowflake_id(), process_id="proc_stale", project_id=project.id,
                crawler_id="proj_m", workspace_id=project.workspace_id,
                run_type="cron", pod_name="acs-run-proj-m-0", status="alive",
                started_at=int(time.time() * 1000) - 3_600_000,
                last_heartbeat_at=int(time.time() * 1000) - 3_600_000,
            )
        )
        await session.commit()

    mon = HeartbeatMonitor(kube, max_degraded=3)
    async with session_factory() as session:
        events = await mon.sweep(session)
    assert any(e["process_id"] == "proc_stale" and e["event"] == "unreachable" for e in events)


async def test_scheduler_trigger_once_creates_job(client, session_factory, auth_headers, kube):
    """通过 API 触发 once run, 校验 K8s Job 创建与运行记录。"""
    ac, _, _ = client
    ws = (await ac.post("/api/v1/workspaces", json={"name": "ws-run"}, headers=auth_headers)).json()
    proj = (
        await ac.post(
            f"/api/v1/workspaces/{ws['id']}/projects",
            json={"name": "r", "source_type": "custom"},
            headers=auth_headers,
        )
    ).json()
    resp = await ac.post(
        f"/api/v1/projects/{proj['id']}/runs",
        json={"trigger": "once", "headless": True},
        headers=auth_headers,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "pending"
    assert kube.jobs  # FakeKubeClient 收到 Job 创建


async def test_scheduler_trigger_cron_invalid(client, auth_headers):
    ac, _, _ = client
    ws = (await ac.post("/api/v1/workspaces", json={"name": "ws-cron"}, headers=auth_headers)).json()
    proj = (
        await ac.post(
            f"/api/v1/workspaces/{ws['id']}/projects",
            json={"name": "c", "source_type": "custom"},
            headers=auth_headers,
        )
    ).json()
    resp = await ac.post(
        f"/api/v1/projects/{proj['id']}/runs",
        json={"trigger": "cron", "cron": "bad expr"},
        headers=auth_headers,
    )
    assert resp.status_code == 400


async def test_monitor_loop_recycles_idle_and_marks_unreachable(client, session_factory, kube, monkeypatch):
    """monitor 巡检: 回收空闲容器 + 失联进程标记 unreachable。"""
    import asyncio

    from backend.core.ids import snowflake_id
    from backend.db.models import CrawlerProject, DevContainer, RunProcess
    from backend.services.dev_container import DevContainerService
    from backend.tasks import worker as worker_module
    from backend.tasks.worker import monitor_loop

    monkeypatch.setattr(worker_module, "SessionLocal", session_factory)
    now = int(time.time() * 1000)
    async with session_factory() as session:
        ws = snowflake_id()
        project = CrawlerProject(id=snowflake_id(), workspace_id=ws, name="p", crawler_id="proj_mon")
        session.add(project)
        await session.flush()
        # 空闲超时的 ready 容器
        session.add(
            DevContainer(
                id=snowflake_id(), project_id=project.id, workspace_id=ws,
                crawler_id="proj_mon", pod_name="acs-dev-proj-mon",
                service_name="acs-dev-proj-mon", phase="ready",
                last_active_at=now - 3_600_000, expires_at=now - 1000,
                created_at=now - 3_600_000,
            )
        )
        # 失联的 cron 进程
        session.add(
            RunProcess(
                id=snowflake_id(), process_id="proc_stale2", project_id=project.id,
                crawler_id="proj_mon", workspace_id=ws, run_type="cron",
                pod_name="acs-run-proj-mon-0", status="alive",
                started_at=now - 3_600_000, last_heartbeat_at=now - 3_600_000,
            )
        )
        await session.commit()

    stop = asyncio.Event()

    async def _stop_soon():
        await asyncio.sleep(1.5)
        stop.set()

    stop_task = asyncio.create_task(_stop_soon())
    await monitor_loop(kube, stop)
    await stop_task

    assert any(name for name, kind in kube.deleted if kind == "pod")
    async with session_factory() as session:
        from backend.db.models import RunProcess as RP
        from sqlalchemy import select

        proc = await session.scalar(select(RP).where(RP.process_id == "proc_stale2"))
        assert proc.status == "unreachable"


async def test_scheduler_trigger_cron_creates_deployment(client, auth_headers, kube):
    ac, _, _ = client
    ws = (await ac.post("/api/v1/workspaces", json={"name": "ws-cron2"}, headers=auth_headers)).json()
    proj = (
        await ac.post(
            f"/api/v1/workspaces/{ws['id']}/projects",
            json={"name": "c2", "source_type": "custom"},
            headers=auth_headers,
        )
    ).json()
    resp = await ac.post(
        f"/api/v1/projects/{proj['id']}/runs",
        json={"trigger": "cron", "cron": "*/30 * * * *"},
        headers=auth_headers,
    )
    assert resp.status_code == 200, resp.text
    assert kube.deployments
    assert resp.json()["status"] == "running"