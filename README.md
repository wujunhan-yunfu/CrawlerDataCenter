# CrawlerDataCenter（爬虫数据中心控制面）

基于 [AgentCrawlerStudio](https://github.com/your-org/AgentCrawlerStudio) 规划（`docs/crawler-data-center-plan.md`）实现的多租户
爬虫数据中心控制面。技术栈：**FastAPI + SQLAlchemy 2.0(async) + PostgreSQL + Redis + MongoDB + Celery**。

> 与规划文档的差异：控制面元数据由 MongoDB 改为 PostgreSQL；Redis 承担令牌/限流/锁/队列/热状态；
> **爬虫数据正文存 MongoDB**（`cdc.data_items`），PG 只存索引与引用路径。
> ACS 侧 webhook/心跳/数据推送协议原样保留，CDC 侧按本仓库实现接收端。

## 功能

- **认证**：注册/登录/刷新/登出，JWT(access+refresh)，bcrypt，Redis 撤销/黑名单，登录限流
- **RBAC**：角色→权限 + 用户→角色绑定（global / workspace / project 三级 scope），内置 6 个角色
- **工作空间**：资源与权限边界，成员邀请/移除，配额（预留）
- **爬虫项目**：`builtin` / `custom` 两种来源，`crawler_id` 自动分配（与 ACS 隔离键对齐）
- **开发容器**：Celery 异步任务 + K8s 编排（Pod/Service），phase 状态机 + 就绪探针轮询 + 任务状态轮询 + 空闲 TTL 回收 + 配额；`/dev/{ws}/{pid}` 反向代理（token 鉴权），开发模式跳过 Pod 拉起、仅上游指向本地 ACS(8000)
- **login 实时画面**：短时效令牌 + 只读 WebSocket 代理（不注入任何输入）
- **run 调度**：once（K8s Job）/ cron（K8s Deployment），运行记录
- **webhook 接收**：run/heartbeat/data 三类事件，HMAC 签名 + 时间戳防重放 + 幂等 + 状态机校验
- **数据入库**：`data.saved` 幂等落 `data_items`（正文存 MongoDB，PG 存索引，Mongo 不可达自动降级内联），支持查询与下载
- **定时进程可观测**：心跳存活/健康检测，失联标记 `unreachable` + 重启策略
- **审计**：敏感操作经 Redis 队列异步落库

## 快速开始

```bash
# 1. 依赖
uv sync --extra test

# 2. 基础设施(需 docker)或自行起 PG+Redis
docker compose up -d

# 3. 配置
cp .env.example .env   # 修改 DATABASE_URL / JWT_SECRET

# 4. 迁移建表 + 种子角色
uv run alembic upgrade head

# (可选)创建/重建数据库: 不存在则建, 存在则跳过; --recreate 存在时先删除再建
uv run python scripts/create_db.py
uv run python scripts/create_db.py --recreate

# (可选)创建超级管理员(默认 admin / 123456, 幂等)
uv run python scripts/create_admin.py
uv run python scripts/create_admin.py --on-exists reset   # 已存在则重置密码

# 5. 启动
uv run uvicorn backend.main:app --port 8080 --reload    # API
./scripts/celery.sh                                     # Celery(开发容器拉起; 开发模式可不起)
uv run python -m backend.worker                         # worker(审计队列)
uv run python -m backend.worker --monitor               # monitor(心跳巡检/容器回收)
```

无 Docker 时可用测试数据库跑测试（内存 sqlite + fakeredis）：

```bash
uv run pytest --cov=backend --cov-report=term
```

## 目录结构

```
backend/
  config.py          # pydantic-settings 配置
  main.py            # 应用工厂 create_app()
  core/              # ids / security(JWT+bcrypt+加密)
  db/models/         # SQLAlchemy 模型
  redis/client.py    # Redis 客户端/限流/锁/令牌/队列/热状态
  rbac/              # 权限点、内置角色、权限解析
  services/          # auth/workspace/project/dev_container(+task)/run/webhook_receiver/data_ingest/heartbeat/cron/audit
  k8s/               # KubeClient 抽象 + Pod/Service/Job/Deployment 模板
  routers/           # API 路由
  tasks/             # Celery 应用/任务 + 后台任务 worker
alembic/             # 数据库迁移
docs/                # 细化方案文档
```

## 文档

| 文档 | 内容 |
| --- | --- |
| `docs/architecture.md` | 总体架构、分层、Redis 用法、技术栈 |
| `docs/data-model.md` | PostgreSQL + Redis 数据模型与 Key 规划 |
| `docs/webhook-protocol.md` | ACS→CDC webhook/心跳/数据接收协议 |
| `docs/k8s-orchestration.md` | 开发容器编排 + login 实时画面代理 |
| `docs/scheduler-heartbeat-data.md` | 调度、心跳巡检、数据入库、API 概览 |
| `docs/milestones.md` | 里程碑与实现进度对照 |

## 安全要点

- 容器内不信任前端传入的 `crawler_id`，一律由 CDC 按项目推导下发
- 开发容器仅经 CDC 反向代理暴露；webhook 强制 HMAC 签名 + 时间戳 + 内网白名单（预留）
- 密钥走环境变量/K8s Secret，不落镜像
- 敏感字段加密预留（`field_encryption_key`）