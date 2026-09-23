"""Webhook 接收服务: 签名校验、时间戳防重放、幂等、状态机、落库。

与 ACS backend/services/runmode/webhook.py 的签名协议严格对齐。
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..core.ids import snowflake_id
from ..db.models import Run, RunProcess, RunResult, WebhookDelivery, WebhookEvent

_MAX_TIMESTAMP_SKEW_MS = 5 * 60 * 1000

_ALLOWED_RUN_EVENTS = {"run.started", "run.succeeded", "run.failed", "run.skipped"}

# 运行状态机: 当前状态 -> 允许的下一事件状态
_STATE_MACHINE = {
    "pending": {"running"},
    "running": {"succeeded", "failed", "skipped"},
    "succeeded": set(),
    "failed": set(),
    "skipped": set(),
}


class WebhookError(Exception):
    def __init__(self, status_code: int, code: str, message: str = "") -> None:
        self.status_code = status_code
        self.code = code
        self.message = message
        super().__init__(code)


def _secret() -> str:
    return settings.webhook_secret or settings.jwt_secret


def verify_signature(timestamp: str, signature: str, body: bytes) -> bool:
    expected = hmac.new(
        _secret().encode("utf-8"),
        f"{timestamp}.".encode("utf-8") + body,
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(signature, f"sha256={expected}")


def verify_timestamp(timestamp: str) -> bool:
    try:
        ts = int(timestamp)
    except (TypeError, ValueError):
        return False
    return abs(int(time.time() * 1000) - ts) <= _MAX_TIMESTAMP_SKEW_MS


def _check_state_transition(current: str, next_status: str) -> bool:
    allowed = _STATE_MACHINE.get(current, set())
    return next_status in allowed or current == "pending" and next_status == "running"


async def _record_delivery(
    session: AsyncSession,
    delivery_id: str,
    kind: str,
    event: str,
    run_id: str | None,
    save_id: str | None,
    accepted: bool,
    source_ip: str | None,
    response: dict | None = None,
) -> None:
    session.add(
        WebhookDelivery(
            id=snowflake_id(),
            delivery_id=delivery_id,
            kind=kind,
            event=event,
            run_id=run_id,
            save_id=save_id,
            source_ip=source_ip,
            accepted=accepted,
            response_json=response,
        )
    )


async def _duplicate(session: AsyncSession, kind: str, event: str, delivery_id: str) -> bool:
    return (
        await session.scalar(
            select(WebhookDelivery.id).where(
                WebhookDelivery.kind == kind,
                WebhookDelivery.event == event,
                WebhookDelivery.delivery_id == delivery_id,
            )
        )
    ) is not None


async def _record_event(session: AsyncSession, delivery_id: str, event: str, payload: dict) -> None:
    session.add(
        WebhookEvent(
            id=snowflake_id(),
            delivery_id=delivery_id,
            event=event,
            payload_json=payload,
            received_at=int(time.time() * 1000),
        )
    )


class WebhookReceiver:
    """run / heartbeat / data 三类事件的统一接收入口。"""

    async def handle(
        self,
        session: AsyncSession,
        kind: str,
        event: str,
        headers: dict[str, str],
        body: bytes,
        source_ip: str | None = None,
    ) -> tuple[bool, dict | None]:
        """返回 (accepted, ack_body)。校验失败抛 WebhookError。"""
        delivery_id = headers.get("x-webhook-delivery") or uuid.uuid4().hex
        timestamp = headers.get("x-webhook-timestamp", "")
        signature = headers.get("x-webhook-signature", "")

        if not verify_timestamp(timestamp):
            raise WebhookError(401, "invalid_signature", "时间戳失效或过期")
        if not verify_signature(timestamp, signature, body):
            raise WebhookError(401, "invalid_signature", "签名校验失败")

        try:
            payload = json.loads(body.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            raise WebhookError(400, "invalid_payload", "JSON 解析失败")

        if await _duplicate(session, kind, event, delivery_id):
            return False, {"ok": True, "accepted": False, "reason": "duplicate"}

        await _record_event(session, delivery_id, event, payload)
        await _record_delivery(session, delivery_id, kind, event, None, None, False, source_ip)
        await session.commit()

        if kind == "run":
            ack = await self._handle_run(session, delivery_id, event, payload)
        elif kind == "heartbeat":
            ack = await self._handle_heartbeat(session, delivery_id, payload)
        elif kind == "data":
            ack = await self._handle_data(session, delivery_id, payload)
        else:
            raise WebhookError(400, "invalid_payload", f"未知 kind: {kind}")

        # 更新 delivery 为 accepted
        d = await session.scalar(
            select(WebhookDelivery).where(WebhookDelivery.delivery_id == delivery_id)
        )
        if d:
            d.accepted = True
        await session.commit()
        return True, ack

    async def _handle_run(
        self, session: AsyncSession, delivery_id: str, event: str, payload: dict
    ) -> dict:
        run_data = payload.get("run") or {}
        run_id = run_data.get("run_id") or payload.get("run_id")
        if not run_id:
            raise WebhookError(400, "invalid_payload", "缺少 run_id")

        run = await session.scalar(select(Run).where(Run.run_id == run_id))
        if run is None:
            raise WebhookError(404, "run_not_found", f"run_id 不存在: {run_id}")

        next_status = {
            "run.started": "running",
            "run.succeeded": "succeeded",
            "run.failed": "failed",
            "run.skipped": "skipped",
        }.get(event, "failed")
        if not _check_state_transition(run.status, next_status):
            raise WebhookError(409, "state_conflict", f"{run.status} -> {next_status} 非法")

        run.status = next_status
        run.mode = run_data.get("mode", run.mode)
        run.trigger = run_data.get("trigger", run.trigger)
        run.run_type = run_data.get("run_type", run.run_type)
        run.cron = run_data.get("cron", run.cron)
        run.process_id = run_data.get("process_id", run.process_id)
        run.finished_at = run_data.get("finished_at") or (None if run.finished_at else run.finished_at)
        run.duration_ms = run_data.get("duration_ms")
        run.next_run_at = run_data.get("next_run_at")
        if run_data.get("error"):
            run.error_json = run_data["error"]

        if event == "run.started":
            run.started_at = run_data.get("started_at") or run.started_at

        # 结束事件: 写 run_results
        if next_status in ("succeeded", "failed", "skipped"):
            existing = set(
                (await session.execute(select(RunResult.save_id).where(RunResult.run_id == run_id))).scalars().all()
            )
            for item in run_data.get("saved") or []:
                save_id = item.get("save_id")
                if save_id and save_id in existing:
                    continue
                session.add(
                    RunResult(
                        id=snowflake_id(),
                        run_id=run_id,
                        name=item.get("name", ""),
                        kind=item.get("kind", "content"),
                        size=item.get("size", 0),
                        save_id=save_id,
                        delivery=item.get("delivery", "local"),
                        remote_path=item.get("remote_path"),
                    )
                )
        await session.commit()
        return {"ok": True, "accepted": True, "run_id": run_id}

    async def _handle_heartbeat(self, session: AsyncSession, delivery_id: str, payload: dict) -> dict:
        process_id = payload.get("process_id")
        if not process_id:
            raise WebhookError(400, "invalid_payload", "缺少 process_id")

        process = await session.scalar(select(RunProcess).where(RunProcess.process_id == process_id))
        if process is None:
            # 心跳先于记录到达: 尝试按 crawler_id 匹配
            process = await session.scalar(
                select(RunProcess).where(RunProcess.crawler_id == payload.get("crawler_id", ""))
            )
        if process is None:
            raise WebhookError(404, "process_not_found", f"process_id 不存在: {process_id}")

        now = int(time.time() * 1000)
        hb_status = payload.get("status", "alive")
        process.status = {"alive": "alive", "running": "running", "degraded": "degraded", "stopping": "stopped"}.get(hb_status, hb_status)
        process.last_heartbeat_at = now
        process.uptime_ms = payload.get("uptime_ms")
        process.next_run_at = payload.get("next_run_at")
        process.pod_name = payload.get("pod_name") or process.pod_name
        process.pid = payload.get("pid") or process.pid
        process.health_json = payload.get("health") or {}
        process.last_run_json = payload.get("last_run") or {}
        health = payload.get("health") or {}
        if health and not all([health.get("browser", True), health.get("mongo", True), health.get("llm", True), health.get("disk_ok", True)]):
            process.status = "degraded"
            process.degraded_count += 1
        await session.commit()
        return {"ok": True, "accepted": True, "process_id": process_id}

    async def _handle_data(self, session: AsyncSession, delivery_id: str, payload: dict) -> dict:
        from .data_ingest import DataIngestService

        svc = DataIngestService()
        return await svc.ingest(session, delivery_id, payload)