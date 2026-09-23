"""CDC 配置层: 基于 pydantic-settings, 支持 .env 与环境变量覆盖。"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    # ---- 基础 ----
    app_name: str = "CrawlerDataCenter"
    api_prefix: str = "/api/v1"
    environment: str = "dev"
    debug: bool = True

    # ---- 数据库 ----
    database_url: str = "postgresql+asyncpg://yunfu:vG8bD5wH6yU4uU5c@yftool-db-pgvector:5432/cdc"
    db_echo: bool = False
    db_pool_size: int = 10
    db_max_overflow: int = 20

    # ---- MongoDB(爬虫数据存储) ----
    mongo_host: str = "yftool-db-mongo.default"
    mongo_port: int = 27017
    mongo_username: str = ""
    mongo_password: str = ""
    mongo_database: str = "cdc"

    # ---- Redis ----
    redis_url: str = "redis://yftool-db-redis.default:6379/0"
    redis_prefix: str = "cdc"

    # ---- 认证 ----
    jwt_secret: str = "dev-secret-change-me"
    jwt_algorithm: str = "HS256"
    access_token_ttl: int = 3600           # 秒
    refresh_token_ttl: int = 7 * 86400     # 秒
    token_issuer: str = "cdc"

    # ---- 限流 ----
    rate_login_max: int = 10               # 登录/注册每分钟次数
    rate_login_window: int = 60
    rate_webhook_max: int = 600            # webhook 每分钟次数(按来源 IP)
    rate_webhook_window: int = 60

    # ---- 开发容器 ----
    acs_image: str = "agentcrawlerstudio:latest"
    k8s_namespace: str = "cdc"
    dev_container_idle_ttl: int = 1800     # 空闲回收 TTL(秒)
    dev_container_timeout: int = 120       # pending/starting 总超时(秒)
    workspace_container_quota: int = 3     # 每空间并发 dev 容器上限

    # ---- 调度 / 心跳 ----
    heartbeat_interval: int = 30           # ACS 心跳间隔(秒), 判定阈值 = max(3x, 90)
    heartbeat_unreachable_ms: int = 90000  # 失联阈值(毫秒)
    heartbeat_monitor_every: int = 10      # 巡检周期(秒)
    scheduler_slot_ms: int = 200           # 调度主循环 sleep
    run_webhook_base: str = ""             # 出站 webhook 基址(发送 ACS 生成的 run 事件, 预留)

    # ---- 数据 ----
    data_inline_max_bytes: int = 1024 * 1024
    data_max_single_bytes: int = 8 * 1024 * 1024  # 单条 data.saved 内联上限
    object_store_impl: Literal["none", "s3", "minio"] = "none"
    object_store_base_url: str = ""
    object_store_bucket: str = "cdc-data"

    # ---- 密钥 ----
    webhook_secret: str = ""               # 入站 webhook 校验密钥(缺省用 jwt_secret)
    field_encryption_key: str = ""         # 敏感字段加密密钥(32字节 base64), 空则不加密


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()