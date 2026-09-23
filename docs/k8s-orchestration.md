# K8s 开发容器编排 + login 实时画面代理

## 1. 编排模型

- 每个 `custom` 项目对应一个 `dev_containers` 行，`project_id` 唯一 → **同项目最多一个 dev Pod**（scale-to-zero）。
- login / run 为短生命周期 Pod，由调度/触发服务按需创建，不常驻。
- K8s 交互收敛在 `backend/k8s/`，暴露 `KubeClient` 接口（`create_pod / get_pod / delete_pod / create_service / delete_service / create_ingress / delete_ingress / wait_ready`），
  测试注入 `FakeKubeClient`，生产使用 `kubernetes` 客户端。

## 2. 触发流程（loading 页）

```
POST /api/v1/projects/{id}/dev-container
  → 校验权限(project:read + container:manage) + source_type=custom + crawler_id 存在
  → dev_containers.phase == ready → 直接返回 dev_url
  → 否则创建/复用 Pod：env {CRAWLER_ID, MODE=dev, MONGO_URI, LLM_*}
  → phase: absent → pending → starting → ready(探针 /healthz 通过)
GET /api/v1/projects/{id}/dev-container   （前端轮询 1–2s，总超时 120s）
  → phase == ready → 返回 dev_url → 解除 loading
  → 超时 → phase=failed + error_code(START_TIMEOUT / IMAGE_PULL_FAILED / QUOTA_EXCEEDED)
```

### Pod 规格（dev）

| 项 | 值 |
| --- | --- |
| image | `agentcrawlerstudio:<version>` |
| env | `MODE=dev, CRAWLER_ID=<project.crawler_id>, MONGO_URI, MONGO_DB=crawler, LLM_*, WEB_PORT=8080, API_PREFIX=/api/v1`；密钥走 `secretKeyRef` |
| resources | limits `{cpu:2, memory:2Gi}` / requests `{cpu:500m, memory:512Mi}` |
| readinessProbe | `httpGet: /healthz:8080`，initialDelaySeconds 5，periodSeconds 3 |
| security | 非 root、只读根文件系统、NetworkPolicy |

Service（ClusterIP）+ Ingress（子域或 `--web-prefix` 路径，经 CDC 反向代理鉴权后转发）。

## 3. login 模式内嵌实时画面

- login Pod 仅暴露 `WS /api/v1/stream`（ACS 只读画面流），不直接公网暴露。
- CDC 提供鉴权 WebSocket 代理：

```
GET /api/v1/projects/{id}/login/live?token=<short-lived>
  → 校验 token(Redis live:{token} → {user, project, run})
  → K8s port-forward / 反向代理 → Pod 的 /api/v1/stream
```

- 触发 login 返回 `{run_id, status, live_ws_url, expires_at}`；运行结束 CDC 主动关闭画面并回收令牌。
- 代理为**只读帧流**：不注入任何输入事件；Origin 校验 + 限流 + 审计。

## 4. 生命周期 / 回收

| 触发 | 动作 |
| --- | --- |
| 空闲 TTL（如 30min `last_active_at`） | scale-to-zero：`stopping → absent`，删 Pod/Service/Ingress |
| 空间并发容器配额 | 超限返回 `QUOTA_EXCEEDED` |
| 项目/空间删除 | 级联回收全部资源（软删除 + 异步硬清理） |
| `phase=failed` | 记录 `error_code`，前端可重试 |

回收任务由 worker 的 monitor 循环执行（Redis 分布式锁保证单实例）。