"""测试夹具: aiosqlite 内存库 + fakeredis + ASGI 客户端。"""

from __future__ import annotations

import asyncio
import time
import uuid

import fakeredis.aioredis
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from backend.db.base import Base
from backend.db.session import get_db
from backend.k8s.client import FakeKubeClient
from backend.redis.client import redis as redis_singleton
from backend.rbac.service import seed_roles


@pytest.fixture(autouse=True)
def _force_k8s_dev_container(monkeypatch):
    """测试默认走 K8s 路径(开发模式判定与 environment=dev 解耦)。"""
    from backend.config import settings

    monkeypatch.setattr(settings, "dev_container_mode", "k8s")


class InlineDevContainerTaskService:
    """测试用同步任务服务: 投递即执行完整个拉起流程。"""

    def __init__(self, session_factory, dev_svc, timeout: int = 5) -> None:
        self._session_factory = session_factory
        self._dev = dev_svc
        self._timeout = timeout
        self._tasks: dict[str, int] = {}

    async def enqueue(self, project_id: int) -> tuple[str, int]:
        from backend.db.models import CrawlerProject

        task_id = f"inline-{project_id}-{uuid.uuid4().hex[:8]}"
        async with self._session_factory() as session:
            project = await session.get(CrawlerProject, project_id)
            await self._dev.launch(session, project, timeout=self._timeout, interval=0)
        self._tasks[task_id] = project_id
        return task_id, int(time.time() * 1000)

    async def get_task(self, task_id: str):
        from backend.db.models import CrawlerProject
        from backend.services.dev_container_task import DevContainerTaskState

        project_id = self._tasks.get(task_id)
        if project_id is None:
            return DevContainerTaskState(task_id, "PENDING", None, None, None)
        async with self._session_factory() as session:
            project = await session.get(CrawlerProject, project_id)
            row = await self._dev.get(session, project)
        status = "success" if row is not None and row.phase == "ready" else "failed"
        info = {
            "status": status,
            "phase": row.phase if row else "absent",
            "error_code": row.error_code if row else None,
        }
        return DevContainerTaskState(
            task_id, "SUCCESS", info, project_id, int(time.time() * 1000)
        )


@pytest_asyncio.fixture
async def engine():
    from sqlalchemy.pool import StaticPool

    eng = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        echo=False,
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield eng
    await eng.dispose()


@pytest_asyncio.fixture
async def session_factory(engine):
    return async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


@pytest_asyncio.fixture
async def rds():
    fake = fakeredis.aioredis.FakeRedis(decode_responses=True)
    redis_singleton.set_client(fake)
    yield redis_singleton
    await fake.flushall()


@pytest_asyncio.fixture
async def kube():
    return FakeKubeClient()


@pytest_asyncio.fixture
async def client(session_factory, rds, kube):
    """返回 (AsyncClient, session_factory)。首用户注册后 seed 角色。"""
    from backend.main import create_app

    # 预置内置角色
    async with session_factory() as session:
        await seed_roles(session)

    app = create_app(kube=kube, create_tables=False)
    dev_svc = __import__("backend.services.dev_container", fromlist=["DevContainerService"]).DevContainerService(kube, rds=rds)
    app.state.dev_container_service = dev_svc
    app.state.dev_task_service = InlineDevContainerTaskService(session_factory, dev_svc)

    async def override_get_db():
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac, session_factory, app
    app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def registered_user(client):
    ac, _, _ = client
    resp = await ac.post(
        "/api/v1/auth/register",
        json={"username": "alice", "email": "alice@example.com", "password": "password123"},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


@pytest_asyncio.fixture
async def auth_headers(registered_user):
    return {
        "Authorization": f"Bearer {registered_user['access_token']}",
        "Content-Type": "application/json",
    }


def run(coro):
    return asyncio.run(coro)