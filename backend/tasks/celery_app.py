"""Celery 应用实例。

启动 worker:
    uv run celery -A backend.tasks.celery_app:celery_app worker -l info

broker/result backend 缺省复用 `REDIS_URL`(分别可用 `CELERY_BROKER_URL` /
`CELERY_RESULT_BACKEND` 覆盖)。开发容器异步拉起任务见
`backend/tasks/dev_container_tasks.py`。
"""

from __future__ import annotations

from celery import Celery

from ..config import settings

celery_app = Celery(
    "cdc",
    broker=settings.celery_broker_url or settings.redis_url,
    backend=settings.celery_result_backend or settings.redis_url,
    include=["backend.tasks.dev_container_tasks"],
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    broker_connection_retry_on_startup=True,
    result_expires=3600,
)
