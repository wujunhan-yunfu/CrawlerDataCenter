"""数据库创建脚本工具函数测试。"""

from __future__ import annotations

import pytest

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