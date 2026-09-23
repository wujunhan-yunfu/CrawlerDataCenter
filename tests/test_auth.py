"""认证流程测试。"""

from __future__ import annotations

import pytest


async def test_register_and_login(client):
    ac, _, _ = client
    resp = await ac.post(
        "/api/v1/auth/register",
        json={"username": "bob", "email": "bob@example.com", "password": "password123"},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["access_token"]
    assert data["refresh_token"]
    assert data["token_type"] == "bearer"

    login = await ac.post(
        "/api/v1/auth/login",
        json={"username": "bob", "password": "password123"},
    )
    assert login.status_code == 200, login.text
    assert login.json()["access_token"]


async def test_login_wrong_password(client, registered_user):
    ac, _, _ = client
    resp = await ac.post(
        "/api/v1/auth/login",
        json={"username": "alice", "password": "wrong-password"},
    )
    assert resp.status_code == 400
    assert resp.json()["error"] == "invalid_credentials"


async def test_register_duplicate(client, registered_user):
    ac, _, _ = client
    resp = await ac.post(
        "/api/v1/auth/register",
        json={"username": "alice", "email": "alice@example.com", "password": "password123"},
    )
    assert resp.status_code == 400
    assert resp.json()["error"] == "username_or_email_taken"


async def test_refresh_and_logout(client, registered_user):
    ac, _, _ = client
    refresh = registered_user["refresh_token"]
    resp = await ac.post("/api/v1/auth/refresh", json={"refresh_token": refresh})
    assert resp.status_code == 200, resp.text
    new_access = resp.json()["access_token"]

    # 旧 refresh 已撤销
    resp = await ac.post("/api/v1/auth/refresh", json={"refresh_token": refresh})
    assert resp.status_code == 400
    assert resp.json()["error"] == "invalid_refresh_token"

    # 登出后 access 令牌黑名单生效
    logout = await ac.post(
        "/api/v1/auth/logout",
        json={"refresh_token": new_access},
        headers={"Authorization": f"Bearer {new_access}"},
    )
    assert logout.status_code == 200
    me = await ac.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {new_access}"})
    assert me.status_code == 401


async def test_me(client, auth_headers):
    ac, _, _ = client
    resp = await ac.get("/api/v1/auth/me", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["username"] == "alice"


async def test_rate_limit(client):
    ac, _, _ = client
    for _ in range(11):
        await ac.post(
            "/api/v1/auth/login", json={"username": "nobody", "password": "x" * 8}
        )
    resp = await ac.post(
        "/api/v1/auth/login", json={"username": "nobody", "password": "x" * 8}
    )
    assert resp.status_code == 400
    assert resp.json()["error"] == "rate_limited"