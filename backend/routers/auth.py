"""认证路由: 注册 / 登录 / 刷新 / 登出。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from ..api.deps import get_client_ip, get_current_user
from ..api.errors import bad_request
from ..db.models import User
from ..db.session import get_db
from ..redis.client import Redis, redis
from ..rbac.service import effective_permissions
from ..schemas.auth import LoginIn, LogoutIn, PermissionsOut, RefreshIn, RegisterIn, TokenOut, UserOut
from ..services.auth import AuthError, login, logout, refresh, register

router = APIRouter(prefix="/auth", tags=["auth"])


def _handle_auth_error(exc: AuthError):
    if exc.args and exc.args[0] == "rate_limited":
        return bad_request("rate_limited", "请求过于频繁")
    if exc.args and exc.args[0] == "invalid_credentials":
        return bad_request("invalid_credentials", "用户名或密码错误")
    if exc.args and exc.args[0] == "username_or_email_taken":
        return bad_request("username_or_email_taken", "用户名或邮箱已存在")
    if exc.args and exc.args[0] == "user_disabled":
        return bad_request("user_disabled", "账号已被禁用")
    return bad_request("invalid_refresh_token", "刷新令牌无效")


@router.post("/register", response_model=TokenOut)
async def register_route(
    body: RegisterIn,
    request: Request,
    db: AsyncSession = Depends(get_db),
    rds: Redis = Depends(lambda: redis),
):
    try:
        return await register(db, rds, body.username, str(body.email), body.password, get_client_ip(request))
    except AuthError as exc:
        raise _handle_auth_error(exc)


@router.post("/login", response_model=TokenOut)
async def login_route(
    body: LoginIn,
    request: Request,
    db: AsyncSession = Depends(get_db),
    rds: Redis = Depends(lambda: redis),
):
    try:
        return await login(db, rds, body.username, body.password, get_client_ip(request))
    except AuthError as exc:
        raise _handle_auth_error(exc)


@router.post("/refresh", response_model=TokenOut)
async def refresh_route(
    body: RefreshIn,
    db: AsyncSession = Depends(get_db),
    rds: Redis = Depends(lambda: redis),
):
    try:
        return await refresh(db, rds, body.refresh_token)
    except AuthError as exc:
        raise _handle_auth_error(exc)


@router.post("/logout")
async def logout_route(
    body: LogoutIn,
    request: Request,
    db: AsyncSession = Depends(get_db),
    rds: Redis = Depends(lambda: redis),
    user: User = Depends(get_current_user),
):
    await logout(db, rds, request.state.access_payload, body.refresh_token)
    return {"ok": True}


@router.get("/me", response_model=UserOut)
async def me(user: User = Depends(get_current_user)):
    return user


@router.get("/permissions", response_model=PermissionsOut)
async def my_permissions(
    workspace_id: int | None = None,
    project_id: int | None = None,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """返回当前用户在指定 scope 下的有效权限。

    - 不带参数: 用户在全部 scope 下的权限并集(用于菜单/导航 gating)。
    - 带 workspace_id: 该工作空间内的有效权限(含全局 + 空间 + 空间内项目)。
    - 带 workspace_id + project_id: 该项目的有效权限。
    """
    perms = await effective_permissions(db, user.id, workspace_id, project_id)
    return PermissionsOut(
        permissions=sorted(perms),
        workspace_id=workspace_id,
        project_id=project_id,
    )