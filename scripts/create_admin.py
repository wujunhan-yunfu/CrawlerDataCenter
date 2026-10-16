"""创建后端超级管理员账号(默认 admin / 123456)。

用法:
    uv run python scripts/create_admin.py
    uv run python scripts/create_admin.py --username admin --password 123456 --email admin@cdc.local
    uv run python scripts/create_admin.py --on-exists reset   # 账号已存在时重置密码并置为 active
    uv run python scripts/create_admin.py --on-exists fail    # 账号已存在时直接报错

说明:
    - 连接串取自 DATABASE_URL(.env / 环境变量), 与后端运行时一致;
    - 会先幂等写入内置角色(含 super_admin), 再把账号绑定为 `global` scope 的 super_admin;
    - 需要先建表: `uv run alembic upgrade head`;
    - 默认口令 123456 不满足注册接口的 >=8 位策略, 仅供本地/初始化环境, 生产请尽快改密。
"""

from __future__ import annotations

import argparse
import asyncio
import sys

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.ids import snowflake_id
from backend.core.security import hash_password
from backend.db.models import User
from backend.rbac.service import bind_role, get_role_by_name, seed_roles

SUPER_ADMIN_ROLE = "super_admin"
ON_EXISTS_CHOICES = ("skip", "reset", "fail")


async def create_super_admin(
    session: AsyncSession,
    *,
    username: str,
    password: str,
    email: str,
    on_exists: str = "skip",
) -> str:
    """在给定会话中创建(或按 on_exists 修复)全局超级管理员。

    返回 'created' / 'reset' / 'skipped'; 冲突或前置缺失抛 ValueError。
    """
    if on_exists not in ON_EXISTS_CHOICES:
        raise ValueError(f"--on-exists 取值非法: {on_exists}")

    # 幂等写入内置角色(含 super_admin)
    await seed_roles(session)
    role = await get_role_by_name(session, SUPER_ADMIN_ROLE)
    if role is None:
        raise ValueError(f"内置角色 {SUPER_ADMIN_ROLE} 缺失, 请先执行 alembic upgrade head")

    user = await session.scalar(select(User).where(User.username == username))
    if user is None:
        email_owner = await session.scalar(select(User).where(User.email == email))
        if email_owner is not None:
            raise ValueError(f"邮箱 {email} 已被用户 {email_owner.username} 占用")
        user = User(
            id=snowflake_id(),
            username=username,
            email=email,
            password_hash=hash_password(password),
            status="active",
        )
        session.add(user)
        await session.commit()
        result = "created"
    elif on_exists == "fail":
        raise ValueError(f"用户 {username} 已存在 (id={user.id})")
    elif on_exists == "reset":
        user.password_hash = hash_password(password)
        user.status = "active"
        await session.commit()
        result = "reset"
    else:
        result = "skipped"

    # 确保全局(scope=global) super_admin 绑定; bind_role 幂等
    await bind_role(session, user.id, role.id)
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="创建 CDC 超级管理员账号(默认 admin / 123456)")
    parser.add_argument("--username", default="admin", help="用户名(默认: admin)")
    parser.add_argument("--password", default="123456", help="密码(默认: 123456)")
    parser.add_argument("--email", default="admin@cdc.local", help="邮箱(默认: admin@cdc.local)")
    parser.add_argument(
        "--on-exists",
        choices=ON_EXISTS_CHOICES,
        default="skip",
        help="用户名已存在时: skip 跳过(默认) / reset 重置密码 / fail 报错",
    )
    return parser


async def _run(args: argparse.Namespace) -> int:
    from backend.db.session import SessionLocal, engine

    try:
        async with SessionLocal() as session:
            result = await create_super_admin(
                session,
                username=args.username,
                password=args.password,
                email=args.email,
                on_exists=args.on_exists,
            )
    finally:
        await engine.dispose()

    labels = {"created": "已创建", "reset": "已存在, 已重置密码", "skipped": "已存在, 已跳过"}
    print(f"[ok] 超级管理员 '{args.username}' {labels[result]} (全局 {SUPER_ADMIN_ROLE})")
    if args.password == "123456":
        print("[warn] 当前使用默认弱口令 123456, 生产环境请尽快修改")
    return 0


def main() -> None:
    args = build_parser().parse_args()
    try:
        code = asyncio.run(_run(args))
    except ValueError as exc:
        print(f"[error] {exc}", file=sys.stderr)
        sys.exit(1)
    except Exception as exc:  # noqa: BLE001
        print(f"[error] 创建超级管理员失败: {exc}", file=sys.stderr)
        sys.exit(1)
    sys.exit(code)


if __name__ == "__main__":
    main()
