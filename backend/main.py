"""CDC 应用工厂: FastAPI app, 路由挂载, 生命周期, 异常处理。"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .api.errors import BizError, biz_error_handler, validation_error_handler
from .config import settings
from .db.base import Base
from .db.session import SessionLocal, engine
from .k8s.client import FakeKubeClient, KubeClient, RealKubeClient
from .redis.client import redis
from .routers import (
    audit,
    auth,
    data,
    dev_container,
    health,
    login_live,
    projects,
    runs,
    webhooks,
    workspaces,
)
from .services.dev_container import DevContainerService


def create_app(*, kube: KubeClient | None = None, create_tables: bool = False) -> FastAPI:
    """创建 CDC 应用。

    - kube: 注入 KubeClient(测试传 FakeKubeClient; 缺省自动探测 Real/Fake)。
    - create_tables: 直接建表(本地/测试用; 生产走 alembic migrate)。
    """

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if create_tables:
            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
            async with SessionLocal() as session:
                from .rbac.service import seed_roles

                await seed_roles(session)
        yield
        await redis.close()

    app = FastAPI(
        title=settings.app_name,
        version="0.1.0",
        lifespan=lifespan,
        docs_url="/docs" if settings.environment != "prod" else None,
        redoc_url=None,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # 基础设施实例挂载到 app.state
    if kube is not None:
        app.state.kube = kube
    else:
        try:
            app.state.kube = RealKubeClient(settings.k8s_namespace)
        except Exception:  # noqa: BLE001
            app.state.kube = FakeKubeClient()
    app.state.dev_container_service = DevContainerService(app.state.kube, rds=redis)

    # 异常处理
    app.add_exception_handler(BizError, biz_error_handler)
    from fastapi import HTTPException
    from fastapi.exceptions import RequestValidationError
    from fastapi.responses import JSONResponse

    async def http_exc_handler(_, exc: HTTPException):
        if isinstance(exc.detail, dict):
            return JSONResponse(status_code=exc.status_code, content=exc.detail)
        return JSONResponse(
            status_code=exc.status_code,
            content={"ok": False, "error": "error", "message": str(exc.detail)},
        )

    app.add_exception_handler(HTTPException, http_exc_handler)
    app.add_exception_handler(RequestValidationError, validation_error_handler)

    # 路由
    prefix = settings.api_prefix
    app.include_router(auth.router, prefix=prefix)
    app.include_router(workspaces.router, prefix=prefix)
    app.include_router(projects.router, prefix=prefix)
    app.include_router(dev_container.router, prefix=prefix)
    app.include_router(login_live.router, prefix=prefix)
    app.include_router(runs.router, prefix=prefix)
    app.include_router(webhooks.router, prefix=prefix)
    app.include_router(data.router, prefix=prefix)
    app.include_router(audit.router, prefix=prefix)
    app.include_router(health.router, prefix="")  # /healthz 不走 /api/v1

    return app


app = create_app()