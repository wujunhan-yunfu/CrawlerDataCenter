"""webhook 接收测试: 签名 / 幂等 / 状态机 / run 更新 / 心跳 / 数据入库。"""

from __future__ import annotations

import hashlib
import hmac
import json
import time

from backend.config import settings
from backend.core.ids import snowflake_id
from backend.db.models import CrawlerProject, DataItem, Run, RunProcess, RunResult, WebhookDelivery
from sqlalchemy import select


def _secret():
    return settings.webhook_secret or settings.jwt_secret


def _sign(body: bytes, timestamp: str) -> str:
    digest = hmac.new(
        _secret().encode(), f"{timestamp}.".encode() + body, hashlib.sha256
    ).hexdigest()
    return f"sha256={digest}"


def _headers(event: str, delivery: str, body: bytes, ts: str | None = None, sig: str | None = None):
    ts = ts or str(int(time.time() * 1000))
    return {
        "X-Webhook-Event": event,
        "X-Webhook-Delivery": delivery,
        "X-Webhook-Timestamp": ts,
        "X-Webhook-Signature": sig or _sign(body, ts),
        "Content-Type": "application/json",
    }


def _run_payload(run_id: str, status: str, event: str) -> dict:
    now = int(time.time() * 1000)
    return {
        "event": event,
        "delivery_id": "dlv_test",
        "timestamp": now,
        "run": {
            "run_id": run_id,
            "crawler_id": "proj_abc",
            "project_id": "1",
            "workspace_id": "1",
            "mode": "run",
            "trigger": "once",
            "run_type": "once",
            "process_id": "proc_abc",
            "attempt": 1,
            "status": status,
            "started_at": now - 5000,
            "finished_at": now,
            "duration_ms": 5000,
            "error": None if status == "succeeded" else {"type": "login_failed", "message": "登录失败", "detail": "..."},
            "saved": [{"name": "a.json", "kind": "content", "size": 10, "save_id": "sav_1", "delivery": "delivered", "remote_path": "s3://x/a.json"}],
        },
    }


async def _make_project(session_factory) -> CrawlerProject:
    async with session_factory() as session:
        project = CrawlerProject(
            id=snowflake_id(), workspace_id=snowflake_id(), name="p", crawler_id="proj_abc"
        )
        session.add(project)
        await session.commit()
        return project


async def test_run_webhook_full_lifecycle(client, session_factory):
    ac, _, _ = client
    project = await _make_project(session_factory)
    run_id = "run_test_1"

    async with session_factory() as session:
        run = Run(
            id=snowflake_id(), run_id=run_id, project_id=project.id,
            crawler_id=project.crawler_id, workspace_id=project.workspace_id,
            status="pending", started_at=int(time.time() * 1000),
        )
        session.add(run)
        await session.commit()

    # started
    body = json.dumps(_run_payload(run_id, "running", "run.started"), ensure_ascii=False).encode()
    resp = await ac.post("/api/v1/webhooks/runs", content=body, headers=_headers("run.started", "dlv_start", body))
    assert resp.status_code == 200, resp.text
    assert resp.json()["accepted"] is True

    # succeeded
    body = json.dumps(_run_payload(run_id, "succeeded", "run.succeeded"), ensure_ascii=False).encode()
    resp = await ac.post("/api/v1/webhooks/runs", content=body, headers=_headers("run.succeeded", "dlv_succ", body))
    assert resp.status_code == 200, resp.text

    async with session_factory() as session:
        run = await session.scalar(select(Run).where(Run.run_id == run_id))
        assert run.status == "succeeded"
        result = await session.scalar(select(RunResult).where(RunResult.run_id == run_id))
        assert result.save_id == "sav_1"


async def test_webhook_idempotency(client, session_factory):
    ac, _, _ = client
    project = await _make_project(session_factory)
    run_id = "run_test_2"
    async with session_factory() as session:
        session.add(Run(id=snowflake_id(), run_id=run_id, project_id=project.id, crawler_id="proj_abc", workspace_id=project.workspace_id, status="pending", started_at=int(time.time() * 1000)))
        await session.commit()

    body = json.dumps(_run_payload(run_id, "running", "run.started"), ensure_ascii=False).encode()
    headers = _headers("run.started", "dlv_dup", body)
    r1 = await ac.post("/api/v1/webhooks/runs", content=body, headers=headers)
    assert r1.json()["accepted"] is True
    r2 = await ac.post("/api/v1/webhooks/runs", content=body, headers=headers)
    assert r2.status_code == 200
    assert r2.json()["accepted"] is False
    assert r2.json()["reason"] == "duplicate"


async def test_webhook_bad_signature(client):
    ac, _, _ = client
    body = json.dumps({"event": "run.started", "run": {}}).encode()
    headers = _headers("run.started", "dlv_bad", body, sig="sha256=deadbeef")
    resp = await ac.post("/api/v1/webhooks/runs", content=body, headers=headers)
    assert resp.status_code == 401
    assert resp.json()["error"] == "invalid_signature"


async def test_webhook_stale_timestamp(client):
    ac, _, _ = client
    body = json.dumps({"event": "run.started"}).encode()
    old_ts = str(int(time.time() * 1000) - 3600_000)
    headers = _headers("run.started", "dlv_old", body, ts=old_ts)
    resp = await ac.post("/api/v1/webhooks/runs", content=body, headers=headers)
    assert resp.status_code == 401
    assert resp.json()["error"] == "invalid_signature"


async def test_webhook_state_conflict(client, session_factory):
    ac, _, _ = client
    project = await _make_project(session_factory)
    run_id = "run_test_3"
    async with session_factory() as session:
        session.add(Run(id=snowflake_id(), run_id=run_id, project_id=project.id, crawler_id="proj_abc", workspace_id=project.workspace_id, status="succeeded", started_at=int(time.time() * 1000)))
        await session.commit()

    body = json.dumps(_run_payload(run_id, "failed", "run.failed"), ensure_ascii=False).encode()
    resp = await ac.post("/api/v1/webhooks/runs", content=body, headers=_headers("run.failed", "dlv_conflict", body))
    assert resp.status_code == 409
    assert resp.json()["error"] == "state_conflict"


async def test_webhook_run_not_found(client):
    ac, _, _ = client
    body = json.dumps(_run_payload("run_ghost", "running", "run.started"), ensure_ascii=False).encode()
    resp = await ac.post("/api/v1/webhooks/runs", content=body, headers=_headers("run.started", "dlv_ghost", body))
    assert resp.status_code == 404
    assert resp.json()["error"] == "run_not_found"


async def test_heartbeat_webhook(client, session_factory):
    ac, _, _ = client
    project = await _make_project(session_factory)
    async with session_factory() as session:
        process = RunProcess(id=snowflake_id(), process_id="proc_hb1", project_id=project.id, crawler_id="proj_abc", workspace_id=project.workspace_id, run_type="cron", cron="*/30 * * * *", started_at=int(time.time() * 1000))
        session.add(process)
        await session.commit()

    payload = {
        "crawler_id": "proj_abc", "process_id": "proc_hb1",
        "project_id": str(project.id), "workspace_id": str(project.workspace_id),
        "mode": "run", "run_type": "cron", "cron": "*/30 * * * *",
        "status": "alive", "pid": 12345,
        "started_at": int(time.time() * 1000), "uptime_ms": 1000,
        "health": {"browser": True, "mongo": True, "llm": True, "disk_ok": True},
    }
    body = json.dumps(payload).encode()
    resp = await ac.post("/api/v1/webhooks/heartbeat", content=body, headers=_headers("heartbeat", "dlv_hb", body))
    assert resp.status_code == 200, resp.text
    assert resp.json()["accepted"] is True

    async with session_factory() as session:
        proc = await session.scalar(select(RunProcess).where(RunProcess.process_id == "proc_hb1"))
        assert proc.last_heartbeat_at is not None
        assert proc.status == "alive"


async def test_heartbeat_degraded(client, session_factory):
    ac, _, _ = client
    project = await _make_project(session_factory)
    async with session_factory() as session:
        session.add(RunProcess(id=snowflake_id(), process_id="proc_hb2", project_id=project.id, crawler_id="proj_abc", workspace_id=project.workspace_id, run_type="cron", started_at=int(time.time() * 1000)))
        await session.commit()

    payload = {
        "crawler_id": "proj_abc", "process_id": "proc_hb2",
        "status": "alive", "pid": 1, "started_at": int(time.time() * 1000),
        "health": {"browser": False, "mongo": True, "llm": True, "disk_ok": True},
    }
    body = json.dumps(payload).encode()
    resp = await ac.post("/api/v1/webhooks/heartbeat", content=body, headers=_headers("heartbeat", "dlv_hb2", body))
    assert resp.status_code == 200
    async with session_factory() as session:
        proc = await session.scalar(select(RunProcess).where(RunProcess.process_id == "proc_hb2"))
        assert proc.status == "degraded"