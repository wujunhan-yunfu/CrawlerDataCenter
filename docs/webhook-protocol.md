# Webhook 接收协议（与 ACS 对齐）

ACS 的 `backend/services/runmode/webhook.py`、`heartbeat.py`、`data_webhook.py` 是发送方，CDC 侧接收端必须与其严格对齐。
本仓库的 `backend/services/webhook_receiver.py` 统一实现签名校验、时间戳防重放、幂等、状态机校验。

## 1. 公共信封与签名

```
Headers:
  Content-Type:         application/json
  X-Webhook-Event:      run.started | run.succeeded | run.failed | run.skipped
                        heartbeat | data.saved
  X-Webhook-Delivery:   uuid（投递唯一 ID，幂等键）
  X-Webhook-Timestamp:  毫秒时间戳
  X-Webhook-Signature:  sha256=HMAC_SHA256(secret, timestamp + "." + raw_body)
```

校验顺序：签名 → 时间戳新鲜度（±5min，防重放）→ 幂等（重复即 200 duplicate）→ 载荷 → 状态机。

## 2. 端点

| 端点 | 事件 | 处理 |
| --- | --- | --- |
| `POST /api/v1/webhooks/runs` | `run.*` | 更新 `runs` 状态/结果，写 `run_results`，触发告警/重试策略 |
| `POST /api/v1/webhooks/heartbeat` | `heartbeat` | 更新 `run_processes` 存活/健康 |
| `POST /api/v1/webhooks/data` | `data.saved` | 按 `seq` 落库 `data_items` + 对象存储 |
| `POST /api/v1/webhooks/data/prepare` | — | 大文件：签发预签名上传地址 |
| `POST /api/v1/webhooks/data/commit` | — | 大文件：确认已上传并落索引 |

## 3. run 事件载荷（节选自 ACS RunContext.to_dict）

```json
{
  "event": "run.failed",
  "delivery_id": "dlv_9f2c...",
  "timestamp": 1750000000000,
  "run": {
    "run_id": "run_abc123", "crawler_id": "proj_xxx",
    "project_id": "p_123", "workspace_id": "ws_456",
    "mode": "run", "trigger": "cron", "run_type": "cron", "cron": "*/30 * * * *",
    "process_id": "proc_abc123", "attempt": 1, "status": "failed",
    "started_at": 1749999990000, "finished_at": 1750000000000, "duration_ms": 10000,
    "error": {"type": "login_failed", "message": "...", "detail": "..."},
    "saved": [{"name": "content_ab12.json", "kind": "content", "size": 2048,
               "save_id": "sav_xyz", "delivery": "delivered", "remote_path": "..."}],
    "next_run_at": 1750001800000
  }
}
```

`error.type` 取值：`login_failed | login_not_saved | login_timeout | verification_failed | code_error | no_code | browser_error | internal_error`。

**状态机（CDC 校验）**：`started → succeeded|failed|skipped`；同一 run 不允许非法回退
（如 `succeeded → failed` 返回 `state_conflict`）。

## 4. 返回约定

| HTTP | 场景 | Body |
| --- | --- | --- |
| 200 | 接受 | `{"ok":true,"accepted":true,...}` |
| 200 | 幂等重复 | `{"ok":true,"accepted":false,"reason":"duplicate"}` |
| 400 | 载荷非法 | `{"ok":false,"error":"invalid_payload"}` |
| 401 | 签名/时间戳失败 | `{"ok":false,"error":"invalid_signature"}` |
| 404 | run_id 不存在 | `{"ok":false,"error":"run_not_found"}` |
| 409 | 状态迁移非法 | `{"ok":false,"error":"state_conflict"}` |
| 429 | 限流 | `{"ok":false,"error":"rate_limited","retry_after_ms":5000}` |
| 5xx | 内部错误 | `{"ok":false,"error":"internal_error"}` |

ACS 对非 2xx 会指数退避重试（1s/5s/30s/60s/120s，最多 5 次），CDC 侧每次入站记 `webhook_deliveries`。

## 5. 心跳载荷（run_processes 更新源）

```json
{
  "crawler_id": "proj_xxx", "process_id": "proc_abc123",
  "project_id": "p_123", "workspace_id": "ws_456",
  "mode": "run", "run_type": "cron", "cron": "*/30 * * * *",
  "pod_name": "acs-run-proj-xxx-0", "status": "alive",
  "pid": 12345, "started_at": ..., "uptime_ms": 3600000,
  "next_run_at": ..., "last_run": {...},
  "health": {"browser": true, "mongo": true, "llm": true, "disk_ok": true, "last_error": null},
  "version": "0.3.0"
}
```

- `status`：`alive | running | degraded | stopping`。
- CDC 记录 `last_heartbeat_at`；巡检线程按 `now - last_heartbeat_at > max(3×interval, 90s)` 判定 `unreachable`。
- 收到 `stopping` → 置 `stopped`。

## 6. 数据载荷（data_items 落库源）

```json
{
  "event": "data.saved",
  "delivery_id": "dlv_7a1b...",
  "timestamp": 1750000000000,
  "data": {
    "crawler_id": "proj_xxx", "project_id": "p_123", "workspace_id": "ws_456",
    "run_id": "run_abc123", "save_id": "sav_xyz789", "seq": 3,
    "kind": "content", "fmt": "json", "name": "content_ab12.json",
    "size": 2048, "content_hash": "sha256:9f2c...", "content_type": "application/json",
    "encoding": "utf-8", "content": "{...}", "storage": {"mode": "inline"},
    "source_url": "", "collected_at": 1750000000000
  }
}
```

- 幂等键 `(run_id, save_id)`；同 `content_hash` 可去重。
- 大文件：`storage.mode=presigned`，ACS 直传对象存储后 `commit`（本仓库预留接口，生产接入 MinIO/S3）。
- 返回：200 + `{"ok":true,"accepted":true,"save_id":...,"stored":true,"storage":{...}}`；
  413 超限 / 507 配额不足 / 429 限流。

## 7. 已知耦合点（ACS 侧配合）

| 耦合点 | 说明 |
| --- | --- |
| cron 每次运行需独立 `run_id` | ACS cron 长驻进程需为**每次**运行生成新的 `run_id`（规划 7.4），否则 CDC 侧 `runs` 状态机会对重复 run_id 返回 `state_conflict` |
| 心跳 `process_id` | ACS 自生成 `process_id` 与 CDC 下发 `RUN_ID` 不同，CDC 侧按 `process_id` 查不到时回退按 `crawler_id` 匹配 `run_processes`（已实现） |
| login 结束判定 | login 模式复用 ACS 既有 `set_login_ticket` + `LoginComplete` 编排，CDC 仅根据 `run.*` 事件更新状态 |