"""CDC 自身探针: GET /healthz(不走 /api/v1 前缀)。"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from ..db.session import get_db, ping_db
from ..redis.client import ping_redis
from ..schemas.webhook import HealthOut

router = APIRouter(tags=["system"])


@router.get("/healthz", response_model=HealthOut)
async def healthz(db: AsyncSession = Depends(get_db)):
    ok_db = await ping_db()
    ok_redis = await ping_redis()
    return HealthOut(ok=ok_db and ok_redis, db=ok_db, redis=ok_redis)