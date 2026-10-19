"""开发容器反向代理: /dev/{workspace_id}/{project_id}[/...] → ACS 上游。

- 对外路径/前缀与容器内部实现无关: 无论 Pod 还是本地 ACS, 都用同一 dev_url。
- **透传原始访问路径**: 代理目标 = 上游 + 与访问地址相同的完整 path
  (含 `/dev/{ws}/{pid}` 前缀, 即 ACS 的 `--web-prefix`), 这样 ACS 页面内
  绝对/相对资源路径都无需改写。
- 上游由 `DevContainerService.upstream_url` 决定:
  - 集群模式 → K8s Service(acs-dev-*.cdc.svc.cluster.local:8080)
  - 开发模式 → 本地 ACS(ACS_LOCAL_URL, 默认 http://localhost:8000)
- 鉴权: 浏览器新标签无法带 Authorization 头, 支持 `?token=<access_token>`
  (也兼容标准 Bearer 头)。token 不转发给上游。
"""

from __future__ import annotations

import asyncio
import logging
from urllib.parse import urlencode

import httpx
import websockets
from fastapi import APIRouter, Depends, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from ..api.deps import DEV_PROXY_COOKIE, get_current_user_via_token
from ..api.errors import forbidden, not_found, service_unavailable
from ..config import settings
from ..db.models import CrawlerProject, DevContainer, User
from ..db.session import get_db
from ..rbac.service import has_permission
from ..redis.client import Redis, redis
from ..services.dev_container import DevContainerService
from ..services.project import ProjectService

log = logging.getLogger("cdc.dev_proxy")

router = APIRouter(tags=["dev-container-proxy"])

_METHODS = ["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"]
# 逐跳/长度相关头由代理层重新计算, 不直接透传
_SKIP_REQ_HEADERS = {"host", "connection", "content-length", "accept-encoding", "authorization"}
_SKIP_RESP_HEADERS = {
    "connection",
    "content-length",
    "content-encoding",
    "transfer-encoding",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailers",
    "upgrade",
}


def _new_client() -> httpx.AsyncClient:
    """代理用 HTTP 客户端(测试可 monkeypatch 替换)。"""
    return httpx.AsyncClient(timeout=None, follow_redirects=False)


def _proxy_path(path: str, prefix: str) -> str:
    """计算转发给上游的 path。

    - ACS 的 API 面(`/api/v1/...`, 含 `/api/v1/ws/...`)挂载在原生路径下,
      因此带前缀访问时去掉 `/dev/{ws}/{pid}`, 转发到上游 `/api/v1/...`;
    - 其余(页面/静态资源)保留与访问地址相同的前缀(ACS `--web-prefix`)。
    """
    api_at = f"{prefix}/api/v1"
    if path == api_at or path.startswith(f"{api_at}/"):
        return path[len(prefix):]
    return path


async def _resolve_ready_container(
    request: Request, db: AsyncSession, workspace_id: int, project_id: int, user: User
) -> tuple[CrawlerProject, DevContainerService, DevContainer]:
    project = await ProjectService.get(db, project_id)
    if project is None or project.workspace_id != workspace_id:
        raise not_found("project_not_found", "项目不存在")
    grant = await has_permission(
        db, user.id, "container:manage", workspace_id=project.workspace_id, project_id=project.id
    )
    if not grant.granted:
        raise forbidden("forbidden")

    dev: DevContainerService = request.app.state.dev_container_service
    row = await dev.get(db, project)
    if row.phase != "ready":
        raise service_unavailable("container_not_ready", "开发容器未就绪")
    await dev.touch(db, project)
    return project, dev, row


async def _proxy(
    request: Request,
    db: AsyncSession,
    workspace_id: int,
    project_id: int,
    prefix: str,
) -> StreamingResponse:
    rds: Redis = redis
    user = await get_current_user_via_token(request, db, rds)
    project, dev, row = await _resolve_ready_container(
        request, db, workspace_id, project_id, user
    )

    # 代理目标 = 上游 + path(API 面去掉访问前缀, 其余保留)
    upstream = dev.upstream_url(project, row).rstrip("/")
    target = f"{upstream}{_proxy_path(request.url.path, prefix)}"
    query = [(k, v) for k, v in request.query_params.multi_items() if k != "token"]
    if query:
        target = f"{target}?{urlencode(query)}"

    headers = {
        k: v for k, v in request.headers.items() if k.lower() not in _SKIP_REQ_HEADERS
    }
    headers["X-Forwarded-For"] = request.client.host if request.client else ""
    headers["X-Forwarded-Proto"] = request.url.scheme
    headers["X-Forwarded-Prefix"] = prefix
    body = await request.body()

    client = _new_client()
    try:
        upstream_req = client.build_request(request.method, target, headers=headers, content=body)
        upstream_resp = await client.send(upstream_req, stream=True)
    except httpx.HTTPError as exc:
        await client.aclose()
        log.warning("开发容器代理失败: %s -> %s: %s", request.url.path, target, exc)
        raise service_unavailable("upstream_unreachable", f"上游不可达: {exc}")

    resp_headers = {
        k: v for k, v in upstream_resp.headers.items() if k.lower() not in _SKIP_RESP_HEADERS
    }

    async def _stream():
        try:
            async for chunk in upstream_resp.aiter_raw():
                yield chunk
        finally:
            await upstream_resp.aclose()
            await client.aclose()

    response = StreamingResponse(
        _stream(),
        status_code=upstream_resp.status_code,
        headers=resp_headers,
    )
    # 首次带 ?token= 访问时种 Cookie, 后续 js/css 等子资源据此鉴权
    query_token = request.query_params.get("token")
    if query_token:
        response.set_cookie(
            DEV_PROXY_COOKIE,
            query_token,
            max_age=settings.access_token_ttl,
            path=prefix,
            httponly=True,
            samesite="lax",
            secure=request.url.scheme == "https",
        )
    return response


@router.api_route("/dev/{workspace_id}/{project_id}", methods=_METHODS, include_in_schema=False)
async def dev_proxy_root(
    workspace_id: int,
    project_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    # 访问地址与代理目标路径一致, 不做重定向
    return await _proxy(request, db, workspace_id, project_id, f"/dev/{workspace_id}/{project_id}")


@router.api_route(
    "/dev/{workspace_id}/{project_id}/{subpath:path}", methods=_METHODS, include_in_schema=False
)
async def dev_proxy(
    workspace_id: int,
    project_id: int,
    request: Request,
    subpath: str = "",
    db: AsyncSession = Depends(get_db),
):
    return await _proxy(
        request, db, workspace_id, project_id, f"/dev/{workspace_id}/{project_id}"
    )


# ---- WebSocket 代理(如 /dev/{ws}/{pid}/api/v1/ws/network) ----

def _ws_upstream_url(upstream: str, path: str, query: list[tuple[str, str]]) -> str:
    base = upstream.rstrip("/")
    if base.startswith("https://"):
        base = "wss://" + base[len("https://"):]
    elif base.startswith("http://"):
        base = "ws://" + base[len("http://"):]
    url = f"{base}{path}"
    if query:
        url = f"{url}?{urlencode(query)}"
    return url


async def _proxy_ws(
    websocket: WebSocket, db: AsyncSession, workspace_id: int, project_id: int
) -> None:
    rds: Redis = redis
    user = await get_current_user_via_token(websocket, db, rds)
    project, dev, row = await _resolve_ready_container(
        websocket, db, workspace_id, project_id, user
    )

    upstream = dev.upstream_url(project, row)
    query = [(k, v) for k, v in websocket.query_params.multi_items() if k != "token"]
    prefix = f"/dev/{workspace_id}/{project_id}"
    target = _ws_upstream_url(upstream, _proxy_path(websocket.url.path, prefix), query)

    # 仅转发少量握手头; 其余由 websockets 客户端自行生成, 避免重复的 Upgrade 头
    extra_headers: dict[str, str] = {}
    if websocket.headers.get("origin"):
        extra_headers["Origin"] = websocket.headers["origin"]
    extra_headers["X-Forwarded-For"] = (
        websocket.client.host if websocket.client else ""
    )
    extra_headers["X-Forwarded-Prefix"] = f"/dev/{workspace_id}/{project_id}"
    subprotocols = [
        p.strip()
        for p in (websocket.headers.get("sec-websocket-protocol") or "").split(",")
        if p.strip()
    ]

    await websocket.accept(subprotocol=subprotocols[0] if subprotocols else None)
    try:
        async with websockets.connect(
            target, additional_headers=extra_headers, subprotocols=subprotocols or None
        ) as upstream_ws:

            async def client_to_upstream() -> None:
                try:
                    while True:
                        message = await websocket.receive()
                        if message.get("type") == "websocket.disconnect":
                            break
                        if message.get("text") is not None:
                            await upstream_ws.send(message["text"])
                        elif message.get("bytes") is not None:
                            await upstream_ws.send(message["bytes"])
                except WebSocketDisconnect:
                    pass

            async def upstream_to_client() -> None:
                async for message in upstream_ws:
                    if isinstance(message, bytes):
                        await websocket.send_bytes(message)
                    else:
                        await websocket.send_text(message)

            tasks = [
                asyncio.create_task(client_to_upstream()),
                asyncio.create_task(upstream_to_client()),
            ]
            done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            for task in pending:
                task.cancel()
            for task in done:
                if not task.cancelled():
                    task.result()
    except Exception as exc:  # noqa: BLE001
        log.warning("开发容器 WebSocket 代理失败: %s -> %s: %s", websocket.url.path, target, exc)
    finally:
        try:
            await websocket.close()
        except Exception:  # noqa: BLE001
            pass


@router.websocket("/dev/{workspace_id}/{project_id}")
async def dev_proxy_ws_root(
    websocket: WebSocket,
    workspace_id: int,
    project_id: int,
    db: AsyncSession = Depends(get_db),
):
    try:
        await _proxy_ws(websocket, db, workspace_id, project_id)
    except Exception:  # noqa: BLE001
        try:
            await websocket.close(code=4401)
        except Exception:  # noqa: BLE001
            pass


@router.websocket("/dev/{workspace_id}/{project_id}/api/v1/ws")
async def dev_proxy_ws_api_root(
    websocket: WebSocket,
    workspace_id: int,
    project_id: int,
    db: AsyncSession = Depends(get_db),
):
    try:
        await _proxy_ws(websocket, db, workspace_id, project_id)
    except Exception:  # noqa: BLE001
        try:
            await websocket.close(code=4401)
        except Exception:  # noqa: BLE001
            pass


@router.websocket("/dev/{workspace_id}/{project_id}/api/v1/ws/{rest:path}")
async def dev_proxy_ws_api(
    websocket: WebSocket,
    workspace_id: int,
    project_id: int,
    rest: str = "",
    db: AsyncSession = Depends(get_db),
):
    try:
        await _proxy_ws(websocket, db, workspace_id, project_id)
    except Exception:  # noqa: BLE001
        try:
            await websocket.close(code=4401)
        except Exception:  # noqa: BLE001
            pass


@router.websocket("/dev/{workspace_id}/{project_id}/{subpath:path}")
async def dev_proxy_ws(
    websocket: WebSocket,
    workspace_id: int,
    project_id: int,
    subpath: str = "",
    db: AsyncSession = Depends(get_db),
):
    try:
        await _proxy_ws(websocket, db, workspace_id, project_id)
    except Exception:  # noqa: BLE001
        try:
            await websocket.close(code=4401)
        except Exception:  # noqa: BLE001
            pass
