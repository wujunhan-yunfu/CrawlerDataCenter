# 爬虫数据中心（CDC）总体架构设计

> 本文基于 AgentCrawlerStudio（下称 **ACS**）的 [`docs/crawler-data-center-plan.md`](../AgentCrawlerStudio/docs/crawler-data-center-plan.md)
> 细化 CDC 控制面实现方案。相对原计划的关键差异：**元数据存储由 MongoDB 改为 PostgreSQL（SQLAlchemy 2.0 异步 ORM）**，
> **新增 Redis 作为中间件层（令牌存储/限流/分布式锁/任务队列/热状态缓存）**；ACS 侧的 webhook/心跳/数据推送协议原样保留，CDC 侧按新栈实现接收端。

## 1. 设计目标与原则

| 目标 | 说明 |
| --- | --- |
| 多租户 | 用户 → 工作空间 → 爬虫项目三级资源模型 |
| 强隔离 | `crawler_id` 与 CDC 项目一一对应，贯穿登录凭据/代码/会话 |
| 可观测 | 开发容器、定时进程、运行、数据、webhook 投递全链路可见 |
| 数据主权 | ACS 只负责采集，数据经 `data.saved` webhook 交由 CDC 落库/落对象存储 |
| 可运维 | K8s 探针 + CDC 心跳双层存活检测；webhook 幂等、签名、重试 |

## 2. 分层架构

```
┌──────────────────────────────────────────────────────────────────────────┐
│                          浏览器（CDC 前端 SPA）                             │
│  登录 | 工作空间 | 项目 | loading 页 | 运行记录 | 数据浏览 | 审计             │
└───────────────┬──────────────────────────────────────────────────────────┘
                │ HTTPS (CDC API, JWT) / WebSocket(login live 代理)
┌───────────────▼──────────────────────────────────────────────────────────┐
│                         CDC 控制面（本仓库，FastAPI）                      │
│  Auth/RBAC | Workspace | CrawlerProject | DevContainer Orchestrator      │
│  Scheduler(cron/once) | Webhook Receiver | Run/Result Store | Audit       │
│  ─────────────────────────────────────────────────────────────────────   │
│   PostgreSQL(元数据)   Redis(令牌/限流/锁/队列/热状态)                     │
└───────┬───────────────────────────┬───────────────────────┬──────────────┘
        │ K8s API                   │ 反向代理 / Ingress     │ webhook 出站(重试worker)
        ▼                           ▼                       ▼
┌──────────────────────────────────────────────────────────────────────────┐
│                         K8s 集群（数据面）                                  │
│  ACS Pod(MODE=dev)   ── Service ── 经 CDC 代理 ──► 用户访问开发容器          │
│  ACS Pod(MODE=login) ── 一次性，登录+保存凭据后退出                          │
│  ACS Pod(MODE=run)   ── 一次性/定时，运行并回调 CDC（MongoDB 共享凭据/代码） │
└──────────────────────────────────────────────────────────────────────────┘
```

## 3. 组件职责

| 组件 | 职责 |
| --- | --- |
| CDC API | 用户/权限/空间/项目元数据、开发容器编排、运行触发、webhook 接收、数据入库、审计 |
| PostgreSQL | **控制面事实源**：用户、RBAC、工作空间、项目、运行记录、数据索引、投递记录、审计 |
| MongoDB | **爬虫数据正文存储**：`data.saved` 的 content 落 `cdc.data_items` 集合，PG 只存索引与 `mongo://` 引用路径；同时承载 ACS 侧共享库（`login_tickets`/`code_commits`/`agent_*`，按 `crawler_id` 隔离） |
| Redis | 会话/刷新令牌存储、token 黑名单、限流计数、分布式锁（调度/回收）、任务队列（webhook 重试、数据提交）、开发容器/进程热状态缓存 |
| 后台任务 | 调度器（cron）、webhook 出站重试 worker、心跳失联巡检、容器空闲回收 |
| ACS Pod | 浏览器执行体，按 `MODE` 提供 IDE / login 画面 / run 回调 |

## 4. 关键设计决策

### 4.1 PostgreSQL vs MongoDB（相对原计划的变更）

| 维度 | 原计划(Mongo) | 本方案(PostgreSQL) |
| --- | --- | --- |
| 元数据 | 面向文档，灵活 | 关系化：用户/角色绑定/成员/配额需要强一致与外键约束 |
| 运行记录 | 单文档 | `runs` 主表 + `run_results`/`data_items`/`webhook_deliveries` 关联表，便于聚合统计 |
| 状态机 | 应用层约束 | DB CHECK 约束 + 应用层状态机双重保障 |
| 迁移 | 无 | Alembic 版本化迁移，生产可控 |
| 唯一约束 | 软实现 | PG 唯一索引（幂等键、`crawler_id`、`(run_id, save_id)` 等）硬保证 |

### 4.2 Redis 的使用场景

| 场景 | 用法 | 说明 |
| --- | --- | --- |
| Refresh Token | `SET refresh:uid:token -> jti EX 7d` | 可撤销的刷新令牌，登出即删 |
| Access Token 黑名单 | `SET blk:jti -> 1 EX <剩余TTL>` | 登出/改密后立即失效 |
| 限流 | `INCR rate:{scope}:{key}` + `EXPIRE` | 登录、webhook、登录画面令牌 |
| 分布式锁 | `SET lock:{key} -> nonce NX PX` | 调度执行、容器回收、`run_id` 生成互斥 |
| 任务队列 | Redis List `brpoplpush` 语义 | webhook 出站重试、大文件 commit、审计异步落盘 |
| 热状态缓存 | `SET devcontainer:{pid} -> json` | 开发容器 phase、进程心跳最近状态，避免频繁查库 |
| 登录画面短时令牌 | `SET loginlive:{token} -> {user,project,run}` | WebSocket 代理鉴权 |

### 4.3 状态机

**运行（runs.status）**：`pending → running → succeeded | failed | skipped`
**开发容器（dev_containers.phase）**：`absent → pending → starting → ready → stopping → absent`，`pending/starting → failed`
**定时进程（run_processes.status）**：`alive | running | degraded | stopping | stopped | unreachable`

状态迁移均在服务层统一校验，DB 层用 CHECK 约束兜底。

## 5. 技术栈

| 层 | 选型 |
| --- | --- |
| 框架 | FastAPI + uvicorn |
| ORM | SQLAlchemy 2.0（async，Declarative + `Mapped` 风格） |
| 数据库 | PostgreSQL 15+（asyncpg 驱动，控制面元数据） |
| 爬虫数据存储 | MongoDB（motor/pymongo async，`cdc.data_items` 集合） |
| 迁移 | Alembic（async engine） |
| 缓存/队列 | redis-py（async） |
| 异步任务 | Celery（Redis broker/backend，开发容器拉起等） |
| 认证 | PyJWT（HS256）+ bcrypt（密码哈希） |
| 校验 | Pydantic v2 |
| K8s | `kubernetes` 客户端 + 抽象接口（测试注入 fake） |
| 测试 | pytest + pytest-asyncio + aiosqlite + fakeredis |

## 6. 运行形态

| 进程 | 说明 |
| --- | --- |
| `api` | `uvicorn backend.main:app`，CDC 控制面 API + 代理 |
| `worker` | `python -m backend.worker`，消费 Redis 队列：审计等 |
| `monitor` | `python -m backend.worker --monitor`，心跳失联巡检 + 容器空闲回收（可由 worker 内子任务承担） |
| `celery` | `./scripts/celery.sh`（`celery -A backend.tasks.celery_app:celery_app worker`），开发容器异步拉起等异步任务 |

> 简化部署：`docker-compose up` 启动 PostgreSQL + Redis；`api`/`worker` 均可本地 `uv run` 启动。

## 7. 与 ACS 的对接面

| 对接 | 方向 | 协议 | CDC 实现 |
| --- | --- | --- | --- |
| 运行回调 | ACS → CDC | `POST /api/v1/webhooks/runs` | `routers/webhooks.py` + `services/webhook_receiver.py` |
| 定时心跳 | ACS → CDC | `POST /api/v1/webhooks/heartbeat` | `services/heartbeat.py` + `run_processes` 表 |
| 数据推送 | ACS → CDC | `POST /api/v1/webhooks/data` | `services/data_ingest.py` + `data_items` 表 |
| 大文件 | ACS → CDC | `POST /api/v1/webhooks/data/prepare|commit` | 预签名上传（S3/MinIO），预留 |
| 开发容器 | CDC → K8s | K8s API | `k8s/` 编排 + `/dev-container` 路由 |
| 开发容器访问 | 浏览器 ↔ ACS | HTTP 反向代理 | `routers/dev_proxy.py`（`/dev/{ws}/{pid}`，token 鉴权） |
| 画面代理 | CDC ↔ ACS | WebSocket | `routers/login_live.py` + `k8s/proxy.py` |

详见 `docs/webhook-protocol.md` 与 `docs/k8s-orchestration.md`。