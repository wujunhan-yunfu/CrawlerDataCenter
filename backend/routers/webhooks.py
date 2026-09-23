"""ACS → CDC webhook 接收端点(签名+幂等, 见 docs/webhook-protocol.md)。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from ..api.deps import get_client_ip
from ..api.errors import bad_request
from ..config import settings
from ..db.session import get_db
from ..redis.client import RateLimiter, Redis, redis
from ..schemas.webhook import WebhookAck
from ..services.data_ingest import DataError, DataIngestService
from ..services.webhook_receiver import WebhookError, WebhookReceiver

router = APIRouter(prefix="/webhooks", tags=["webhooks"])

_HEADER_EVENT = "x-webhook-event"


async def _rate_limit(request: Request, rds: Redis) -> None:
    rl = RateLimiter(rds.client)
    allowed, _ = await rl.check(
        "webhook", request.client.host or "?", settings.rate_webhook_max, settings.rate_webhook_window
    )
    if not allowed:
        raise WebhookError(429, "rate_limited", "请求过于频繁")


async def _handle(
    request: Request,
    kind: str,
    db: AsyncSession,
    rds: Redis,
) -> JSONResponse:
    await _rate_limit(request, rds)
    body = await request.body()
    event = request.headers.get(_HEADER_EVENT, "")
    try:
        receiver = WebhookReceiver()
        accepted, ack = await receiver.handle(
            db, kind, event, dict(request.headers), body, get_client_ip(request)
        )
    except WebhookError as exc:
        payload = {"ok": False, "error": exc.code, "message": exc.message}
        if exc.code == "rate_limited":
            payload["retry_after_ms"] = 5000
        return JSONResponse(status_code=exc.status_code, content=payload)
    except DataError as exc:
        payload = {"ok": False, "error": exc.code, "message": exc.message, **exc.extra}
        return JSONResponse(status_code=exc.status_code, content=payload)
    return JSONResponse(status_code=200, content=ack)


@router.post("/runs", response_model=WebhookAck)
async def webhook_runs(request: Request, db: AsyncSession = Depends(get_db), rds: Redis = Depends(lambda: redis)):
    return await _handle(request, "run", db, rds)


@router.post("/heartbeat", response_model=WebhookAck)
async def webhook_heartbeat(request: Request, db: AsyncSession = Depends(get_db), rds: Redis = Depends(lambda: redis)):
    return await _handle(request, "heartbeat", db, rds)


@router.post("/data", response_model=WebhookAck)
async def webhook_data(request: Request, db: AsyncSession = Depends(get_db), rds: Redis = Depends(lambda: redis)):
    return await _handle(request, "data", db, rds)


@router.post("/data/prepare")
async def webhook_data_prepare(request: Request, db: AsyncSession = Depends(get_db), rds: Redis = Depends(lambda: redis)):
    await _rate_limit(request, rds)
    import json

    try:
        payload = json.loads(await request.body())
    except json.JSONDecodeError:
        raise bad_request("invalid_payload", "JSON 解析失败")
    try:
        result = await DataIngestService().prepare(db, payload)
    except DataError as exc:
        return JSONResponse(status_code=exc.status_code, content={"ok": False, "error": exc.code, **exc.extra})
    return result


@router.post("/data/commit")
async def webhook_data_commit(request: Request, db: AsyncSession = Depends(get_db), rds: Redis = Depends(lambda: redis)):
    await _rate_limit(request, rds)
    import json
    import uuid

    body = await request.body()
    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        raise bad_request("invalid_payload", "JSON 解析失败")
    from ..services.webhook_receiver import WebhookReceiver

    try:
        receiver = WebhookReceiver()
        accepted, ack = await receiver.handle(
            db, "data", "data.saved", dict(request.headers), body, get_client_ip(request)
        )
    except WebhookError as exc:
        return JSONResponse(status_code=exc.status_code, content={"ok": False, "error": exc.code, "message": exc.message})
    except DataError as exc:
        return JSONResponse(status_code=exc.status_code, content={"ok": False, "error": exc.code, "message": exc.message, **exc.extra})
    return ack