"""开发容器状态机测试(FakeKubeClient)。"""

from __future__ import annotations

import pytest


async def _setup_project(ac, headers):
    ws = (
        await ac.post("/api/v1/workspaces", json={"name": "ws-dev"}, headers=headers)
    ).json()
    proj = (
        await ac.post(
            f"/api/v1/workspaces/{ws['id']}/projects",
            json={"name": "dev", "source_type": "custom"},
            headers=headers,
        )
    ).json()
    return proj


async def test_ensure_and_poll_dev_container(client, auth_headers):
    ac, _, app = client
    proj = await _setup_project(ac, auth_headers)

    ensure = await ac.post(
        f"/api/v1/projects/{proj['id']}/dev-container", headers=auth_headers
    )
    assert ensure.status_code == 200, ensure.text
    assert ensure.json()["phase"] in ("starting", "pending")

    poll = await ac.get(f"/api/v1/projects/{proj['id']}/dev-container", headers=auth_headers)
    assert poll.status_code == 200
    assert poll.json()["phase"] == "ready"
    assert poll.json()["dev_url"] == f"/dev/{proj['workspace_id']}/{proj['id']}"
    assert app.state.kube.created  # FakeKubeClient 收到创建请求


async def test_recycle_dev_container(client, auth_headers):
    ac, _, app = client
    proj = await _setup_project(ac, auth_headers)
    await ac.post(f"/api/v1/projects/{proj['id']}/dev-container", headers=auth_headers)
    await ac.get(f"/api/v1/projects/{proj['id']}/dev-container", headers=auth_headers)

    resp = await ac.delete(f"/api/v1/projects/{proj['id']}/dev-container", headers=auth_headers)
    assert resp.status_code == 200
    assert any(name for name, kind in app.state.kube.deleted if kind == "pod")


async def test_builtin_project_rejects_dev_container(client, auth_headers):
    ac, _, _ = client
    ws = (
        await ac.post("/api/v1/workspaces", json={"name": "ws-b"}, headers=auth_headers)
    ).json()
    proj = (
        await ac.post(
            f"/api/v1/workspaces/{ws['id']}/projects",
            json={"name": "b", "source_type": "builtin", "builtin_crawler_id": "b1"},
            headers=auth_headers,
        )
    ).json()
    resp = await ac.post(f"/api/v1/projects/{proj['id']}/dev-container", headers=auth_headers)
    assert resp.status_code == 400


async def test_dev_container_quota(client, auth_headers, monkeypatch):
    import backend.config as cfg_module

    ac, _, _ = client
    monkeypatch.setattr(cfg_module.settings, "workspace_container_quota", 0)
    proj = await _setup_project(ac, auth_headers)
    resp = await ac.post(f"/api/v1/projects/{proj['id']}/dev-container", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["phase"] == "failed"
    assert resp.json()["error_code"] == "QUOTA_EXCEEDED"


async def test_illegal_phase_transition(client, auth_headers, session_factory):
    """直接调用服务层验证非法迁移被拒绝。"""
    from backend.db.models import CrawlerProject, DevContainer
    from backend.k8s.client import FakeKubeClient
    from backend.services.dev_container import DevContainerService
    from backend.core.ids import snowflake_id

    async with session_factory() as session:
        project = CrawlerProject(
            id=snowflake_id(), workspace_id=snowflake_id(), name="p", crawler_id="proj_x"
        )
        session.add(project)
        await session.commit()
        row = DevContainer(id=snowflake_id(), project_id=project.id, workspace_id=project.workspace_id, crawler_id="proj_x")
        session.add(row)
        await session.commit()
        svc = DevContainerService(FakeKubeClient())
        with pytest.raises(ValueError):
            svc._transition(row, "ready")  # absent -> ready 非法