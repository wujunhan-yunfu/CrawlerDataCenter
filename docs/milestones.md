# 里程碑与测试策略

## 1. 里程碑

| 阶段 | 内容 | 交付 |
| --- | --- | --- |
| M0 基础 | 脚手架、配置、PostgreSQL 连接、Redis 客户端、用户系统、JWT | 可注册登录 |
| M1 权限与空间 | RBAC（角色/权限/绑定）、工作空间、成员管理 | 权限可用 |
| M2 项目 | 爬虫项目 CRUD、来源选择、`crawler_id` 分配 | 项目可用 |
| M3 开发容器 | K8s 编排（Pod/Service/Ingress）、loading 状态机、就绪探针轮询、空闲回收 | 可进入开发容器 |
| M4 login 模式 | login 触发 + 只读实时画面 WebSocket 代理 + 短时令牌 | 登录可完成（含人工扫码） |
| M5 run 模式 | run 触发（once/cron）、webhook 接收与幂等、**cron 心跳与存活/健康检测**、**data.saved 数据入库（含预签名直传）** | 定时运行 + 回调 + 数据入库 + 进程可观测 |
| M6 结果与数据 | 运行记录/结果、数据浏览与下载、webhook 投递记录、审计查询 | 数据可查 |
| M7 内置爬取器 | builtin 来源接入（预留接口落地） | 内置爬取可用 |
| M8 加固 | 配额、限流、告警、密钥管理、压测、生产化 | 生产就绪 |

**建议顺序**：M0–M3（打通开发容器闭环）→ M4/M5（运行模式）→ M6–M8。

## 2. 本仓库实现进度对照

| 模块 | 状态 |
| --- | --- |
| M0（配置/DB/Redis/认证） | ✅ 已实现 |
| M1（RBAC/工作空间/成员） | ✅ 已实现 |
| M2（项目） | ✅ 已实现 |
| M3（开发容器状态机 + FakeKubeClient） | ✅ 已实现（生产 K8s 客户端接口预留） |
| M4（login 触发 + live 令牌 + WS 代理占位） | ✅ 已实现（WS 代理经 KubeClient 转发接口） |
| M5（run 触发 + webhook 接收 + 心跳 + data 入库 + 调度） | ✅ 已实现 |
| M6（记录/数据/审计查询） | ✅ 已实现 |
| M7（builtin） | ⏳ 预留接口（`source_type=builtin` 模型已支持） |
| M8（加固） | ⏳ 部分（限流/锁/软删除已实现） |

## 3. 测试策略

- **单元测试**：认证/RBAC/状态机/webhook 签名与幂等/数据入库/调度计算/心跳判定。
- **存储**：PostgreSQL 用 aiosqlite（内存）跑逻辑测试；Redis 用 fakeredis。
- **容器编排**：注入 `FakeKubeClient`，验证 phase 状态机与回收逻辑，不依赖真实集群。
- **覆盖率**：`pyproject.toml` 配置 `[tool.coverage.run]`，目标 ≥ 85%。
- **端到端（后续）**：docker-compose 起 PG+Redis，本地跑 api/worker，mock ACS 发送 webhook 验证往返。

## 4. 运行命令

```bash
uv sync                              # 安装依赖
cp .env.example .env                 # 配置 DATABASE_URL / REDIS_URL / JWT_SECRET
uv run alembic upgrade head          # 建表 + 种子角色
uv run uvicorn backend.main:app --port 8080     # API
uv run python -m backend.worker                 # worker（webhook 重试/调度/审计）
uv run python -m backend.worker --monitor       # monitor（心跳巡检/容器回收）
uv run pytest --cov=backend --cov-report=term   # 测试 + 覆盖率
```

> 无 Docker 环境时，可用 `aiosqlite` 跑测试（conftest 自动切换），生产使用 PostgreSQL。