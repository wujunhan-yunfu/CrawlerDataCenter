"""数据库创建脚本: 根据 DATABASE_URL 创建目标数据库, 存在时可选重建。

用法:
    uv run python scripts/create_db.py                 # 不存在则创建, 存在则跳过
    uv run python scripts/create_db.py --recreate      # 存在则先 DROP 再 CREATE
    uv run python scripts/create_db.py --url postgresql+asyncpg://u:p@host:5432/db
    uv run python scripts/create_db.py --maintenance-db postgres   # 连接的维护库

- 通过维护库(默认 postgres)执行 CREATE/DROP DATABASE;
- --recreate 会先 pg_terminate_backend 终止目标库的活跃连接再删除;
- 脚本不建表, 建表请执行 `uv run alembic upgrade head`。
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from urllib.parse import unquote, urlparse

import asyncpg


def parse_database_url(url: str) -> dict:
    """解析 SQLAlchemy 异步连接串, 返回连接参数与目标库名。"""
    if url.startswith("postgresql+asyncpg://"):
        url = url[len("postgresql+asyncpg://"):]
    elif url.startswith("postgresql://"):
        url = url[len("postgresql://"):]
    else:
        raise ValueError(f"不支持的连接串: {url}")

    parsed = urlparse(f"//{url}")
    user = unquote(parsed.username or "postgres")
    password = unquote(parsed.password or "")
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or 5432
    dbname = parsed.path.lstrip("/") or ""
    if not dbname:
        raise ValueError("连接串缺少数据库名, 如 ...:5432/cdc")
    return {"user": user, "password": password, "host": host, "port": port, "dbname": dbname}


async def ensure_database(cfg: dict, maintenance_db: str, recreate: bool) -> None:
    conn = await asyncpg.connect(
        host=cfg["host"], port=cfg["port"], user=cfg["user"],
        password=cfg["password"], database=maintenance_db, timeout=10,
    )
    dbname = cfg["dbname"]
    try:
        exists = await conn.fetchval(
            "SELECT 1 FROM pg_database WHERE datname = $1", dbname
        )
        if exists and not recreate:
            print(f"[skip] 数据库 '{dbname}' 已存在, 跳过(如需重建加 --recreate)")
            return

        if exists:
            # 终止目标库活跃连接, 否则 DROP 会失败
            await conn.execute(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                "WHERE datname = $1 AND pid <> pg_backend_pid()",
                dbname,
            )
            await conn.execute(f'DROP DATABASE "{dbname}"')
            print(f"[ok] 已删除旧库 '{dbname}'")

        await conn.execute(f'CREATE DATABASE "{dbname}"')
        print(f"[ok] 数据库 '{dbname}' 创建成功 (host={cfg['host']}:{cfg['port']})")
        print(f"[hint] 建表: uv run alembic upgrade head")
    finally:
        await conn.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="创建/重建 CDC 数据库")
    parser.add_argument("--url", default="", help="连接串(缺省取 backend.config settings.database_url)")
    parser.add_argument("--maintenance-db", default="postgres", help="维护库名(默认 postgres)")
    parser.add_argument("--recreate", action="store_true", help="存在时先删除再创建")
    args = parser.parse_args()

    url = args.url
    if not url:
        try:
            from backend.config import settings

            url = settings.database_url
        except Exception as exc:  # noqa: BLE001
            print(f"读取配置失败: {exc}, 请用 --url 显式指定", file=sys.stderr)
            sys.exit(1)

    try:
        cfg = parse_database_url(url)
    except ValueError as exc:
        print(f"解析连接串失败: {exc}", file=sys.stderr)
        sys.exit(1)

    try:
        asyncio.run(ensure_database(cfg, args.maintenance_db, args.recreate))
    except Exception as exc:  # noqa: BLE001
        print(f"创建数据库失败: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()