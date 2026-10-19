"""认证与用户 Schema。"""

from __future__ import annotations

from pydantic import BaseModel, EmailStr, Field

from .common import SnowflakeId


class RegisterIn(BaseModel):
    username: str = Field(min_length=3, max_length=64)
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)


class LoginIn(BaseModel):
    username: str = Field(min_length=1)
    password: str = Field(min_length=1)


class TokenOut(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int


class RefreshIn(BaseModel):
    refresh_token: str


class LogoutIn(BaseModel):
    refresh_token: str | None = None


class UserOut(BaseModel):
    id: SnowflakeId
    username: str
    email: str
    status: str
    created_at: int

    model_config = {"from_attributes": True}


class PermissionsOut(BaseModel):
    """当前用户在某 scope(workspace/project) 下的有效权限。

    不带 workspace/project 时返回用户在全部 scope 下的权限并集,
    用于前端菜单/导航等全局 gating。
    """

    permissions: list[str]
    workspace_id: SnowflakeId | None = None
    project_id: SnowflakeId | None = None