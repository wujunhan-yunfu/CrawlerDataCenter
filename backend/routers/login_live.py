"""login 实时画面: 触发 login 运行 + 只读 WebSocket 代理(短时效令牌鉴权)。"""

from __future__ import annotations

import time
import uuid

from fastapi import APIRouter, Depends, Query, Request, WebSocket, WebSocketDisconnect
from sqlalchemy.ext.asyncio import AsyncSession

from ..api.deps import get_current_user, get_dev_service, get_kube
from ..api.errors import not_found
from ..db.models import CrawlerProject, User
from ..db.session import get_db
from ..rbac.service import has_permission
from ..redis.client import LiveTokenStore, Redis, redis
from ..schemas.webhook import LoginTriggerOut
from ..services.project import ProjectService
from ..services.run import RunService

router = APIRouter(tags=["login"])

_LIVE_TTL = 600


async def _project_for(db: AsyncSession, project_id: int, user: User) -> CrawlerProject:
    project = await ProjectService.get(db, project_id)
    if project is None:
        raise not_found("project_not_found", "项目不存在")
    grant = await has_permission(db, user.id, "run:trigger", workspace_id=project.workspace_id, project_id=project.id)
    if not grant.granted:
        from ..api.errors import forbidden

        raise forbidden("forbidden")
    return project


@router.post("/projects/{project_id}/login", response_model=LoginTriggerOut)
async def trigger_login(
    project_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
    rds: Redis = Depends(lambda: redis),
):
    project = await _project_for(db, project_id, user)
    run_service = RunService(request.app.state.kube)
    run = await run_service.login_trigger(db, project)

    token = uuid.uuid4().hex
    await LiveTokenStore(rds.client).issue(
        token, {"user_id": user.id, "project_id": project.id, "run_id": run.run_id}, _LIVE_TTL
    )
    expires_at = int(time.time() * 1000) + _LIVE_TTL * 1000
    live_ws_url = f"{request.url.scheme}://{request.url.netloc}{request.url.path}/live?token={token}"
    return LoginTriggerOut(
        run_id=run.run_id,
        status=run.status,
        live_ws_url=live_ws_url,
        expires_at=expires_at,
    )


@router.websocket("/projects/{project_id}/login/live")
async def login_live_ws(
    websocket: WebSocket,
    project_id: int,
    token: str = Query(...),
):
    """只读实时画面代理(只转发帧流, 不注入任何输入)。"""
    await websocket.accept()
    rds = redis
    store = LiveTokenStore(rds.client)
    info = await store.verify(token)
    if info is None or int(info.get("project_id", -1)) != project_id:
        await websocket.close(code=4401)
        return

    dev = websocket.app.state.dev_container_service
    kube = websocket.app.state.kube
    # 生产: 经 KubeClient.proxy_ws 转发到 Pod 的 /api/v1/stream
    # FakeKubeClient 场景: 返回代理目标信息, 由前端直连或由代理层桥接
    try:
        proxy = await kube.proxy_ws(
            pod_name=f"acs-login-{project_id}",
            namespace="cdc",
            path="/api/v1/stream",
            port=8080,
        )
        await websocket.send_json({"type": "proxy", "target": proxy})
        # 帧流由真实代理层转发; 此处维持连接直至客户端断开
        while True:
            data = await websocket.receive()
            if data.get("type") == "websocket.disconnect":
                break
    except WebSocketDisconnect:
        pass
    finally:
        await store.revoke(token)
        try:
            await websocket.close()
        except Exception:  # noqa: BLE001
            pass