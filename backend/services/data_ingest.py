"""数据入库服务: 解析 data.saved 报文, 幂等去重, 落 data_items。

- 默认(Mongo 已配置): 爬虫数据正文落 MongoDB `cdc.data_items` 集合, PG 只存索引与 mongo 引用路径。
- 降级(Mongo 未配置/不可达): content 内联存 PG(可查询/下载), 供本地与测试。
- 预签名模式(prepare/commit): 大文件直传对象存储, 本表只存 storage_path。
"""

from __future__ import annotations

import base64
import hashlib
import json
import time

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..core.ids import snowflake_id
from ..db.models import CrawlerProject, DataItem, Run
from ..db.mongo import mongo_store


class DataError(Exception):
    def __init__(self, status_code: int, code: str, message: str = "", extra: dict | None = None) -> None:
        self.status_code = status_code
        self.code = code
        self.message = message
        self.extra = extra or {}
        super().__init__(code)


class DataIngestService:
    async def ingest(self, session: AsyncSession, delivery_id: str, payload: dict) -> dict:
        data = payload.get("data") or {}
        run_id = data.get("run_id")
        save_id = data.get("save_id")
        if not run_id or not save_id:
            raise DataError(400, "invalid_payload", "缺少 run_id/save_id")

        run = await session.scalar(select(Run).where(Run.run_id == run_id))
        if run is None:
            raise DataError(404, "run_not_found", f"run_id 不存在: {run_id}")
        project = await session.get(CrawlerProject, run.project_id)

        size = int(data.get("size") or 0)
        if size > settings.data_max_single_bytes:
            raise DataError(413, "payload_too_large", f"超出单条上限", {"max_bytes": settings.data_max_single_bytes})

        existing = await session.scalar(
            select(DataItem).where(DataItem.run_id == run_id, DataItem.save_id == save_id)
        )
        if existing is not None:
            return {"ok": True, "accepted": False, "reason": "duplicate", "save_id": save_id, "run_id": run_id}

        # 内容解码校验
        encoding = data.get("encoding", "utf-8")
        content = data.get("content", "")
        decoded_size = size
        if encoding == "base64":
            try:
                decoded = base64.b64decode(content)
                decoded_size = len(decoded)
            except Exception:  # noqa: BLE001
                raise DataError(400, "invalid_payload", "base64 解码失败")
        else:
            decoded_size = len((content or "").encode("utf-8"))

        if decoded_size > settings.data_max_single_bytes:
            raise DataError(413, "payload_too_large", "解码后超出单条上限", {"max_bytes": settings.data_max_single_bytes})

        storage = data.get("storage") or {"mode": "inline"}
        storage_mode = storage.get("mode", "inline")
        storage_path = None
        if storage_mode == "presigned":
            # prepare/commit 流程后, storage_path 由 commit 写入; 此处仅登记
            storage_path = data.get("storage_path")

        # 爬虫数据正文存储: Mongo 优先, 不可用降级内联 PG
        backend = storage_mode
        pg_content: str | None = None
        mongo_id: str | None = None
        if storage_mode == "inline":
            if mongo_store.enabled:
                try:
                    mongo_id = await mongo_store.save_document(
                        {
                            "run_id": run_id,
                            "save_id": save_id,
                            "crawler_id": data.get("crawler_id") or run.crawler_id,
                            "project_id": str(project.id) if project else str(run.project_id),
                            "workspace_id": str(project.workspace_id) if project else str(run.workspace_id),
                            "seq": int(data.get("seq") or 0),
                            "kind": data.get("kind", "content"),
                            "fmt": data.get("fmt", "json"),
                            "name": data.get("name", save_id),
                            "size": decoded_size,
                            "content_hash": data.get("content_hash"),
                            "content_type": data.get("content_type"),
                            "encoding": encoding,
                            "content": content,
                            "source_url": data.get("source_url"),
                            "collected_at": data.get("collected_at") or int(time.time() * 1000),
                            "meta": data.get("meta"),
                        }
                    )
                except Exception:  # noqa: BLE001  # Mongo 不可达时降级内联
                    mongo_id = None
            if mongo_id:
                backend = "mongo"
                storage_path = f"mongo://{settings.mongo_database}.data_items/{mongo_id}"
            else:
                pg_content = content

        item = DataItem(
            id=snowflake_id(),
            run_id=run_id,
            crawler_id=data.get("crawler_id") or run.crawler_id,
            project_id=project.id if project else run.project_id,
            workspace_id=project.workspace_id if project else run.workspace_id,
            save_id=save_id,
            seq=int(data.get("seq") or 0),
            kind=data.get("kind", "content"),
            fmt=data.get("fmt", "json"),
            name=data.get("name", f"{save_id}"),
            size=decoded_size,
            content_hash=data.get("content_hash"),
            content_type=data.get("content_type"),
            encoding=encoding,
            content=pg_content,
            storage_backend=backend,
            storage_path=storage_path,
            source_url=data.get("source_url"),
            collected_at=data.get("collected_at") or int(time.time() * 1000),
            meta_json=data.get("meta"),
            status="stored",
        )
        session.add(item)
        await session.commit()
        return {
            "ok": True,
            "accepted": True,
            "save_id": save_id,
            "run_id": run_id,
            "stored": True,
            "storage": {"backend": backend, "path": storage_path},
            "received_at": int(time.time() * 1000),
        }

    async def get_content_payload(self, item: DataItem) -> tuple[str, str] | None:
        """按存储后端取正文, 返回 (content, encoding); 无正文返回 None。"""
        if item.storage_backend == "mongo" and item.storage_path:
            oid = item.storage_path.rsplit("/", 1)[-1]
            doc = await mongo_store.get_document(oid)
            if doc is not None:
                return doc.get("content", ""), doc.get("encoding", item.encoding)
            return None
        if item.content is not None:
            return item.content, item.encoding
        return None

    async def prepare(self, session: AsyncSession, payload: dict) -> dict:
        """大文件预签名上传: 校验并签发上传地址(生产接 S3/MinIO)。"""
        data = payload.get("data") or {}
        run_id = data.get("run_id")
        save_id = data.get("save_id")
        size = int(data.get("size") or 0)
        if not run_id or not save_id:
            raise DataError(400, "invalid_payload", "缺少 run_id/save_id")
        if size > settings.data_max_single_bytes:
            raise DataError(413, "payload_too_large", "超出单条上限", {"max_bytes": settings.data_max_single_bytes})
        if settings.object_store_impl == "none":
            raise DataError(501, "storage_unavailable", "对象存储未配置")
        # 预留: 生成 S3/MinIO 预签名 PUT 地址
        upload_url = f"{settings.object_store_base_url}/{settings.object_store_bucket}/{run_id}/{save_id}"
        return {
            "ok": True,
            "save_id": save_id,
            "run_id": run_id,
            "upload_url": upload_url,
            "expires_at": int(time.time() * 1000) + 900_000,
        }

    async def commit(self, session: AsyncSession, delivery_id: str, payload: dict) -> dict:
        """大文件上传完成确认: 写入 data_items 索引。"""
        data = payload.get("data") or {}
        data["storage"] = {"mode": "presigned"}
        data["storage_path"] = data.get("storage_path") or (
            f"obj://{settings.object_store_bucket}/{data.get('run_id')}/{data.get('save_id')}"
        )
        # 复用具 ingest 的幂等落库逻辑
        try:
            return await self.ingest(session, delivery_id, {"data": data})
        except DataError as exc:
            if exc.status_code == 413:
                raise
            raise DataError(400, "invalid_payload", exc.message)

    @staticmethod
    def _sha256(text: str) -> str:
        return hashlib.sha256((text or "").encode("utf-8")).hexdigest()

    async def query(
        self,
        session: AsyncSession,
        project_id: int,
        run_id: str | None = None,
        offset: int = 0,
        limit: int = 50,
    ) -> tuple[list[DataItem], int]:
        stmt = select(DataItem).where(DataItem.project_id == project_id)
        if run_id:
            stmt = stmt.where(DataItem.run_id == run_id)
        total = await session.scalar(select(func.count()).select_from(stmt.subquery())) or 0
        rows = (
            await session.execute(stmt.order_by(DataItem.id.desc()).offset(offset).limit(limit))
        ).scalars().all()
        return list(rows), total

    async def get_content(self, session: AsyncSession, item_id: int) -> DataItem | None:
        return await session.get(DataItem, item_id)