"""工作空间 / 成员 / 项目 Schema。"""

from __future__ import annotations

from pydantic import BaseModel, Field


class WorkspaceCreate(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    quota: dict | None = None


class WorkspaceUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=128)
    quota: dict | None = None
    status: str | None = None


class WorkspaceOut(BaseModel):
    id: int
    name: str
    owner_id: int
    status: str
    quota_json: dict | None
    created_at: int

    model_config = {"from_attributes": True}


class MemberInviteIn(BaseModel):
    username: str
    role: str = "developer"  # 角色名
    project_id: int | None = None


class MemberRoleIn(BaseModel):
    role: str


class MemberOut(BaseModel):
    user_id: int
    username: str
    role: str
    scope: str
    project_id: int | None

    model_config = {"from_attributes": True}


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    description: str | None = Field(default=None, max_length=512)
    source_type: str = "custom"  # builtin / custom
    builtin_crawler_id: str | None = None
    run_config: dict | None = None


class ProjectUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    run_config: dict | None = None
    status: str | None = None


class ProjectOut(BaseModel):
    id: int
    workspace_id: int
    name: str
    description: str | None
    source_type: str
    builtin_crawler_id: str | None
    crawler_id: str
    run_config_json: dict | None
    status: str
    created_at: int

    model_config = {"from_attributes": True}