# 调度、心跳巡检、数据入库与 API 概览

## 1. 调度模型

- **ACS 进程内调度**（复用 `cron.py`）：run+cron 常驻 Pod 自己算下次时间并执行，CDC 只负责启停 Pod。
- **CDC 职责**：创建/删除 cron Pod（`run_processes` 记录进程元数据）、接收心跳判定存活、展示进程状态。
- 触发 run 时 CDC 生成 `run_id` 并以 env `RUN_ID`/`RUN_TYPE`/`CRON`/`WEBHOOK_URL` 下发。

**触发流程（once）**：`POST /projects/{id}/runs {trigger: once, headless: true}` →
创建一次性 K8s Job（restartPolicy Never）→ 返回 `run_id`（pending）。
**触发流程（cron）**：`POST /projects/{id}/runs {trigger: cron, cron: "*/30 * * * *"}` →
校验表达式 → upsert `run_processes` → 创建/更新常驻 Deployment（replicas=1）→ 返回 `process_id`。

## 2. 心跳与存活检测

| 角色 | 机制 |
| --- | --- |
| ACS | cron 主循环每 `--heartbeat-interval`(30s) 发一次 `POST /webhooks/heartbeat`；运行开始/结束立即补发；优雅退出发 `stopping` |
| CDC | 接收心跳更新 `run_processes`（last_heartbeat_at/status/health/next_run_at/last_run） |
| CDC monitor | 每 10s 巡检：`now - last_heartbeat_at > max(3×interval, 90s)` → `status=unreachable` + 告警 + 按策略重启 Deployment Pod |
| CDC monitor | `health.*` 任一 false → `degraded`；连续 N 次降级升级为重启 |

与 K8s 探针互补：探针保证单容器自愈（`GET /healthz`），心跳保证 CDC 全局可观测。

## 3. 数据入库（data.saved）

1. ACS `save_content` 保存成功后构造 `data.saved` 报文（内联 ≤1MB，大文件走预签名直传）。
2. CDC `POST /webhooks/data`：签名 → 幂等(`(run_id, save_id)`) → 校验 → 落库。
3. **正文默认写 MongoDB `cdc.data_items` 集合**，PG `data_items` 只存索引与 `mongo://` 引用路径；
   Mongo 不可达时自动降级内联存 PG `content`。
4. 写库后更新项目数据配额；`runs` 结束事件的 `saved[]` 标记 `delivery` 状态。
5. 异步写库通过 Redis 队列 + worker 消费，避免阻塞 webhook 返回。

## 4. CDC API 概览（前缀 `/api/v1`）

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| POST | `/auth/register` `/auth/login` `/auth/refresh` `/auth/logout` | 认证（含验证码限流） |
| GET/POST | `/workspaces` | 工作空间列表/创建 |
| GET/PATCH/DELETE | `/workspaces/{id}` | 工作空间详情/更新/删除(二次确认) |
| POST | `/workspaces/{id}/members` | 邀请成员 + 角色绑定 |
| DELETE | `/workspaces/{id}/members/{uid}` | 移除成员 |
| GET/POST | `/workspaces/{id}/projects` | 项目列表/创建 |
| GET/PATCH/DELETE | `/projects/{id}` | 项目详情/更新/删除 |
| POST | `/projects/{id}/dev-container` | 确保开发容器拉起 |
| GET | `/projects/{id}/dev-container` | 轮询容器状态 |
| POST | `/projects/{id}/login` | 触发 login 运行（返回 run_id + live_ws_url） |
| GET | `/projects/{id}/login/live` | WebSocket 只读实时画面代理 |
| POST | `/projects/{id}/runs` | 触发 run（once/cron） |
| GET | `/projects/{id}/runs` | 运行记录 |
| GET | `/runs/{run_id}` | 运行详情/结果 |
| GET | `/projects/{id}/run-process` | 定时进程存活/健康状态 |
| POST | `/webhooks/runs` `/webhooks/heartbeat` `/webhooks/data` | ACS 回调接收（签名+幂等） |
| POST | `/webhooks/data/prepare` `/webhooks/data/commit` | 大文件预签名直传 |
| GET | `/projects/{id}/data` | 数据浏览/下载 |
| GET | `/audit` | 审计日志 |
| GET | `/healthz` | CDC 自身探针 |

详见 `docs/api.md`（路由、请求/响应 Schema 与错误码统一约定）。