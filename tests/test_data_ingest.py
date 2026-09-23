"""data.saved 数据入库测试。"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time

from backend.config import settings
from backend.core.ids import snowflake_id
from backend.db.models import CrawlerProject, DataItem, Run
from backend.services.data_ingest import DataIngestService
from sqlalchemy import select


def _secret():
    return settings.webhook_secret or settings.jwt_secret


def _headers(body: bytes, delivery: str):
    ts = str(int(time.time() * 1000))
    digest = hmac.new(_secret().encode(), f"{ts}.".encode() + body, hashlib.sha256).hexdigest()
    return {
        "X-Webhook-Event": "data.saved",
        "X-Webhook-Delivery": delivery,
        "X-Webhook-Timestamp": ts,
        "X-Webhook-Signature": f"sha256={digest}",
        "Content-Type": "application/json",
    }


async def _make_run(session_factory) -> Run:
    async with session_factory() as session:
        project = CrawlerProject(id=snowflake_id(), workspace_id=snowflake_id(), name="p", crawler_id="proj_data")
        session.add(project)
        await session.flush()
        run = Run(id=snowflake_id(), run_id="run_data_1", project_id=project.id, crawler_id="proj_data", workspace_id=project.workspace_id, status="running", started_at=int(time.time() * 1000))
        session.add(run)
        await session.commit()
        return run


def _data_payload(run_id: str, save_id: str = "sav_xyz", content: str = '{"title":"hello"}', seq: int = 1):
    return {
        "event": "data.saved",
        "delivery_id": "dlv_data",
        "timestamp": int(time.time() * 1000),
        "data": {
            "crawler_id": "proj_data",
            "project_id": "1",
            "workspace_id": "1",
            "run_id": run_id,
            "save_id": save_id,
            "seq": seq,
            "kind": "content",
            "fmt": "json",
            "name": "a.json",
            "size": len(content),
            "content_hash": f"sha256:{hashlib.sha256(content.encode()).hexdigest()}",
            "content_type": "application/json",
            "encoding": "utf-8",
            "content": content,
            "storage": {"mode": "inline"},
            "source_url": "https://example.com",
            "collected_at": int(time.time() * 1000),
        },
    }


async def test_data_ingest_inline(client, session_factory):
    ac, _, _ = client
    await _make_run(session_factory)
    body = json.dumps(_data_payload("run_data_1")).encode()
    resp = await ac.post("/api/v1/webhooks/data", content=body, headers=_headers(body, "dlv_data_1"))
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["accepted"] is True
    assert data["stored"] is True

    async with session_factory() as session:
        item = await session.scalar(select(DataItem).where(DataItem.save_id == "sav_xyz"))
        assert item.seq == 1
        assert item.storage_backend in ("mongo", "inline")
        payload = await DataIngestService().get_content_payload(item)
        assert payload is not None
        content, _ = payload
        assert content == '{"title":"hello"}'


async def test_data_ingest_duplicate(client, session_factory):
    ac, _, _ = client
    await _make_run(session_factory)
    body = json.dumps(_data_payload("run_data_1")).encode()
    headers = _headers(body, "dlv_data_2")
    r1 = await ac.post("/api/v1/webhooks/data", content=body, headers=headers)
    assert r1.json()["accepted"] is True
    r2 = await ac.post("/api/v1/webhooks/data", content=body, headers=headers)
    assert r2.status_code == 200
    assert r2.json()["accepted"] is False
    assert r2.json()["reason"] == "duplicate"

    async with session_factory() as session:
        count = len((await session.execute(select(DataItem))).scalars().all())
    assert count == 1


async def test_data_ingest_base64(client, session_factory):
    ac, _, _ = client
    run = await _make_run(session_factory)
    png = base64.b64encode(b"\x89PNG fake image").decode()
    payload = _data_payload("run_data_1", save_id="sav_img", content=png, seq=2)
    payload["data"]["fmt"] = "img"
    payload["data"]["encoding"] = "base64"
    body = json.dumps(payload).encode()
    resp = await ac.post("/api/v1/webhooks/data", content=body, headers=_headers(body, "dlv_img"))
    assert resp.status_code == 200, resp.text
    async with session_factory() as session:
        item = await session.scalar(select(DataItem).where(DataItem.save_id == "sav_img"))
        assert item.encoding == "base64"
        assert item.fmt == "img"
        payload_content = await DataIngestService().get_content_payload(item)
        assert payload_content is not None
        assert payload_content[0] == png


async def test_data_ingest_too_large(client, session_factory, monkeypatch):
    import backend.config as cfg_module

    ac, _, _ = client
    await _make_run(session_factory)
    monkeypatch.setattr(cfg_module.settings, "data_max_single_bytes", 16)
    body = json.dumps(_data_payload("run_data_1", save_id="sav_big", content="x" * 100)).encode()
    resp = await ac.post("/api/v1/webhooks/data", content=body, headers=_headers(body, "dlv_big"))
    assert resp.status_code == 413
    assert resp.json()["error"] == "payload_too_large"


async def test_data_ingest_run_not_found(client):
    ac, _, _ = client
    body = json.dumps(_data_payload("run_ghost")).encode()
    resp = await ac.post("/api/v1/webhooks/data", content=body, headers=_headers(body, "dlv_ghost"))
    assert resp.status_code == 404
    assert resp.json()["error"] == "run_not_found"


async def test_data_query_and_download(client, session_factory):
    ac, _, _ = client
    run = await _make_run(session_factory)
    body = json.dumps(_data_payload("run_data_1")).encode()
    await ac.post("/api/v1/webhooks/data", content=body, headers=_headers(body, "dlv_dl"))
    assert run.project_id
    # 数据查询接口需要鉴权(此处仅验证服务层)
    async with session_factory() as session:
        from backend.services.data_ingest import DataIngestService

        items, total = await DataIngestService().query(session, run.project_id)
        assert total == 1
        assert items[0].name == "a.json"