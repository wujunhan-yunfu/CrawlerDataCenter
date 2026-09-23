"""Redis 客户端与中间件：限流、分布式锁、令牌存储、任务队列、热状态缓存。"""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from collections.abc import AsyncGenerator

import redis.asyncio as aioredis

from ..config import settings


class Redis:
    def __init__(self) -> None:
        self._client: aioredis.Redis | None = None

    @property
    def client(self) -> aioredis.Redis:
        if self._client is None:
            self._client = aioredis.from_url(
                settings.redis_url, decode_responses=True, encoding="utf-8"
            )
        return self._client

    def set_client(self, client: aioredis.Redis) -> None:
        self._client = client

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    # ---- key 辅助 ----
    def k(self, *parts: str) -> str:
        return ":".join((settings.redis_prefix, *parts))


redis = Redis()


async def get_redis() -> AsyncGenerator[aioredis.Redis, None]:
    yield redis.client


async def ping_redis() -> bool:
    try:
        return bool(await redis.client.ping())
    except Exception:  # noqa: BLE001
        return False


class RateLimiter:
    """固定窗口限流: rl:{kind}:{window}:{key} -> count。"""

    def __init__(self, client: aioredis.Redis | None = None) -> None:
        self._client = client

    @property
    def client(self) -> aioredis.Redis:
        return self._client or redis.client

    async def check(self, kind: str, key: str, limit: int, window: int) -> tuple[bool, int]:
        """返回 (是否放行, 当前计数)。"""
        rkey = redis.k("rl", kind, str(window), key)
        pipe = self.client.pipeline()
        pipe.incr(rkey)
        pipe.expire(rkey, window)
        count, _ = await pipe.execute()
        return int(count) <= limit, int(count)


class RedisLock:
    """分布式锁: lock:{name}:{scope}, 持有者 nonce 校验防止误删。"""

    def __init__(self, client: aioredis.Redis | None = None) -> None:
        self._client = client

    @property
    def client(self) -> aioredis.Redis:
        return self._client or redis.client

    async def acquire(self, name: str, scope: str = "", ttl: int = 30) -> str | None:
        nonce = uuid.uuid4().hex
        rkey = redis.k("lock", name, scope or "global")
        ok = await self.client.set(rkey, nonce, nx=True, px=ttl * 1000)
        return nonce if ok else None

    async def release(self, name: str, scope: str, nonce: str) -> None:
        rkey = redis.k("lock", name, scope or "global")

        async def _release(pipe):
            cur = await pipe.get(rkey)
            if cur == nonce:
                await pipe.delete(rkey)

        await self.client.transaction(_release, rkey)

    async def run_locked(
        self, name: str, scope: str, func, ttl: int = 30, *args, **kwargs
    ):
        """持锁执行; 抢锁失败返回 None。支持同步/异步函数。"""
        nonce = await self.acquire(name, scope, ttl)
        if nonce is None:
            return None
        try:
            result = func(*args, **kwargs)
            if asyncio.iscoroutine(result):
                return await result
            return result
        finally:
            await self.release(name, scope, nonce)


class TokenStore:
    """刷新令牌白名单 + 访问令牌黑名单。"""

    def __init__(self, client: aioredis.Redis | None = None) -> None:
        self._client = client

    @property
    def client(self) -> aioredis.Redis:
        return self._client or redis.client

    async def save_refresh(self, user_id: int, jti: str, ttl: int) -> None:
        await self.client.set(redis.k("rt", str(user_id), jti), "1", ex=ttl)

    async def revoke_refresh(self, user_id: int, jti: str) -> None:
        await self.client.delete(redis.k("rt", str(user_id), jti))

    async def refresh_valid(self, user_id: int, jti: str) -> bool:
        return bool(await self.client.get(redis.k("rt", str(user_id), jti)))

    async def blacklist_access(self, jti: str, ttl: int) -> None:
        await self.client.set(redis.k("blk", jti), "1", ex=ttl)

    async def is_blacklisted(self, jti: str) -> bool:
        return bool(await self.client.get(redis.k("blk", jti)))


class LeasedTask:
    """可靠投递的一次性租约: raw 为队列中的原始 JSON, 供 ack/nack 精确匹配。"""

    __slots__ = ("queue", "payload", "raw")

    def __init__(self, queue: str, payload: dict, raw: str) -> None:
        self.queue = queue
        self.payload = payload
        self.raw = raw


class TaskQueue:
    """可靠任务队列(Redis List + ZSet)。

    可靠性模型:
    - push            -> rpush q:{queue}(任务带 _id/_attempts)
    - lease           -> brpoplpush q:{queue} -> q:{queue}:processing (原子, 崩溃不丢)
    - ack             -> 处理成功, lrem processing
    - nack            -> 失败: 未超次 -> 延迟重试(delayed zset, 指数退避);
                         超次   -> 死信 q:{queue}:dead
    - promote_delayed -> worker 周期把到期任务回主队列
    - recover_stale   -> worker 回收 processing 中租约超时的任务(worker 崩溃兜底)
    """

    def __init__(self, client: aioredis.Redis | None = None) -> None:
        self._client = client

    @property
    def client(self) -> aioredis.Redis:
        return self._client or redis.client

    # ---- key ----
    def _q(self, queue: str) -> str:
        return redis.k("q", queue)

    def _proc(self, queue: str) -> str:
        return redis.k("q", queue, "processing")

    def _delay(self, queue: str) -> str:
        return redis.k("q", queue, "delayed")

    def _dead(self, queue: str) -> str:
        return redis.k("q", queue, "dead")

    def _lease_key(self, queue: str, task_id: str) -> str:
        return redis.k("q", queue, "lease", task_id)

    @staticmethod
    def _dump(payload: dict) -> str:
        return json.dumps(payload, ensure_ascii=False)

    # ---- 投递 ----
    async def push(self, queue: str, payload: dict) -> None:
        item = dict(payload)
        item.setdefault("_id", uuid.uuid4().hex)
        item.setdefault("_attempts", 0)
        # lpush 入队 + brpoplpush 出队 => FIFO
        await self.client.lpush(self._q(queue), self._dump(item))

    async def lease(self, queue: str, timeout: int = 30, lease_ttl_ms: int = 300_000) -> LeasedTask | None:
        """原子取任务并放入 processing。lease_ttl_ms 内未 ack/nack 可被 recover_stale 回收。"""
        raw = await self.client.brpoplpush(self._q(queue), self._proc(queue), timeout=timeout)
        if raw is None:
            return None
        try:
            payload = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            payload = {"_id": None, "_raw": raw}
        if payload.get("_id"):
            await self.client.set(
                self._lease_key(queue, payload["_id"]),
                str(int(time.time() * 1000)),
                px=lease_ttl_ms,
            )
        return LeasedTask(queue, payload, raw)

    async def ack(self, task: LeasedTask) -> None:
        await self.client.lrem(self._proc(task.queue), 1, task.raw)
        if task.payload.get("_id"):
            await self.client.delete(self._lease_key(task.queue, task.payload["_id"]))

    async def nack(
        self,
        task: LeasedTask,
        max_attempts: int = 5,
        delay_ms: int = 5_000,
    ) -> str:
        """处理失败。返回 'retry' | 'dead'。延迟指数退避: delay_ms * 2^(_attempts-1)。"""
        payload = dict(task.payload)
        attempts = int(payload.get("_attempts", 0)) + 1
        payload["_attempts"] = attempts
        await self.client.lrem(self._proc(task.queue), 1, task.raw)
        if task.payload.get("_id"):
            await self.client.delete(self._lease_key(task.queue, task.payload["_id"]))
        if attempts >= max_attempts:
            await self.client.rpush(self._dead(task.queue), self._dump(payload))
            return "dead"
        backoff = delay_ms * (2 ** (attempts - 1))
        score = time.time() * 1000 + backoff
        await self.client.zadd(self._delay(task.queue), {self._dump(payload): score})
        return "retry"

    # ---- 维护 ----
    async def promote_delayed(self, queue: str) -> int:
        """把到期的延迟任务回主队列, 返回条数。"""
        now = time.time() * 1000
        items = await self.client.zrangebyscore(self._delay(queue), 0, now)
        moved = 0
        for raw in items:
            removed = await self.client.zrem(self._delay(queue), raw)
            if removed:
                await self.client.rpush(self._q(queue), raw)
                moved += 1
        return moved

    async def recover_stale(self, queue: str, stale_ms: int = 300_000) -> int:
        """回收 processing 中租约超时的任务(worker 崩溃兜底), 返回条数。"""
        now = int(time.time() * 1000)
        recovered = 0
        raws = await self.client.lrange(self._proc(queue), 0, -1)
        for raw in raws:
            try:
                payload = json.loads(raw)
            except (json.JSONDecodeError, TypeError):
                continue
            task_id = payload.get("_id")
            if not task_id:
                continue
            lease_val = await self.client.get(self._lease_key(queue, task_id))
            if lease_val is None or now - int(lease_val) > stale_ms:
                removed = await self.client.lrem(self._proc(queue), 1, raw)
                if removed:
                    await self.client.rpush(self._q(queue), raw)
                    await self.client.delete(self._lease_key(queue, task_id))
                    recovered += 1
        return recovered

    async def stats(self, queue: str) -> dict:
        return {
            "queued": int(await self.client.llen(self._q(queue))),
            "processing": int(await self.client.llen(self._proc(queue))),
            "delayed": int(await self.client.zcard(self._delay(queue))),
            "dead": int(await self.client.llen(self._dead(queue))),
        }

    async def len(self, queue: str) -> int:
        return int(await self.client.llen(self._q(queue)))


class HotState:
    """热状态缓存(dev 容器/进程), 读写 JSON。"""

    def __init__(self, client: aioredis.Redis | None = None) -> None:
        self._client = client

    @property
    def client(self) -> aioredis.Redis:
        return self._client or redis.client

    async def set_json(self, key: str, value: dict, ttl: int = 600) -> None:
        await self.client.set(key, json.dumps(value, ensure_ascii=False), ex=ttl)

    async def get_json(self, key: str) -> dict | None:
        raw = await self.client.get(key)
        if not raw:
            return None
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return None


class LiveTokenStore:
    """login 实时画面短时令牌: live:{token} -> {user_id, project_id, run_id}。"""

    def __init__(self, client: aioredis.Redis | None = None) -> None:
        self._client = client

    @property
    def client(self) -> aioredis.Redis:
        return self._client or redis.client

    async def issue(self, token: str, payload: dict, ttl: int = 600) -> None:
        await self.client.set(redis.k("live", token), json.dumps(payload), ex=ttl)

    async def verify(self, token: str) -> dict | None:
        raw = await self.client.get(redis.k("live", token))
        if not raw:
            return None
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return None

    async def revoke(self, token: str) -> None:
        await self.client.delete(redis.k("live", token))