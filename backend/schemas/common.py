"""公共 Schema 类型。"""

from __future__ import annotations

from typing import Annotated

from pydantic import PlainSerializer

# 雪花 id 是 64 位整数, 会超过 JavaScript Number 的安全整数范围(2^53 - 1)。
# 若以 JSON number 下发, 前端 `JSON.parse` 会把它四舍五入, 于是按 id 请求
# 详情/操作时命中不到记录(表现为 "项目不存在" / "工作空间不存在")。
# 因此所有对外的雪花 id 统一序列化为字符串, 前后端始终以字符串传递 id。
SnowflakeId = Annotated[int, PlainSerializer(str, return_type=str, when_used="always")]
