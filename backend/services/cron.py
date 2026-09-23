"""cron 表达式校验与下次运行计算(与 ACS backend/services/cron.py 语义一致, 独立实现)。"""

from __future__ import annotations

from datetime import datetime

from croniter import croniter


def validate_cron(expr: str) -> bool:
    if not expr or not expr.strip():
        return False
    try:
        croniter(expr.strip())
        return True
    except (ValueError, KeyError):
        return False


def next_runs(expr: str, count: int = 1, base: datetime | None = None) -> list[datetime]:
    """计算未来 count 次运行时间(UTC)。"""
    expr = expr.strip()
    if not validate_cron(expr):
        raise ValueError(f"cron 表达式无效: {expr}")
    base = base or datetime.now()
    it = croniter(expr, base)
    return [it.get_next(datetime) for _ in range(count)]


def next_run_ms(expr: str, base: datetime | None = None) -> int:
    """返回下次运行 Unix 毫秒。"""
    return int(next_runs(expr, 1, base)[0].timestamp() * 1000)