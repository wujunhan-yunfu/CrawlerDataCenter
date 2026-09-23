"""安全原语与 API 集成端点测试。"""

from __future__ import annotations

import json
import time

import pytest

from backend.core.security import (
    create_access_token,
    decode_token,
    encrypt_field,
    hash_password,
    verify_password,
)


def test_password_hash_roundtrip():
    h = hash_password("secret123")
    assert h != "secret123"
    assert verify_password("secret123", h)
    assert not verify_password("wrong", h)


def test_jwt_roundtrip():
    token = create_access_token("42", {"role": "dev"})
    payload = decode_token(token, expected_type="access")
    assert payload["sub"] == "42"
    assert payload["type"] == "access"


def test_jwt_wrong_type_rejected():
    from backend.core.security import create_refresh_token, decode_token
    import jwt as pyjwt

    refresh, _, _ = create_refresh_token("42")
    with pytest.raises(pyjwt.PyJWTError):
        decode_token(refresh, expected_type="access")


def test_field_encryption_roundtrip(monkeypatch):
    import backend.core.security as security_module
    from cryptography.fernet import Fernet

    real_key = Fernet.generate_key().decode()
    monkeypatch.setattr(
        security_module.settings, "field_encryption_key", f"base64:{real_key}"
    )
    cipher = encrypt_field("secret-value")
    assert cipher != "secret-value"
    assert decrypt_roundtrip(cipher) == "secret-value"


def decrypt_roundtrip(cipher: str) -> str:
    from backend.core.security import decrypt_field

    return decrypt_field(cipher) or ""


async def test_login_trigger_and_token(client, auth_headers):
    ac, _, _ = client
    ws = (await ac.post("/api/v1/workspaces", json={"name": "ws-live"}, headers=auth_headers)).json()
    proj = (
        await ac.post(
            f"/api/v1/workspaces/{ws['id']}/projects",
            json={"name": "live", "source_type": "custom"},
            headers=auth_headers,
        )
    ).json()
    resp = await ac.post(f"/api/v1/projects/{proj['id']}/login", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["run_id"]
    assert data["live_ws_url"]
    assert "token=" in data["live_ws_url"]


async def test_run_detail_endpoint(client, auth_headers, session_factory):
    from backend.core.ids import snowflake_id
    from backend.db.models import CrawlerProject, Run

    ac, _, _ = client
    ws = (await ac.post("/api/v1/workspaces", json={"name": "ws-det"}, headers=auth_headers)).json()
    proj = (
        await ac.post(
            f"/api/v1/workspaces/{ws['id']}/projects",
            json={"name": "d", "source_type": "custom"},
            headers=auth_headers,
        )
    ).json()
    async with session_factory() as session:
        session.add(
            Run(
                id=snowflake_id(), run_id="run_det_1", project_id=proj["id"],
                crawler_id=proj["crawler_id"], workspace_id=proj["workspace_id"],
                status="succeeded", started_at=int(time.time() * 1000),
                finished_at=int(time.time() * 1000), duration_ms=10,
            )
        )
        await session.commit()
    resp = await ac.get("/api/v1/runs/run_det_1", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "succeeded"
    assert resp.json()["saved"] == []


async def test_data_download_endpoint(client, auth_headers, session_factory):
    import hashlib
    import hmac
    import json

    from backend.core.ids import snowflake_id
    from backend.db.models import CrawlerProject, DataItem, Run

    ac, _, _ = client
    ws = (await ac.post("/api/v1/workspaces", json={"name": "ws-dl"}, headers=auth_headers)).json()
    proj = (
        await ac.post(
            f"/api/v1/workspaces/{ws['id']}/projects",
            json={"name": "dl", "source_type": "custom"},
            headers=auth_headers,
        )
    ).json()
    async with session_factory() as session:
        session.add(Run(id=snowflake_id(), run_id="run_dl_1", project_id=proj["id"], crawler_id=proj["crawler_id"], workspace_id=proj["workspace_id"], status="running", started_at=int(time.time() * 1000)))
        await session.flush()
        item = DataItem(
            id=snowflake_id(), run_id="run_dl_1", crawler_id=proj["crawler_id"],
            project_id=proj["id"], workspace_id=proj["workspace_id"],
            save_id="sav_dl", seq=1, fmt="json", name="a.json", size=10,
            encoding="utf-8", content='{"ok":true}', storage_backend="inline",
        )
        session.add(item)
        await session.commit()
        item_id = item.id

    listed = await ac.get(f"/api/v1/projects/{proj['id']}/data", headers=auth_headers)
    assert listed.status_code == 200
    assert len(listed.json()) == 1

    dl = await ac.get(f"/api/v1/data/{item_id}/download", headers=auth_headers)
    assert dl.status_code == 200
    assert dl.text == '{"ok":true}'


async def test_webhook_prepare_requires_storage(client):
    ac, _, _ = client
    body = json.dumps({"data": {"run_id": "run_x", "save_id": "sav_x", "size": 100}}).encode()
    resp = await ac.post("/api/v1/webhooks/data/prepare", content=body, headers={"Content-Type": "application/json"})
    assert resp.status_code in (501, 400)  # 未配置对象存储


async def test_audit_listing(client, auth_headers, session_factory):
    from backend.core.ids import snowflake_id
    from backend.db.models import AuditLog
    from sqlalchemy import select

    ac, _, _ = client
    ws = (await ac.post("/api/v1/workspaces", json={"name": "ws-aud"}, headers=auth_headers)).json()
    async with session_factory() as session:
        session.add(AuditLog(id=snowflake_id(), actor_id=1, action="workspace.create", workspace_id=ws["id"], created_at=int(time.time() * 1000)))
        await session.commit()
    resp = await ac.get(f"/api/v1/audit?workspace_id={ws['id']}", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()


async def test_healthz(client):
    ac, _, _ = client
    resp = await ac.get("/healthz")
    assert resp.status_code == 200
    assert "ok" in resp.json()
    assert resp.json()["redis"] is True  # fakeredis 可用