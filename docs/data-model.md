# 数据模型设计（PostgreSQL + Redis）

## 1. 设计原则

- **事实源在 PostgreSQL**；Redis 仅存易失的会话/锁/队列/热状态，可随时重建。
- 全部业务表带 `created_at` / `updated_at`；审计与运行类表额外带 `id` 单调自增用于顺序保证。
- 主键使用 64 位雪花式 `id`（`core/ids.py`），对外以 `xid`（如 `ws_xxx`、`p_xxx`、`run_xxx`）暴露，内部关系用整数主键。
- 雪花 `id` 超出 JavaScript `Number` 安全整数范围（2^53-1），JSON 响应中一律序列化为**字符串**（见 `schemas/common.py` 的 `SnowflakeId`），前端始终以字符串传递 id，避免 `JSON.parse` 丢精度导致按 id 请求详情时报 "不存在"。
- 所有业务表冗余 `workspace_id` 便于按空间过滤与配额统计。
- 幂等与唯一约束全部落在 PG 唯一索引上。

## 2. 表清单

### 2.1 用户与认证

| 表 | 关键字段 | 说明 |
| --- | --- | --- |
| `users` | id, username(unique), email(unique), password_hash, status(`active/disabled/pending`), last_login_at | 用户 |
| `refresh_tokens` | id, user_id, jti(unique), expires_at, revoked_at, created_ip | 可撤销刷新令牌（配合 Redis 白名单） |

### 2.2 RBAC

| 表 | 关键字段 | 说明 |
| --- | --- | --- |
| `roles` | id, name, scope(`global/workspace/project`), description | 内置角色种子：super_admin/workspace_owner/workspace_admin/developer/operator/viewer |
| `role_permissions` | id, role_id, permission | 角色 → 权限点（多对多） |
| `role_bindings` | id, user_id, role_id, workspace_id(nullable), project_id(nullable) | 用户 → 角色绑定，scope 由 `(workspace_id, project_id)` 决定 |

**权限解析**：`(user, permission)` 有效当且仅当存在一条绑定满足：
`role.permissions ⊇ {permission}` 且绑定范围覆盖被访问资源（global 绑定全空间，workspace 绑定限定空间内全部项目，project 绑定限定单项目）。scope 优先级 project > workspace > global，取最具体者。

### 2.3 工作空间与项目

| 表 | 关键字段 | 说明 |
| --- | --- | --- |
| `workspaces` | id, name, owner_id, status(`active/disabled/deleted`), quota_json, deleted_at | 工作空间；`quota_json` 存容器并发/数据容量配额 |
| `workspace_members` | id, workspace_id, user_id, role_id, joined_at | 成员（便捷冗余表，与 role_bindings 保持同步写入） |
| `crawler_projects` | id, workspace_id, name, description, source_type(`builtin/custom`), builtin_crawler_id, crawler_id(unique), run_config_json, status(`active/disabled`) | 爬虫项目；`run_config_json` 存 once/cron/headless/webhook 等默认 |

### 2.4 开发容器

| 表 | 关键字段 | 说明 |
| --- | --- | --- |
| `dev_containers` | id, project_id, crawler_id, pod_name, service_name, namespace, dev_url, phase(`absent/pending/starting/ready/stopping/failed`), last_active_at, error_code, expires_at | 开发容器状态；`project_id` 唯一 → 同项目最多一个 dev Pod |

### 2.5 运行与进程

| 表 | 关键字段 | 说明 |
| --- | --- | --- |
| `runs` | id, run_id(unique), project_id, crawler_id, workspace_id, mode(`login/run`), trigger(`once/cron`), run_type, cron, attempt, status(`pending/running/succeeded/failed/skipped`), started_at, finished_at, duration_ms, error_json, next_run_at | 运行记录；`error_json` 存 {type,message,detail,stage} |
| `run_processes` | id, process_id(unique), project_id, crawler_id, workspace_id, run_type, cron, pod_name, status(`alive/running/degraded/stopping/stopped/unreachable`), pid, started_at, last_heartbeat_at, uptime_ms, next_run_at, last_run_json, health_json | 定时任务进程（cron 常驻），心跳更新 |
| `run_results` | id, run_id, name, kind, size, save_id, delivery, remote_path, content_hash | 运行产物索引（由 run 结束 webhook 汇总写入） |

### 2.6 数据与投递

| 表 | 关键字段 | 说明 |
| --- | --- | --- |
| `data_items` | id, run_id, crawler_id, workspace_id, project_id, save_id, seq, kind, fmt, name, size, content_hash, storage_backend(`mongo/inline/presigned`), storage_path, source_url, collected_at, status(`stored/failed`) | 每次 `data.saved` 推送落库一行；唯一键 `(run_id, save_id)`。**正文默认存 MongoDB `cdc.data_items` 集合**，PG 只存索引与 `mongo://cdc.data_items/<oid>` 引用路径；Mongo 不可达时降级内联存 PG `content` |
| `webhook_deliveries` | id, delivery_id(unique), run_id, kind(`run/heartbeat/data`), event, url, attempt, status_code, response, next_retry_at, state(`pending/success/failed/dead`) | 出站投递与入站接收均记录（入站记录在 `webhook_events`） |

**入站幂等**：`(kind, event, delivery_id)` 唯一；重复投递直接返回 `accepted=false, reason=duplicate`。

### 2.7 审计

| 表 | 关键字段 | 说明 |
| --- | --- | --- |
| `audit_logs` | id, actor_id, action, target_type, target_id, workspace_id, detail_json, ip, user_agent, created_at | 敏感操作审计 |

## 3. Redis Key 规划

| Key 模式 | 用途 | TTL |
| --- | --- | --- |
| `rt:{uid}:{jti}` | 刷新令牌白名单 | 7d |
| `blk:{jti}` | 访问令牌黑名单 | 剩余 TTL |
| `rl:{kind}:{scope}:{key}` | 限流计数 | 窗口 |
| `lock:{name}:{scope}` | 分布式锁 | 秒级 |
| `q:{queue}` | 任务队列（list，`lpush` 入队） | — |
| `q:{queue}:processing` | 进行中租约（`brpoplpush` 原子移入） | — |
| `q:{queue}:delayed` | 延迟重试（zset，指数退避） | — |
| `q:{queue}:dead` | 死信（超过 `max_attempts`） | — |
| `q:{queue}:lease:{task_id}` | 租约时间戳（`recover_stale` 崩溃回收依据） | 5min |
| `dev:{project_id}` | 开发容器热状态 | 10min |
| `devtask:{task_id}` | 开发容器拉起任务元数据(项目/开始时间, 供超时判定) | 超时+5min |
| `proc:{process_id}` | 进程心跳热状态 | 心跳间隔×3 |
| `live:{token}` | login 画面短时令牌 → {user,project,run} | 10min |

> **队列可靠性**：`lpush` 入队 + `brpoplpush` 原子租约 → 成功 `ack`(lrem) / 失败 `nack`
> （按 `_attempts` 指数退避进 delayed zset，到期由 `promote_delayed` 回队）→ 超次进 dead 死信；
> worker 崩溃后其租约由 `recover_stale` 超时回收重投。`TaskQueue.stats()` 提供排队/处理中/延迟/死信计数。

## 4. 时序说明

- 所有 `*_at` 存 **Unix 毫秒**（与 ACS `now_ms()`/webhook 报文一致），杜绝时区歧义。
- `cron` 表达式校验/下次运行计算复用 ACS 的 `backend/services/cron.py` 语义（本仓库 `backend/services/cron.py` 提供等价实现）。
- 软删除优先（`deleted_at`/`status=deleted`），硬删除仅用于数据卷清理任务。