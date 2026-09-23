"""认证服务: 注册 / 登录 / 刷新 / 登出。"""

from __future__ import annotations

import jwt as pyjwt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..core.ids import snowflake_id
from ..core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    verify_password,
)
from ..db.models import RefreshToken, User
from ..redis.client import RateLimiter, Redis, TokenStore
from ..schemas.auth import TokenOut


class AuthError(Exception):
    pass


def _tokens(user_id: int) -> tuple[str, str, str, int]:
    access = create_access_token(str(user_id))
    refresh, jti, exp = create_refresh_token(str(user_id))
    return access, refresh, jti, exp


async def _issue_tokens(session: AsyncSession, store: TokenStore, user_id: int, ip: str) -> TokenOut:
    access, refresh, jti, exp = _tokens(user_id)
    await store.save_refresh(user_id, jti, settings.refresh_token_ttl)
    session.add(
        RefreshToken(
            id=snowflake_id(),
            user_id=user_id,
            jti=jti,
            expires_at=exp * 1000,
            created_ip=ip,
        )
    )
    await session.commit()
    return TokenOut(
        access_token=access,
        refresh_token=refresh,
        expires_in=settings.access_token_ttl,
    )


async def register(
    session: AsyncSession,
    rds: Redis,
    username: str,
    email: str,
    password: str,
    ip: str,
) -> TokenOut:
    rl = RateLimiter(rds.client)
    allowed, _ = await rl.check("auth", f"register:{ip}", settings.rate_login_max, settings.rate_login_window)
    if not allowed:
        raise AuthError("rate_limited")

    exists = await session.scalar(select(User).where((User.username == username) | (User.email == email)))
    if exists:
        raise AuthError("username_or_email_taken")

    user = User(
        id=snowflake_id(),
        username=username,
        email=email,
        password_hash=hash_password(password),
        status="active",
    )
    session.add(user)
    await session.commit()

    # 首个用户自动授予 super_admin(global)
    count = await session.scalar(select(User.id).limit(2))
    if count and await session.scalar(select(User.id).where(User.id != user.id)) is None:
        from ..rbac.service import bind_role, get_role_by_name

        super_role = await get_role_by_name(session, "super_admin")
        if super_role:
            await bind_role(session, user.id, super_role.id)
    return await _issue_tokens(session, TokenStore(rds.client), user.id, ip)


async def login(
    session: AsyncSession,
    rds: Redis,
    username: str,
    password: str,
    ip: str,
) -> TokenOut:
    rl = RateLimiter(rds.client)
    allowed, _ = await rl.check("auth", f"login:{ip}", settings.rate_login_max, settings.rate_login_window)
    if not allowed:
        raise AuthError("rate_limited")

    user = await session.scalar(select(User).where(User.username == username))
    if user is None or not verify_password(password, user.password_hash):
        raise AuthError("invalid_credentials")
    if user.status != "active":
        raise AuthError("user_disabled")

    user.last_login_at = __import__("time").time_ns() // 1_000_000
    await session.commit()
    return await _issue_tokens(session, TokenStore(rds.client), user.id, ip)


async def refresh(
    session: AsyncSession,
    rds: Redis,
    refresh_token: str,
) -> TokenOut:
    try:
        payload = decode_token(refresh_token, expected_type="refresh")
    except pyjwt.PyJWTError:
        raise AuthError("invalid_refresh_token")

    user_id = int(payload["sub"])
    jti = payload["jti"]
    store = TokenStore(rds.client)
    if not await store.refresh_valid(user_id, jti):
        raise AuthError("invalid_refresh_token")

    await store.revoke_refresh(user_id, jti)
    await session.execute(
        RefreshToken.__table__.update()
        .where(RefreshToken.jti == jti)
        .values(revoked_at=__import__("time").time_ns() // 1_000_000)
    )
    await session.commit()
    return await _issue_tokens(session, store, user_id, "")


async def logout(
    session: AsyncSession,
    rds: Redis,
    access_payload: dict,
    refresh_token: str | None,
) -> None:
    store = TokenStore(rds.client)
    await store.blacklist_access(access_payload["jti"], settings.access_token_ttl)
    if refresh_token:
        try:
            payload = decode_token(refresh_token, expected_type="refresh")
            await store.revoke_refresh(int(payload["sub"]), payload["jti"])
            await session.execute(
                RefreshToken.__table__.update()
                .where(RefreshToken.jti == payload["jti"])
                .values(revoked_at=__import__("time").time_ns() // 1_000_000)
            )
        except pyjwt.PyJWTError:
            pass
    await session.commit()