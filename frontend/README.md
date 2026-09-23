# CrawlerDataCenter 前端控制台

基于 **React 19 + Vite + Ant Design 6 + TypeScript** 的 CDC（爬虫数据中心控制面）管理后台。

## 功能

- 认证：登录 / 注册 / 自动刷新 token / 登出（JWT + axios 拦截器自动续期）
- 总览：服务健康状态、我的工作空间
- 工作空间：列表 / 创建 / 编辑 / 删除，成员邀请与移除
- 爬虫项目：创建 / 编辑 / 删除，运行管理、开发容器、数据浏览、login 实时画面
- 运行：触发一次 / 定时运行、定时进程状态、运行详情
- 数据：按 run 过滤、下载数据正文
- 审计日志：敏感操作留痕

## 快速开始

```bash
cd frontend
npm install
npm run dev        # http://localhost:5173
```

开发服务器已配置代理，`/api` 与 `/healthz` 转发到 `http://localhost:8080`
（后端 `uv run uvicorn backend.main:app --port 8080`）。如后端不在 8080，可设置环境变量：

```bash
VITE_API_TARGET=http://localhost:9000 npm run dev
```

## 构建

```bash
npm run build      # tsc 类型检查 + vite 构建，产物在 dist/
npm run lint       # oxlint
npm run preview    # 预览构建产物
```

## 目录结构

```
src/
  api/          # axios 客户端(自动刷新) + 各资源 API + 类型
  stores/       # zustand: 认证 / 全局状态
  components/   # 布局、路由守卫
  pages/
    auth/       # 登录 / 注册
    workspaces/ # 工作空间列表、详情(项目+成员)
    projects/   # 项目详情(运行/开发容器/数据/login)
    runs/       # 运行详情
    audit/      # 审计日志
  utils/        # 时间/大小格式化、下载辅助
```

## 环境说明

- 后端 `CORS` 已放开 `*`，可直接跨域访问；同域部署时走 Vite 代理即可。
- login 实时画面走只读 WebSocket 代理（短时效令牌），帧流只读展示，不注入任何输入。