"""MongoDB 客户端(爬虫数据存储)。

爬虫数据(data.saved)的正文落 MongoDB `cdc.data_items` 集合;
PostgreSQL 只存索引与引用路径, 避免大文本膨胀 PG。
未配置/不可达时回退内联 PG 存储(data_ingest 自动降级)。
"""

from __future__ import annotations

from datetime import datetime

from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorCollection

from ..config import settings


class MongoStore:
    def __init__(self) -> None:
        self._client: AsyncIOMotorClient | None = None
        self._collection: AsyncIOMotorCollection | None = None

    @property
    def enabled(self) -> bool:
        return bool(settings.mongo_host)

    def _uri(self) -> str:
        auth = ""
        if settings.mongo_username:
            auth = f"{settings.mongo_username}:{settings.mongo_password or ''}@"
        return f"mongodb://{auth}{settings.mongo_host}:{settings.mongo_port}"

    def collection(self) -> AsyncIOMotorCollection:
        if self._collection is None:
            self._client = AsyncIOMotorClient(self._uri(), serverSelectionTimeoutMS=3000)
            self._collection = self._client[settings.mongo_database]["data_items"]
        return self._collection

    async def save_document(self, doc: dict) -> str | None:
        """写入一条数据文档, 返回 Mongo ObjectId 字符串。"""
        if not self.enabled:
            return None
        col = self.collection()
        doc["created_at"] = datetime.utcnow()
        result = await col.insert_one(doc)
        return str(result.inserted_id)

    async def get_document(self, oid: str) -> dict | None:
        if not self.enabled:
            return None
        from bson.objectid import ObjectId

        try:
            return await self.collection().find_one({"_id": ObjectId(oid)})
        except Exception:  # noqa: BLE001
            return None

    async def ping(self) -> bool:
        if not self.enabled:
            return False
        try:
            await self.client().admin.command("ping")
            return True
        except Exception:  # noqa: BLE001
            return False

    def client(self) -> AsyncIOMotorClient:
        if self._client is None:
            self._client = AsyncIOMotorClient(self._uri(), serverSelectionTimeoutMS=3000)
        return self._client


mongo_store = MongoStore()