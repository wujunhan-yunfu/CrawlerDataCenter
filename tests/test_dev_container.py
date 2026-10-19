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
    body = ensure.json()
    assert body["status"] == "pending"
    assert body["phase"] == "pending"
    assert body["task_id"]
    assert body["mode"] == "k8s"

    task = await ac.get(
        f"/api/v1/projects/{proj['id']}/dev-container/tasks/{body['task_id']}",
        headers=auth_headers,
    )
    assert task.status_code == 200
    assert task.json()["status"] == "success"

    poll = await ac.get(f"/api/v1/projects/{proj['id']}/dev-container", headers=auth_headers)
    assert poll.status_code == 200
    assert poll.json()["phase"] == "ready"
    assert poll.json()["dev_url"] == f"/dev/{proj['workspace_id']}/{proj['id']}"
    assert app.state.kube.created  # FakeKubeClient 收到创建请求


async def test_dev_mode_skips_k8s_but_keeps_same_dev_url(client, auth_headers, monkeypatch):
    """开发模式: Celery 任务内部跳过 Pod 拉起, dev_url/代理方式与 Pod 模式一致。"""
    from backend.config import settings

    ac, _, app = client
    monkeypatch.setattr(settings, "dev_container_mode", "local")
    monkeypatch.setattr(settings, "acs_local_url", "http://localhost:8000")
    proj = await _setup_project(ac, auth_headers)

    resp = await ac.post(
        f"/api/v1/projects/{proj['id']}/dev-container", headers=auth_headers
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["mode"] == "local"
    assert body["status"] == "pending"
    assert body["task_id"]

    task = await ac.get(
        f"/api/v1/projects/{proj['id']}/dev-container/tasks/{body['task_id']}",
        headers=auth_headers,
    )
    assert task.status_code == 200
    assert task.json()["status"] == "success"
    assert task.json()["mode"] == "local"

    poll = await ac.get(f"/api/v1/projects/{proj['id']}/dev-container", headers=auth_headers)
    assert poll.json()["phase"] == "ready"
    # 与 Pod 模式完全相同的对外访问地址
    assert poll.json()["dev_url"] == f"/dev/{proj['workspace_id']}/{proj['id']}"
    assert not app.state.kube.created  # 未触发任何 K8s 创建


async def test_local_upstream_points_to_local_acs(client, auth_headers, monkeypatch):
    """代理上游: 开发模式指向本地 ACS, 集群模式指向 K8s Service。"""
    from backend.config import settings
    from backend.db.models import CrawlerProject
    from backend.k8s.client import FakeKubeClient
    from backend.services.dev_container import DevContainerService
    from backend.core.ids import snowflake_id

    proj = CrawlerProject(
        id=snowflake_id(), workspace_id=snowflake_id(), name="p", crawler_id="proj_up"
    )
    monkeypatch.setattr(settings, "dev_container_mode", "local")
    monkeypatch.setattr(settings, "acs_local_url", "http://localhost:8000")
    assert DevContainerService.upstream_url(proj) == "http://localhost:8000"

    monkeypatch.setattr(settings, "dev_container_mode", "k8s")
    from backend.k8s.templates import service_name_for

    svc = DevContainerService(FakeKubeClient())
    assert svc.upstream_url(proj) == (
        f"http://{service_name_for(proj.crawler_id)}.{settings.k8s_namespace}.svc.cluster.local:8080"
    )


async def test_poll_normalizes_legacy_local_dev_url(client, auth_headers, monkeypatch):
    """历史数据里遗留的直连地址(http://localhost:8000)应被纠正为代理路径。"""
    from backend.config import settings
    from backend.core.ids import snowflake_id
    from backend.db.models import CrawlerProject, DevContainer

    ac, session_factory, _ = client
    monkeypatch.setattr(settings, "dev_container_mode", "local")
    proj = await _setup_project(ac, auth_headers)

    async with session_factory() as session:
        session.add(
            DevContainer(
                id=snowflake_id(),
                project_id=int(proj["id"]),
                workspace_id=int(proj["workspace_id"]),
                crawler_id=proj["crawler_id"],
                phase="ready",
                dev_url="http://localhost:8000",
            )
        )
        await session.commit()

    poll = await ac.get(f"/api/v1/projects/{proj['id']}/dev-container", headers=auth_headers)
    assert poll.json()["dev_url"] == f"/dev/{proj['workspace_id']}/{proj['id']}"

    # 再次 POST(已 ready)也应返回代理路径
    resp = await ac.post(f"/api/v1/projects/{proj['id']}/dev-container", headers=auth_headers)
    assert resp.json()["dev_url"] == f"/dev/{proj['workspace_id']}/{proj['id']}"


async def test_dev_proxy_forwards_to_local_upstream(client, auth_headers, monkeypatch):
    """点击 /dev/{ws}/{pid} 时经 CDC 反向代理转到 ACS 上游; token 不转发。"""
    import backend.routers.dev_proxy as dev_proxy
    from backend.config import settings
    from httpx import ASGITransport, AsyncClient

    ac, _, app = client
    monkeypatch.setattr(settings, "dev_container_mode", "local")
    monkeypatch.setattr(settings, "acs_local_url", "http://127.0.0.1:8000")
    proj = await _setup_project(ac, auth_headers)
    token = auth_headers["Authorization"].split()[1]

    # 本地模式: 任务立即置 ready
    await ac.post(f"/api/v1/projects/{proj['id']}/dev-container", headers=auth_headers)

    class FakeResponse:
        status_code = 200
        headers = {"content-type": "text/plain"}

        async def aiter_raw(self):
            yield b"acs-ok"

        async def aclose(self):
            pass

    calls: list = []

    class FakeClient:
        def build_request(self, method, url, headers=None, content=None):
            calls.append((method, url, headers))
            return object()

        async def send(self, req, stream=True):
            return FakeResponse()

        async def aclose(self):
            pass

    monkeypatch.setattr(dev_proxy, "_new_client", lambda: FakeClient())

    # 无 token / 无 cookie -> 401(使用独立客户端, 避免 Cookie 影响)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as anon:
        denied = await anon.get(f"/dev/{proj['workspace_id']}/{proj['id']}/")
    assert denied.status_code == 401

    # 首访带 ?token=, 代理目标 path 与访问地址一致, 并种下鉴权 Cookie
    resp = await ac.get(
        f"/dev/{proj['workspace_id']}/{proj['id']}/", params={"token": token}
    )
    assert resp.status_code == 200
    assert resp.text == "acs-ok"
    assert dev_proxy.DEV_PROXY_COOKIE in resp.cookies
    method, url, fwd_headers = calls[-1]
    assert method == "GET"
    assert url == f"http://127.0.0.1:8000/dev/{proj['workspace_id']}/{proj['id']}/"
    assert "token" not in url  # 令牌不转发给上游
    assert "authorization" not in {k.lower() for k in fwd_headers}
    assert fwd_headers.get("X-Forwarded-Prefix") == f"/dev/{proj['workspace_id']}/{proj['id']}"

    # js/css 等子资源不带 query token, 依靠 Cookie 通过鉴权
    asset = await ac.get(
        f"/dev/{proj['workspace_id']}/{proj['id']}/assets/index-t3d0368i.js"
    )
    assert asset.status_code == 200, asset.text
    assert calls[-1][1] == (
        f"http://127.0.0.1:8000/dev/{proj['workspace_id']}/{proj['id']}/assets/index-t3d0368i.js"
    )

    # 子路径保留查询串
    nested = await ac.get(
        f"/dev/{proj['workspace_id']}/{proj['id']}/assets/app.js",
        params={"token": token, "v": "2"},
    )
    assert nested.status_code == 200
    assert calls[-1][1] == (
        f"http://127.0.0.1:8000/dev/{proj['workspace_id']}/{proj['id']}/assets/app.js?v=2"
    )

    # API 面(/api/v1/..., 含 /api/v1/ws)去掉访问前缀, 转发到上游原生路径
    api = await ac.get(
        f"/dev/{proj['workspace_id']}/{proj['id']}/api/v1/data",
        params={"token": token, "x": "1"},
    )
    assert api.status_code == 200
    assert calls[-1][1] == "http://127.0.0.1:8000/api/v1/data?x=1"


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
    task_id = resp.json()["task_id"]
    task = await ac.get(
        f"/api/v1/projects/{proj['id']}/dev-container/tasks/{task_id}", headers=auth_headers
    )
    assert task.status_code == 200
    body = task.json()
    assert body["status"] == "failed"
    assert body["error_code"] == "QUOTA_EXCEEDED"


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


async def test_launch_times_out(client, auth_headers, session_factory, monkeypatch):
    """Celery 任务执行体: 启动后轮询超时置 failed/START_TIMEOUT。"""
    from backend.db.models import CrawlerProject, DevContainer
    from backend.k8s.client import FakeKubeClient, PodStatus
    from backend.services.dev_container import DevContainerService
    from backend.core.ids import snowflake_id

    class NeverReadyKube(FakeKubeClient):
        async def get_pod_status(self, name: str, namespace: str) -> PodStatus:
            return PodStatus(name=name, phase="Pending", ready=False)

    async with session_factory() as session:
        project = CrawlerProject(
            id=snowflake_id(), workspace_id=snowflake_id(), name="p", crawler_id="proj_timeout"
        )
        session.add(project)
        await session.commit()
        svc = DevContainerService(NeverReadyKube())
        row = await svc.launch(session, project, timeout=0, interval=0)
        assert row.phase == "failed"
        assert row.error_code == "START_TIMEOUT"


def test_ws_upstream_url_build():
    """WebSocket 代理目标: API 面去掉访问前缀, http->ws / https->wss。"""
    from backend.routers.dev_proxy import _proxy_path, _ws_upstream_url

    prefix = "/dev/1/2"
    ws_path = _proxy_path(f"{prefix}/api/v1/ws/network", prefix)
    assert ws_path == "/api/v1/ws/network"
    assert _ws_upstream_url("http://localhost:8000", ws_path, [("a", "b")]) == (
        "ws://localhost:8000/api/v1/ws/network?a=b"
    )
    assert _ws_upstream_url("https://svc.cdc:8080/", "/api/v1/ws", []) == (
        "wss://svc.cdc:8080/api/v1/ws"
    )
    # 静态资源仍保留前缀
    assert _proxy_path(f"{prefix}/assets/app.js", prefix) == f"{prefix}/assets/app.js"


def test_resolve_status_timeout():
    from backend.db.models import DevContainer
    from backend.services.dev_container_task import DevContainerTaskState, resolve_status
    from backend.core.ids import snowflake_id

    old = int(__import__("time").time() * 1000) - 10 * 60 * 1000
    row = DevContainer(
        id=snowflake_id(), project_id=1, workspace_id=1, crawler_id="p", phase="starting"
    )
    row.created_at = old
    task = DevContainerTaskState("t", "STARTED", None, 1, old)
    status, code, elapsed = resolve_status(row, task)
    assert status == "timeout"
    assert code == "START_TIMEOUT"
    assert elapsed and elapsed > 0