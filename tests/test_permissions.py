"""权限查询端点 /auth/permissions 测试。"""

from __future__ import annotations


async def _make_ws(ac, headers):
    resp = await ac.post("/api/v1/workspaces", json={"name": "ws-perm"}, headers=headers)
    assert resp.status_code == 200, resp.text
    return resp.json()


async def test_global_permissions_union(client, auth_headers):
    ac, _, _ = client
    resp = await ac.get("/api/v1/auth/permissions", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    perms = set(resp.json()["permissions"])
    # 首个注册用户为 super_admin, 应拥有全部权限点
    assert "workspace:create" in perms
    assert "audit:read" in perms
    assert "run:trigger" in perms
    assert resp.json()["workspace_id"] is None
    assert resp.json()["project_id"] is None


async def test_workspace_scoped_permissions(client, auth_headers):
    ac, _, _ = client
    ws = await _make_ws(ac, auth_headers)

    resp = await ac.get(
        f"/api/v1/auth/permissions?workspace_id={ws['id']}", headers=auth_headers
    )
    assert resp.status_code == 200, resp.text
    perms = set(resp.json()["permissions"])
    assert resp.json()["workspace_id"] == ws["id"]
    # workspace owner 拥有空间内全部权限
    assert "member:invite" in perms
    assert "project:create" in perms


async def test_viewer_permissions_restricted(client, auth_headers):
    ac, _, _ = client
    ws = await _make_ws(ac, auth_headers)

    await ac.post(
        "/api/v1/auth/register",
        json={"username": "viewer", "email": "viewer@example.com", "password": "password123"},
    )
    invite = await ac.post(
        f"/api/v1/workspaces/{ws['id']}/members",
        json={"username": "viewer", "role": "viewer"},
        headers=auth_headers,
    )
    assert invite.status_code == 200, invite.text

    viewer_login = await ac.post(
        "/api/v1/auth/login", json={"username": "viewer", "password": "password123"}
    )
    viewer_headers = {"Authorization": f"Bearer {viewer_login.json()['access_token']}"}

    resp = await ac.get(
        f"/api/v1/auth/permissions?workspace_id={ws['id']}", headers=viewer_headers
    )
    assert resp.status_code == 200, resp.text
    perms = set(resp.json()["permissions"])
    assert "project:read" in perms
    assert "run:read" in perms
    assert "project:create" not in perms
    assert "member:invite" not in perms
    assert "container:manage" not in perms


async def test_permissions_require_auth(client):
    ac, _, _ = client
    resp = await ac.get("/api/v1/auth/permissions")
    assert resp.status_code == 401