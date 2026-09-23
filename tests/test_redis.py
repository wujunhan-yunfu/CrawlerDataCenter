"""Redis 中间件单元测试。"""

from __future__ import annotations

import asyncio
import json

import pytest

from backend.redis.client import (
    HotState,
    LiveTokenStore,
    RateLimiter,
    RedisLock,
    TaskQueue,
    TokenStore,
    redis,
)


async def test_rate_limiter(rds):
    rl = RateLimiter(rds.client)
    for _ in range(3):
        allowed, count = await rl.check("t", "k", 3, 60)
    assert allowed is True
    assert count == 3
    allowed, _ = await rl.check("t", "k", 3, 60)
    assert allowed is False


async def test_token_store(rds):
    ts = TokenStore(rds.client)
    await ts.save_refresh(1, "jti-1", 100)
    assert await ts.refresh_valid(1, "jti-1")
    await ts.revoke_refresh(1, "jti-1")
    assert not await ts.refresh_valid(1, "jti-1")

    await ts.blacklist_access("acc-1", 100)
    assert await ts.is_blacklisted("acc-1")


async def test_task_queue(rds):
    q = TaskQueue(rds.client)
    await q.push("jobs", {"x": 1})
    await q.push("jobs", {"x": 2})
    assert await q.len("jobs") == 2
    task = await q.lease("jobs", timeout=1)
    assert task.payload["x"] == 1
    assert task.payload["_id"]
    await q.ack(task)
    assert await q.len("jobs") == 1


async def test_task_queue_nack_retry_and_promote(rds):
    q = TaskQueue(rds.client)
    await q.push("jobs", {"x": 1})
    task = await q.lease("jobs", timeout=1)
    assert task is not None
    outcome = await q.nack(task, max_attempts=3, delay_ms=10)
    assert outcome == "retry"
    # 任务进入延迟队列
    stats = await q.stats("jobs")
    assert stats["delayed"] == 1
    assert stats["processing"] == 0
    # 到期后 promote 回主队列
    import asyncio

    await asyncio.sleep(0.05)
    moved = await q.promote_delayed("jobs")
    assert moved == 1
    task2 = await q.lease("jobs", timeout=1)
    assert task2.payload["_attempts"] == 1


async def test_task_queue_dead_letter(rds):
    q = TaskQueue(rds.client)
    await q.push("jobs", {"x": 1})
    # 模拟 worker 多次 lease -> 失败 -> nack -> promote 的循环, 超过上限进死信
    final_outcome = None
    for _ in range(3):
        task = await q.lease("jobs", timeout=1)
        assert task is not None
        final_outcome = await q.nack(task, max_attempts=3, delay_ms=0)
        await q.promote_delayed("jobs")
    assert final_outcome == "dead"
    stats = await q.stats("jobs")
    assert stats["dead"] == 1
    assert stats["queued"] == 0


async def test_task_queue_recover_stale(rds):
    q = TaskQueue(rds.client)
    await q.push("jobs", {"x": 1})
    task = await q.lease("jobs", timeout=1)
    # 未 ack/nack, 模拟 worker 崩溃: 强制过期租约
    from backend.redis.client import redis as redis_singleton

    await redis_singleton.client.delete(redis_singleton.k("q", "jobs", "lease", task.payload["_id"]))
    recovered = await q.recover_stale("jobs", stale_ms=0)
    assert recovered == 1
    task2 = await q.lease("jobs", timeout=1)
    assert task2.payload["_id"] == task.payload["_id"]


async def test_hot_state(rds):
    hs = HotState(rds.client)
    await hs.set_json("k", {"a": 1}, ttl=10)
    assert (await hs.get_json("k"))["a"] == 1


async def test_live_token_store(rds):
    ls = LiveTokenStore(rds.client)
    await ls.issue("tok", {"user_id": 1, "project_id": 2}, ttl=10)
    info = await ls.verify("tok")
    assert info["project_id"] == 2
    await ls.revoke("tok")
    assert await ls.verify("tok") is None


async def test_redis_lock(rds):
    lock = RedisLock(rds.client)
    nonce = await lock.acquire("name", "scope")
    assert nonce is not None
    # 第二次获取失败
    assert await lock.acquire("name", "scope") is None
    await lock.release("name", "scope", nonce)
    assert await lock.acquire("name", "scope") is not None


async def test_redis_lock_run_locked(rds):
    lock = RedisLock(rds.client)
    result = await lock.run_locked("name", "s2", lambda: "done")
    assert result == "done"
    # 锁释放后可再次获取
    assert await lock.acquire("name", "s2") is not None