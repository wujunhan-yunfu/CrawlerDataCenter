"""开发容器 / 运行 / 数据 / webhook / 审计 Schema。"""

from __future__ import annotations

from pydantic import BaseModel, Field

from .common import SnowflakeId


# ---- 开发容器 ----

class DevContainerOut(BaseModel):
    project_id: SnowflakeId
    crawler_id: str
    phase: str
    dev_url: str | None
    pod_name: str | None
    error_code: str | None
    last_active_at: int | None
    expires_at: int | None

    model_config = {"from_attributes": True}


class DevContainerTaskOut(BaseModel):
    """异步拉起任务状态: 前端循环轮询直到 success/failed/timeout。"""

    task_id: str | None = None
    project_id: SnowflakeId
    status: str          # pending / running / success / failed / timeout
    phase: str           # absent/pending/starting/ready/stopping/failed
    mode: str            # k8s / local
    dev_url: str | None = None
    pod_name: str | None = None
    error_code: str | None = None
    message: str | None = None
    started_at: int | None = None
    elapsed_ms: int | None = None


# ---- 运行 ----

class RunTrigger(BaseModel):
    trigger: str = "once"  # once / cron
    cron: str | None = None
    headless: bool = True
    webhook_secret: str | None = None


class RunOut(BaseModel):
    run_id: str
    project_id: SnowflakeId
    crawler_id: str
    workspace_id: SnowflakeId
    mode: str
    trigger: str
    cron: str | None
    status: str
    started_at: int
    finished_at: int | None = None
    duration_ms: int | None = None
    error_json: dict | None = None

    model_config = {"from_attributes": True}


class RunDetailOut(RunOut):
    saved: list[dict] = []
    process_id: str | None = None


class RunProcessOut(BaseModel):
    process_id: str
    project_id: SnowflakeId
    crawler_id: str
    workspace_id: SnowflakeId
    cron: str | None
    pod_name: str | None
    status: str
    pid: int | None
    started_at: int
    last_heartbeat_at: int | None
    next_run_at: int | None
    last_run_json: dict | None
    health_json: dict | None

    model_config = {"from_attributes": True}


# ---- login ----

class LoginTriggerOut(BaseModel):
    run_id: str
    status: str
    live_ws_url: str
    expires_at: int


# ---- webhook 接收 ----

class WebhookAck(BaseModel):
    ok: bool
    accepted: bool
    reason: str | None = None
    run_id: str | None = None
    save_id: str | None = None


class WebhookErrorOut(BaseModel):
    ok: bool = False
    error: str
    message: str | None = None
    retry_after_ms: int | None = None


# ---- 数据 ----

class DataItemOut(BaseModel):
    id: SnowflakeId
    run_id: str
    crawler_id: str
    project_id: SnowflakeId
    workspace_id: SnowflakeId
    save_id: str
    seq: int
    kind: str
    fmt: str
    name: str
    size: int
    content_hash: str | None
    storage_backend: str
    storage_path: str | None
    source_url: str | None
    collected_at: int | None

    model_config = {"from_attributes": True}


class DataDownloadOut(BaseModel):
    name: str
    content: str
    encoding: str
    content_type: str


# ---- 审计 ----

class AuditOut(BaseModel):
    id: SnowflakeId
    actor_id: SnowflakeId | None
    action: str
    target_type: str | None
    target_id: SnowflakeId | None
    workspace_id: SnowflakeId | None
    detail_json: dict | None
    ip: str | None
    created_at: int

    model_config = {"from_attributes": True}


# ---- 分页 ----

class Page(BaseModel):
    total: int
    offset: int
    limit: int
    items: list


class HealthOut(BaseModel):
    ok: bool
    db: bool
    redis: bool
    version: str = "0.1.0"