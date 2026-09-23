"""ID 生成: 雪花式 64 位 id 与对外 xid 编码。

- 雪花 id: 41 位时间戳 + 10 位机器/进程 + 12 位自增序列。
- xid: 短字符串, 如 ws_xxx / p_xxx / run_xxx, 用于 API 暴露。
"""

from __future__ import annotations

import base64
import os
import threading
import time

_EPOCH = 1700000000000  # 2023-11-14, 使时间戳段可用更久
_NODE = os.getpid() & 0x3FF
_seq = 0
_seq_lock = threading.Lock()
_last_ms = 0


def snowflake_id() -> int:
    """生成全局单调递增的 64 位 id。"""
    global _seq, _last_ms
    now = int(time.time() * 1000)
    with _seq_lock:
        if now == _last_ms:
            _seq = (_seq + 1) & 0xFFF
            if _seq == 0:
                while now <= _last_ms:
                    now = int(time.time() * 1000)
        else:
            _seq = 0
        _last_ms = now
        return ((now - _EPOCH) << 22) | (_NODE << 12) | _seq


def new_xid(prefix: str) -> str:
    """生成对外 xid, 如 new_xid("run") -> run_ab12cd34。"""
    raw = (prefix + "_" + os.urandom(6).hex()).encode()
    return base64.urlsafe_b64encode(raw).decode()[: 8 + len(prefix) + 1].replace("-", "")


def new_run_id() -> str:
    return new_xid("run")


def new_delivery_id() -> str:
    return new_xid("dlv")


def new_process_id() -> str:
    return new_xid("proc")