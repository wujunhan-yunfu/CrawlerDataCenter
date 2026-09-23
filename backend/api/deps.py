"""API 依赖: 当前用户、权限校验、分页。"""

from __future__ import annotations

import jwt as pyjwt
from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.security import decode_token
from ..db.models import User
from ..db.session import get_db
from ..rbac.service import has_permission
from ..redis.client import Redis, redis, TokenStore
from .errors import forbidden, unauthorized

_bearer = HTTPBearer(auto_error=False)


async def get_current_user(
    request: Request,
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: AsyncSession = Depends(get_db),
    rds: Redis = Depends(lambda: redis),
) -> User:
    if creds is None:
        raise unauthorized()
    try:
        payload = decode_token(creds.credentials, expected_type="access")
    except pyjwt.PyJWTError:
        raise unauthorized()

    jti = payload.get("jti")
    if jti and await TokenStore(rds.client).is_blacklisted(jti):
        raise unauthorized("令牌已失效")

    user = await db.get(User, int(payload["sub"]))
    if user is None or user.status != "active":
        raise unauthorized()
    request.state.user = user
    request.state.access_payload = payload
    return user


def require_permission(permission: str):
    """权限依赖工厂: require_permission("run:trigger")。"""

    async def _dep(
        request: Request,
        user: User = Depends(get_current_user),
        db: AsyncSession = Depends(get_db),
    ) -> User:
        ws_id = request.path_params.get("workspace_id")
        proj_id = request.path_params.get("project_id")
        grant = await has_permission(
            db,
            user.id,
            permission,
            workspace_id=ws_id,
            project_id=proj_id,
        )
        if not grant.granted:
            raise forbidden("forbidden")
        request.state.permission = permission
        return user

    return _dep


def get_client_ip(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else ""


def get_kube(request: Request):
    return request.app.state.kube


def get_dev_service(request: Request):
    return request.app.state.dev_container_service


def pagination_params(offset: int = 0, limit: int = 50):
    return {"offset": max(0, offset), "limit": min(200, max(1, limit))}