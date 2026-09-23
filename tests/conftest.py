"""测试夹具: aiosqlite 内存库 + fakeredis + ASGI 客户端。"""

from __future__ import annotations

import asyncio

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
    app.state.dev_container_service = __import__("backend.services.dev_container", fromlist=["DevContainerService"]).DevContainerService(kube, rds=rds)

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