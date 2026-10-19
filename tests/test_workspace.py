"""工作空间 / 成员 / 项目 / RBAC 集成测试。"""

from __future__ import annotations

import pytest


async def _make_ws(ac, headers):
    resp = await ac.post("/api/v1/workspaces", json={"name": "ws-1"}, headers=headers)
    assert resp.status_code == 200, resp.text
    return resp.json()


async def test_create_list_get_workspace(client, auth_headers):
    ac, _, _ = client
    ws = await _make_ws(ac, auth_headers)
    assert ws["owner_id"]

    listed = await ac.get("/api/v1/workspaces", headers=auth_headers)
    assert listed.status_code == 200
    assert any(w["id"] == ws["id"] for w in listed.json())

    got = await ac.get(f"/api/v1/workspaces/{ws['id']}", headers=auth_headers)
    assert got.status_code == 200
    assert got.json()["name"] == "ws-1"


async def test_update_workspace(client, auth_headers):
    ac, _, _ = client
    ws = await _make_ws(ac, auth_headers)
    resp = await ac.patch(
        f"/api/v1/workspaces/{ws['id']}", json={"name": "ws-renamed"}, headers=auth_headers
    )
    assert resp.status_code == 200
    assert resp.json()["name"] == "ws-renamed"


async def test_delete_workspace(client, auth_headers):
    ac, _, _ = client
    ws = await _make_ws(ac, auth_headers)
    resp = await ac.delete(f"/api/v1/workspaces/{ws['id']}", headers=auth_headers)
    assert resp.status_code == 200
    got = await ac.get(f"/api/v1/workspaces/{ws['id']}", headers=auth_headers)
    assert got.status_code == 404


async def test_workspace_members_and_rbac(client, auth_headers):
    ac, _, _ = client
    ws = await _make_ws(ac, auth_headers)

    # 邀请第二个用户为 viewer
    await ac.post(
        "/api/v1/auth/register",
        json={"username": "carol", "email": "carol@example.com", "password": "password123"},
    )
    invite = await ac.post(
        f"/api/v1/workspaces/{ws['id']}/members",
        json={"username": "carol", "role": "viewer"},
        headers=auth_headers,
    )
    assert invite.status_code == 200, invite.text

    # carol 登录并尝试创建项目 -> 403
    carol_login = await ac.post(
        "/api/v1/auth/login", json={"username": "carol", "password": "password123"}
    )
    carol_headers = {"Authorization": f"Bearer {carol_login.json()['access_token']}"}
    denied = await ac.post(
        f"/api/v1/workspaces/{ws['id']}/projects",
        json={"name": "p1", "source_type": "custom"},
        headers=carol_headers,
    )
    assert denied.status_code == 403

    # 成员列表可见
    members = await ac.get(f"/api/v1/workspaces/{ws['id']}/members", headers=auth_headers)
    assert members.status_code == 200
    usernames = {m["username"] for m in members.json()}
    assert "carol" in usernames


async def test_project_crud_and_crawler_id(client, auth_headers):
    ac, _, _ = client
    ws = await _make_ws(ac, auth_headers)

    created = await ac.post(
        f"/api/v1/workspaces/{ws['id']}/projects",
        json={"name": "my-crawler", "source_type": "custom"},
        headers=auth_headers,
    )
    assert created.status_code == 200, created.text
    proj = created.json()
    assert proj["crawler_id"].startswith("proj_")
    assert proj["source_type"] == "custom"

    listed = await ac.get(f"/api/v1/workspaces/{ws['id']}/projects", headers=auth_headers)
    assert listed.status_code == 200
    assert len(listed.json()) == 1

    patched = await ac.patch(
        f"/api/v1/projects/{proj['id']}",
        json={"name": "renamed", "run_config": {"cron": "*/5 * * * *"}},
        headers=auth_headers,
    )
    assert patched.status_code == 200
    assert patched.json()["run_config_json"]["cron"] == "*/5 * * * *"

    deleted = await ac.delete(f"/api/v1/projects/{proj['id']}", headers=auth_headers)
    assert deleted.status_code == 200
    got = await ac.get(f"/api/v1/projects/{proj['id']}", headers=auth_headers)
    assert got.status_code == 404


async def test_snowflake_ids_are_strings_for_js_clients(client, auth_headers):
    """64 位雪花 id 必须以字符串下发, 否则前端 JSON.parse 丢精度会请求到不存在的 id。"""
    ac, _, _ = client
    ws = await _make_ws(ac, auth_headers)
    proj = (
        await ac.post(
            f"/api/v1/workspaces/{ws['id']}/projects",
            json={"name": "custom", "source_type": "custom"},
            headers=auth_headers,
        )
    ).json()

    assert isinstance(ws["id"], str)
    assert isinstance(ws["owner_id"], str)
    assert isinstance(proj["id"], str)
    assert isinstance(proj["workspace_id"], str)

    # 用原样返回的 id 访问详情必须命中(模拟前端导航到 /projects/{id})
    got = await ac.get(f"/api/v1/projects/{proj['id']}", headers=auth_headers)
    assert got.status_code == 200, got.text
    assert got.json()["id"] == proj["id"]


async def test_builtin_project_requires_builtin_crawler(client, auth_headers):
    ac, _, _ = client
    ws = await _make_ws(ac, auth_headers)
    resp = await ac.post(
        f"/api/v1/workspaces/{ws['id']}/projects",
        json={"name": "builtin", "source_type": "builtin"},
        headers=auth_headers,
    )
    assert resp.status_code == 400


async def test_first_user_is_super_admin(client, registered_user):
    ac, session_factory, _ = client
    from sqlalchemy import select

    from backend.db.models import Role, RoleBinding

    async with session_factory() as session:
        binding = await session.scalar(select(RoleBinding))
        role = await session.get(Role, binding.role_id)
        assert role.name == "super_admin"