#!/usr/bin/env bash
# Celery worker 启动脚本。
#
# 用途: 承载开发容器异步拉起等任务(backend/tasks/dev_container_tasks.py)。
#       页面点击"拉起/刷新容器" -> API 投递任务 -> 本 worker 消费并调用
#       DevContainerService.launch 拉起 Pod(开发模式下跳过 Pod, 仅置本地上游)。
#
# 用法:
#   ./scripts/celery.sh                        # 前台启动 worker(loglevel=info)
#   ./scripts/celery.sh --loglevel debug       # 调整日志级别
#   ./scripts/celery.sh --concurrency 4        # 进程数(默认 4, 可用 CELERY_CONCURRENCY 覆盖)
#   ./scripts/celery.sh --queues cdc           # 只消费指定队列
#   ./scripts/celery.sh --beat                 # 同时启动定时调度(当前无定时任务, 预留)
#   ./scripts/celery.sh --kill                 # 只杀掉已有 worker, 不启动
#   ./scripts/celery.sh --no-kill              # 启动前不杀旧 worker(端口/进程冲突自负)
#   ./scripts/celery.sh --help                 # 查看用法
#
# 环境变量(可写入 .env, 由 backend.config 读取):
#   REDIS_URL / CELERY_BROKER_URL / CELERY_RESULT_BACKEND   队列与结果后端
#   DEV_CONTAINER_MODE=auto|k8s|local                        拉起策略
#   例: DEV_CONTAINER_MODE=k8s ./scripts/celery.sh            # 本地联调 K8s 拉起
#
# 说明:
#   - broker/result 默认复用 REDIS_URL; 启动前请确保 Redis 可达。
#   - Ctrl-C 结束前台 worker; --beat 时两个进程一起结束。

set -euo pipefail

cd "$(dirname "$0")/.."

CELERY_APP="${CELERY_APP:-backend.tasks.celery_app:celery_app}"
LOGLEVEL="${LOGLEVEL:-info}"
CONCURRENCY="${CONCURRENCY:-${CELERY_CONCURRENCY:-4}}"
QUEUES="${QUEUES:-}"
BEAT=0
KILL_ONLY=0
KILL_EXISTING=1
EXTRA_ARGS=()

usage() {
  sed -n '2,25p' "$0"
  exit 0
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --loglevel) LOGLEVEL="$2"; shift ;;
    --concurrency|-c) CONCURRENCY="$2"; shift ;;
    --queues|-Q) QUEUES="$2"; shift ;;
    --beat) BEAT=1 ;;
    --kill) KILL_ONLY=1 ;;
    --no-kill) KILL_EXISTING=0 ;;
    -h|--help) usage ;;
    --) shift; EXTRA_ARGS+=("$@"); break ;;
    *) echo "未知参数: $1"; usage ;;
  esac
  shift
done

if ! command -v uv >/dev/null 2>&1; then
  echo "[error] 未找到 uv, 请先安装: https://docs.astral.sh/uv/" >&2
  exit 1
fi

# 匹配本仓库的 celery worker/beat 进程(避免误杀其他项目)
worker_pids() {
  pgrep -f "celery.*-A ${CELERY_APP//\//\\/}" 2>/dev/null || true
}

kill_workers() {
  local pids
  pids="$(worker_pids)"
  if [[ -z "$pids" ]]; then
    echo "  [kill] 无运行中的 celery 进程"
    return 0
  fi
  echo "  [kill] 结束 celery 进程: $(echo "$pids" | tr '\n' ' ')"
  for pid in $pids; do
    kill "$pid" 2>/dev/null || true
  done
  for _ in $(seq 1 10); do
    [[ -z "$(worker_pids)" ]] && return 0
    sleep 0.5
  done
  pids="$(worker_pids)"
  if [[ -n "$pids" ]]; then
    echo "  [warn] 强制结束: $(echo "$pids" | tr '\n' ' ')"
    for pid in $pids; do
      kill -9 "$pid" 2>/dev/null || true
    done
  fi
}

if [[ "$KILL_ONLY" -eq 1 ]]; then
  echo "==> 清理模式: 结束已有 celery 进程"
  kill_workers
  echo "==> 清理完成"
  exit 0
fi

if [[ "$KILL_EXISTING" -eq 1 ]]; then
  echo "==> 清理已有 celery 进程"
  kill_workers
fi

echo "==> 工作目录: $PWD"
echo "==> Celery App: $CELERY_APP | loglevel: $LOGLEVEL"
echo "==> DEV_CONTAINER_MODE: ${DEV_CONTAINER_MODE:-auto} | REDIS_URL: ${REDIS_URL:-<.env>}"

WORKER_CMD=(uv run celery -A "$CELERY_APP" worker --loglevel "$LOGLEVEL" --without-gossip --without-mingle)
if [[ -n "$CONCURRENCY" ]]; then
  WORKER_CMD+=(-c "$CONCURRENCY")
fi
if [[ -n "$QUEUES" ]]; then
  WORKER_CMD+=(-Q "$QUEUES")
fi
if [[ ${#EXTRA_ARGS[@]} -gt 0 ]]; then
  WORKER_CMD+=("${EXTRA_ARGS[@]}")
fi

PIDS=()
cleanup() {
  echo ""
  echo "==> 收到退出信号, 停止 celery..."
  for pid in "${PIDS[@]}"; do
    kill "$pid" 2>/dev/null || true
  done
  wait 2>/dev/null || true
  echo "==> 已退出"
}
trap cleanup INT TERM EXIT

echo "==> 启动 worker: ${WORKER_CMD[*]}"
"${WORKER_CMD[@]}" &
PIDS+=($!)

if [[ "$BEAT" -eq 1 ]]; then
  BEAT_CMD=(uv run celery -A "$CELERY_APP" beat --loglevel "$LOGLEVEL")
  echo "==> 启动 beat: ${BEAT_CMD[*]}"
  "${BEAT_CMD[@]}" &
  PIDS+=($!)
fi

echo "==> Celery 已启动, 按 Ctrl-C 停止"
wait
