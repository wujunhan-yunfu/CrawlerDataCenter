# K8s 开发容器编排 + login 实时画面代理

## 1. 编排模型

- 每个 `custom` 项目对应一个 `dev_containers` 行，`project_id` 唯一 → **同项目最多一个 dev Pod**（scale-to-zero）。
- login / run 为短生命周期 Pod，由调度/触发服务按需创建，不常驻。
- K8s 交互收敛在 `backend/k8s/`，暴露 `KubeClient` 接口（`create_pod / get_pod / delete_pod / create_service / delete_service / create_ingress / delete_ingress / wait_ready`），
  测试注入 `FakeKubeClient`，生产使用 `kubernetes` 客户端。

## 2. 触发流程（loading 页）

开发容器拉起为**异步任务**：API 只投递任务，前端轮询任务状态，避免长请求占用连接。

```
POST /api/v1/projects/{id}/dev-container
  → 校验权限(container:manage) + source_type=custom
  → 已 ready → 直接返回 dev_url（刷新 last_active_at）
  → 否则投递 Celery 任务 cdc.dev_container.ensure(project_id)
       → 集群模式: 创建/复用 Pod：env {CRAWLER_ID, MODE=dev, MONGO_URI, LLM_*}
          → 阻塞轮询就绪/超时，phase: absent → pending → starting → ready
       → 开发模式(settings.use_local_dev_container):
          任务内跳过 Pod 拉起，直接置 phase=ready
       → 返回 {task_id, status=pending}
GET /api/v1/projects/{id}/dev-container/tasks/{task_id}   （前端轮询 1–2s，总超时 120s）
  → 归一化状态 pending → running → success | failed | timeout
  → success 时返回 dev_url → 解除 loading
  → 超时 → status=timeout + error_code(START_TIMEOUT / IMAGE_PULL_FAILED / QUOTA_EXCEEDED)
GET /api/v1/projects/{id}/dev-container
  → 返回 dev_containers 当前快照（phase/dev_url/pod_name/error_code）
```

> **开发模式与集群模式的对外形态完全一致**：`dev_url = /dev/{workspace_id}/{project_id}`，
> 均经 CDC 反向代理访问；区别仅在代理上游 —— 开发模式指向本地 ACS(`ACS_LOCAL_URL`，
> 默认 `http://localhost:8000`)，集群模式指向 K8s Service(`DevContainerService.upstream_url`)。

- Celery 任务执行体：`backend/tasks/dev_container_tasks.py`（复用 `DevContainerService.launch` 状态机与探针）。
- 任务状态查询：`backend/services/dev_container_task.py`（结合 DB phase + Celery state + 超时归一化）。
- 启动 worker：`./scripts/celery.sh`（`--help` 查看参数；开发模式跳过 Pod，可不起 worker）。
- 开发模式与集群模式由 `DEV_CONTAINER_MODE` 控制：`auto`（environment=dev/local 用本地 ACS）/ `k8s` / `local`。
- monitor 循环兜底把 `pending/starting` 超过 `dev_container_timeout` 的容器置 `failed(START_TIMEOUT)`。

### 开发容器反向代理（HTTP）

`backend/routers/dev_proxy.py` 实现 `/dev/{workspace_id}/{project_id}/...` 的 HTTP 反向代理：

```
GET /dev/{ws}/{pid}/...               （新标签页无法带 Authorization 头）
  → 鉴权: ?token=<access_token>（兼容 Bearer 头），JWT 校验 + 黑名单 + container:manage 权限
  → 校验 dev_containers.phase == ready，刷新 last_active_at
  → 上游: DevContainerService.upstream_url(project, row)
       开发模式 -> ACS_LOCAL_URL（默认 http://localhost:8000）
       集群模式 -> http://{service}.{namespace}.svc.cluster.local:8080
  → 代理目标 path: 页面/静态资源保留访问前缀(ACS --web-prefix);
       API 面(/api/v1/..., 含 /api/v1/ws/...)去掉 /dev/{ws}/{pid}, 转发上游原生路径
       例: GET /dev/1/2/assets/app.js      -> {upstream}/dev/1/2/assets/app.js
           GET /dev/1/2/api/v1/data        -> {upstream}/api/v1/data
  → 透传 method/headers/body 并流式返回；token 不下发上游
  → 附 X-Forwarded-Prefix: /dev/{ws}/{pid}
```

**WebSocket 同前缀代理**：`/dev/{ws}/{pid}/api/v1/ws...`（及任意 `/dev/{ws}/{pid}/...`
升级请求）经 CDC 转发到上游原生 `/api/v1/ws...`（`http→ws` / `https→wss`），
鉴权同 HTTP（`?token=` / Cookie / Bearer），双向消息通过 `websockets` 桥接。

因此 ACS 需以相同的 web 前缀启动（`--web-prefix=/dev/{ws}/{pid}`），
使其生成的绝对/相对资源路径与访问地址一致，代理侧无需改写路径。
前端访问地址自动附加 `?token=<access_token>`；首次访问会种下 HttpOnly Cookie
`cdc_dev_token`（Path=`/dev/{ws}/{pid}`），页面内 **js/css 等子资源不再携带 query
token，靠该 Cookie 鉴权**（避免子资源 401）。代理也兼容标准 Bearer 头。
集群模式下若需公网直连，可由 Ingress/网关承载同一前缀并复用相同鉴权。

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