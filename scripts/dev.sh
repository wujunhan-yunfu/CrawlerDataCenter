#!/usr/bin/env bash
# 快捷启动脚本: 同时运行 CDC 后端(uvicorn) 与前端(Vite)。
#
# 用法:
#   ./scripts/dev.sh                       # 启动后端 + 前端(先杀掉占用端口的旧进程)
#   ./scripts/dev.sh --no-frontend         # 仅后端
#   ./scripts/dev.sh --no-backend          # 仅前端
#   ./scripts/dev.sh --setup               # 先拉起基础设施 + 建库 + 迁移, 再启动
#   ./scripts/dev.sh --backend-port 9000 --frontend-port 5174
#   ./scripts/dev.sh --kill                # 只杀掉占用端口的所有进程, 不启动
#   ./scripts/dev.sh --no-kill             # 启动前不杀旧进程(端口被占会启动失败)
#
# 说明:
#   - 启动前默认会杀掉占用 BACKEND_PORT / FRONTEND_PORT 的旧进程(含残留的 uvicorn/vite)。
#   - 前端已配置 /api 代理, 默认转发到 http://localhost:8080(后端端口);
#     若用 --backend-port 改了后端端口, 请保持前端 VITE_API_TARGET 同步。
#   - Ctrl-C 会同时结束两个进程。

set -euo pipefail

cd "$(dirname "$0")/.."

BACKEND_PORT="${BACKEND_PORT:-8080}"
FRONTEND_PORT="${FRONTEND_PORT:-5173}"
RUN_BACKEND=1
RUN_FRONTEND=1
DO_SETUP=0
INFRA=1
KILL_ONLY=0
KILL_EXISTING=1

usage() {
  sed -n '2,21p' "$0"
  exit 0
}

# 找出占用指定 TCP 端口的进程 PID(多行输出), 无则输出空
port_pids() {
  local port="$1"
  if command -v python3 >/dev/null 2>&1; then
    # 解析 /proc/net/tcp 找 LISTEN 的 inode, 再通过 /proc/[pid]/fd 反查进程
    python3 -c '
import os, sys, glob

def get_pids_for_port(port):
    hex_port = f"{port:04X}"
    inodes = set()
    for fn in ("/proc/net/tcp", "/proc/net/tcp6"):
        try:
            with open(fn) as f:
                f.readline()
                for line in f:
                    p = line.split()
                    if len(p) < 10 or p[3] != "0A":
                        continue
                    if p[1].rsplit(":", 1)[1] == hex_port:
                        inodes.add(p[9])
        except FileNotFoundError:
            continue
    if not inodes:
        return []
    pids = []
    for fd in glob.glob("/proc/[0-9]*/fd/*"):
        try:
            t = os.readlink(fd)
        except OSError:
            continue
        if t.startswith("socket:[") and t[8:-1] in inodes:
            pids.append(int(fd.split("/")[2]))
    return sorted(set(pids))

for pid in get_pids_for_port(int(sys.argv[1])):
    print(pid)
' "$port" 2>/dev/null || true
  elif command -v lsof >/dev/null 2>&1; then
    lsof -t -iTCP:"$port" -sTCP:LISTEN 2>/dev/null || true
  elif command -v fuser >/dev/null 2>&1; then
    fuser "$port"/tcp 2>/dev/null || true
  else
    ss -ltnp 2>/dev/null | grep ":$port " | grep -oE 'pid=[0-9]+' | cut -d= -f2 || true
  fi
}

# 杀死占用指定端口的进程, 并等待端口释放
kill_port() {
  local port="$1"
  local pids
  pids="$(port_pids "$port")"
  if [[ -z "$pids" ]]; then
    echo "  [kill] 端口 $port 无占用"
    return 0
  fi
  echo "  [kill] 端口 $port 占用进程: $(echo "$pids" | tr '\n' ' ')"
  for pid in $pids; do
    kill "$pid" 2>/dev/null || kill -9 "$pid" 2>/dev/null || true
  done
  # 等待端口释放(最多 5 秒)
  for _ in $(seq 1 10); do
    if [[ -z "$(port_pids "$port")" ]]; then
      return 0
    fi
    sleep 0.5
  done
  echo "  [warn] 端口 $port 仍有进程占用: $(port_pids "$port" | tr '\n' ' ')"
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --no-backend) RUN_BACKEND=0 ;;
    --no-frontend) RUN_FRONTEND=0 ;;
    --setup) DO_SETUP=1 ;;
    --no-infra) INFRA=0 ;;
    --kill) KILL_ONLY=1 ;;
    --no-kill) KILL_EXISTING=0 ;;
    --backend-port) BACKEND_PORT="$2"; shift ;;
    --frontend-port) FRONTEND_PORT="$2"; shift ;;
    -h|--help) usage ;;
    *) echo "未知参数: $1"; usage ;;
  esac
  shift
done

if [[ "$RUN_BACKEND" -eq 0 && "$RUN_FRONTEND" -eq 0 && "$KILL_ONLY" -eq 0 ]]; then
  echo "[error] --no-backend 与 --no-frontend 不能同时使用"
  exit 1
fi

echo "==> 工作目录: $PWD"
echo "==> 后端端口: $BACKEND_PORT | 前端端口: $FRONTEND_PORT"

# 仅清理模式: 杀掉占用端口的进程后退出
if [[ "$KILL_ONLY" -eq 1 ]]; then
  echo "==> 清理模式: 杀掉占用后端/前端端口的旧进程"
  kill_port "$BACKEND_PORT"
  kill_port "$FRONTEND_PORT"
  echo "==> 清理完成"
  exit 0
fi

# 启动前默认清理端口上的旧进程
if [[ "$KILL_EXISTING" -eq 1 ]]; then
  if [[ "$RUN_BACKEND" -eq 1 ]]; then
    echo "==> 清理后端端口 $BACKEND_PORT"
    kill_port "$BACKEND_PORT"
  fi
  if [[ "$RUN_FRONTEND" -eq 1 ]]; then
    echo "==> 清理前端端口 $FRONTEND_PORT"
    kill_port "$FRONTEND_PORT"
  fi
fi

# 基础设施(可选): PG + Redis
if [[ "$INFRA" -eq 1 && "$DO_SETUP" -eq 1 ]]; then
  echo "==> [1/3] 拉起基础设施 (docker compose up -d)"
  docker compose up -d || { echo "[warn] docker compose 启动失败, 继续尝试"; }

  echo "==> [2/3] 创建数据库 + 迁移建表"
  uv run python scripts/create_db.py
  uv run alembic upgrade head

  echo "==> [3/3] 基础设施就绪"
fi

PIDS=()
cleanup() {
  echo ""
  echo "==> 收到退出信号, 停止所有进程..."
  for pid in "${PIDS[@]}"; do
    kill "$pid" 2>/dev/null || true
  done
  wait 2>/dev/null || true
  echo "==> 已退出"
}
trap cleanup INT TERM EXIT

if [[ "$RUN_BACKEND" -eq 1 ]]; then
  echo "==> 启动后端: uv run uvicorn backend.main:app --port $BACKEND_PORT --reload"
  uv run uvicorn backend.main:app --host 0.0.0.0 --port "$BACKEND_PORT" --reload &
  PIDS+=($!)
fi

if [[ "$RUN_FRONTEND" -eq 1 ]]; then
  if [[ ! -d frontend/node_modules ]]; then
    echo "==> 首次运行, 安装前端依赖 (npm install)"
    (cd frontend && npm install)
  fi
  echo "==> 启动前端: VITE_API_TARGET=http://localhost:$BACKEND_PORT npm run dev"
  (cd frontend && VITE_API_TARGET="http://localhost:$BACKEND_PORT" npm run dev -- --port "$FRONTEND_PORT") &
  PIDS+=($!)
fi

echo "==> 全部启动完成, 按 Ctrl-C 停止"
wait