"""数据库创建脚本工具函数测试。"""

from __future__ import annotations

import pytest
from sqlalchemy import select

from backend.core.security import verify_password
from backend.db.models import RoleBinding, User
from backend.rbac.service import effective_permissions
from scripts.create_admin import create_super_admin
from scripts.create_db import parse_database_url


def test_parse_database_url_standard():
    cfg = parse_database_url(
        "postgresql+asyncpg://yunfu:vG8bD5wH6yU4uU5c@yftool-db-pgvector:5432/cdc"
    )
    assert cfg["user"] == "yunfu"
    assert cfg["password"] == "vG8bD5wH6yU4uU5c"
    assert cfg["host"] == "yftool-db-pgvector"
    assert cfg["port"] == 5432
    assert cfg["dbname"] == "cdc"


def test_parse_database_url_plain_postgres():
    cfg = parse_database_url("postgresql://u:p@localhost:5433/mydb")
    assert cfg["host"] == "localhost"
    assert cfg["port"] == 5433
    assert cfg["dbname"] == "mydb"


def test_parse_database_url_default_port_and_user():
    cfg = parse_database_url("postgresql+asyncpg://admin@db-host/db")
    assert cfg["user"] == "admin"
    assert cfg["port"] == 5432
    assert cfg["password"] == ""
    assert cfg["dbname"] == "db"


def test_parse_database_url_urlencoded():
    cfg = parse_database_url(
        "postgresql+asyncpg://user:p%40ss@host:5432/db"
    )
    assert cfg["password"] == "p@ss"


def test_parse_database_url_missing_db():
    with pytest.raises(ValueError):
        parse_database_url("postgresql+asyncpg://u:p@host:5432/")


async def test_create_super_admin_creates_user_with_global_role(session_factory):
    async with session_factory() as session:
        result = await create_super_admin(
            session, username="admin", password="123456", email="admin@cdc.local"
        )
    assert result == "created"

    async with session_factory() as session:
        user = await session.scalar(select(User).where(User.username == "admin"))
        assert user is not None
        assert user.status == "active"
        assert verify_password("123456", user.password_hash)

        bindings = (
            await session.execute(select(RoleBinding).where(RoleBinding.user_id == user.id))
        ).scalars().all()
        assert len(bindings) == 1
        assert bindings[0].workspace_id is None
        assert bindings[0].project_id is None

        perms = await effective_permissions(session, user.id)
        assert {"audit:read", "workspace:create", "data:read"} <= perms


async def test_create_super_admin_is_idempotent(session_factory):
    async with session_factory() as session:
        assert await create_super_admin(
            session, username="admin", password="123456", email="admin@cdc.local"
        ) == "created"
    async with session_factory() as session:
        assert await create_super_admin(
            session, username="admin", password="other-pass", email="admin@cdc.local"
        ) == "skipped"

    async with session_factory() as session:
        user = await session.scalar(select(User).where(User.username == "admin"))
        # 默认 skip 不覆盖密码
        assert verify_password("123456", user.password_hash)
        bindings = (
            await session.execute(select(RoleBinding).where(RoleBinding.user_id == user.id))
        ).scalars().all()
        assert len(bindings) == 1


async def test_create_super_admin_reset_password(session_factory):
    async with session_factory() as session:
        await create_super_admin(
            session, username="admin", password="123456", email="admin@cdc.local"
        )
    async with session_factory() as session:
        assert await create_super_admin(
            session, username="admin", password="new-secret-123", email="admin@cdc.local",
            on_exists="reset",
        ) == "reset"

    async with session_factory() as session:
        user = await session.scalar(select(User).where(User.username == "admin"))
        assert verify_password("new-secret-123", user.password_hash)
        assert not verify_password("123456", user.password_hash)


async def test_create_super_admin_fail_on_exists(session_factory):
    async with session_factory() as session:
        await create_super_admin(
            session, username="admin", password="123456", email="admin@cdc.local"
        )
    async with session_factory() as session:
        with pytest.raises(ValueError):
            await create_super_admin(
                session, username="admin", password="123456", email="admin@cdc.local",
                on_exists="fail",
            )


async def test_create_super_admin_email_conflict(session_factory):
    async with session_factory() as session:
        await create_super_admin(
            session, username="admin", password="123456", email="admin@cdc.local"
        )
    async with session_factory() as session:
        with pytest.raises(ValueError):
            await create_super_admin(
                session, username="admin2", password="123456", email="admin@cdc.local"
            )


async def test_create_super_admin_invalid_on_exists(session_factory):
    async with session_factory() as session:
        with pytest.raises(ValueError):
            await create_super_admin(
                session, username="admin", password="123456", email="admin@cdc.local",
                on_exists="bogus",
            )
