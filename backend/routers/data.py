"""数据浏览路由: 按项目查询 data_items / 下载内容。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from ..api.deps import get_current_user
from ..api.errors import not_found
from ..db.models import CrawlerProject, User
from ..db.session import get_db
from ..rbac.service import has_permission
from ..schemas.webhook import DataItemOut
from ..services.data_ingest import DataIngestService
from ..services.project import ProjectService

router = APIRouter(tags=["data"])

_CONTENT_TYPES = {
    "txt": "text/plain; charset=utf-8",
    "json": "application/json; charset=utf-8",
    "jsonl": "application/x-ndjson; charset=utf-8",
    "csv": "text/csv; charset=utf-8",
    "html": "text/html; charset=utf-8",
    "img": "image/png",
}


async def _project_check(db: AsyncSession, project_id: int, user: User) -> CrawlerProject:
    project = await ProjectService.get(db, project_id)
    if project is None:
        raise not_found("project_not_found", "项目不存在")
    grant = await has_permission(db, user.id, "data:read", workspace_id=project.workspace_id, project_id=project.id)
    if not grant.granted:
        from ..api.errors import forbidden

        raise forbidden("forbidden")
    return project


@router.get("/projects/{project_id}/data", response_model=list[DataItemOut])
async def list_data(
    project_id: int,
    run_id: str | None = None,
    offset: int = 0,
    limit: int = 50,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    project = await _project_check(db, project_id, user)
    items, _ = await DataIngestService().query(db, project.id, run_id, offset, min(200, max(1, limit)))
    return items


@router.get("/data/{item_id}/download")
async def download_data(
    item_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    item = await DataIngestService().get_content(db, item_id)
    if item is None:
        raise not_found("data_not_found", "数据不存在")
    project = await _project_check(db, item.project_id, user)
    if item.storage_backend not in ("inline", "mongo"):
        raise HTTPException(404, detail={"ok": False, "error": "not_inline", "message": "大文件请走对象存储下载"})
    payload = await DataIngestService().get_content_payload(item)
    if payload is None:
        raise HTTPException(404, detail={"ok": False, "error": "content_unavailable", "message": "正文不可用"})
    content, encoding = payload
    ctype = _CONTENT_TYPES.get(item.fmt, "application/octet-stream")
    body = content.encode("utf-8") if encoding == "utf-8" else content
    return Response(content=body, media_type=ctype)