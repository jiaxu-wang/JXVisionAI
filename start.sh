#!/bin/bash

echo "========================================="
echo "          JXVisionAI 启动脚本"
echo "========================================="

_visionai_api_pids() {
    ps -eo pid=,args= | awk '
      $2 == "python3" && $3 == "-m" && ($4 == "visionai.api" || $4 == "visionai") { print $1 }
    '
}
_visionai_worker_pids() {
    ps -eo pid=,args= | awk '
      $2 == "python3" && $3 == "-m" && ($4 == "visionai.worker" || $4 == "visionai.workers.alert_worker") { print $1 }
    '
}

if [ ! -d "env" ]; then
    echo "错误: 虚拟环境 'env' 不存在！"
    echo "请先执行: python3 -m venv env && ./env/bin/pip install -r requirements.txt"
    exit 1
fi

if [ -n "$(_visionai_api_pids)$(_visionai_worker_pids)" ]; then
    echo "警告: JXVisionAI 相关进程已在运行！请先 ./stop.sh"
    exit 1
fi

echo "正在启动 JXVisionAI 服务..."
source env/bin/activate

if [ "${FORCE_PIP_INSTALL:-0}" = "1" ]; then
    echo "正在同步 Python 依赖（FORCE_PIP_INSTALL=1）..."
    if ! pip install -q -r requirements.txt; then
        echo "错误: pip install 失败"
        exit 1
    fi
fi

export REDIS_HOST="${REDIS_HOST:-127.0.0.1}"
export REDIS_PORT="${REDIS_PORT:-16379}"
export SAVE_DIR="${SAVE_DIR:-./snapshots}"
export LOG_DIR="${LOG_DIR:-./logs}"
_PROXY_BYPASS="127.0.0.1,localhost,::1,10.0.0.0/8,172.16.0.0/12,192.168.0.0/16"
if [ -n "${NO_PROXY:-}" ]; then
    export NO_PROXY="$NO_PROXY,$_PROXY_BYPASS"
else
    export NO_PROXY="$_PROXY_BYPASS"
fi
export no_proxy="$NO_PROXY"
export S3_ENDPOINT_URL="${S3_ENDPOINT_URL:-http://127.0.0.1:9000}"
export OBJECT_STORAGE_ENABLED="${OBJECT_STORAGE_ENABLED:-true}"

mkdir -p "$LOG_DIR" ./logs ./snapshots

# 可选拉起 compose 依赖（redis/minio/zlm）
if [ "${START_COMPOSE_DEPS:-1}" = "1" ] && command -v docker >/dev/null 2>&1; then
  if [ -f docker-compose.yaml ] || [ -f docker-compose.yml ]; then
    echo "确保 Redis/MinIO/ZLM 容器运行（START_COMPOSE_DEPS=1）..."
    docker compose up -d redis minio zlmediakit 2>/dev/null || docker-compose up -d redis minio zlmediakit 2>/dev/null || true
  fi
fi

_INFER_BACKEND="$(
  PYTHONPATH="${PYTHONPATH:+$PYTHONPATH:}$PWD/.pip_target" \
  ./env/bin/python -c "from visionai.config.settings import INFER_BACKEND; print(INFER_BACKEND)" 2>/dev/null || echo python
)"
_INFER_DEVICE="$(
  PYTHONPATH="${PYTHONPATH:+$PYTHONPATH:}$PWD/.pip_target" \
  ./env/bin/python -c "
from visionai.config.settings import INFER_DEVICE, INFERENCE_DEVICE
d=(INFER_DEVICE or INFERENCE_DEVICE or 'cpu').strip().lower()
print('cuda' if d in ('gpu','cuda','0') else 'cpu')
" 2>/dev/null || echo cpu
)"
_INFERD_BIN=""
for _c in native/inferd/build-user/visionai-inferd native/inferd/build/visionai-inferd; do
  if [ -x "$_c" ]; then _INFERD_BIN="$_c"; break; fi
done
if [ "$_INFER_BACKEND" = "cpp" ]; then
  if [ -z "$_INFERD_BIN" ]; then
    echo "错误: infer.backend=cpp 但未找到 visionai-inferd"
    exit 1
  fi
  if ! pgrep -f '[v]isionai-inferd' >/dev/null 2>&1; then
    echo "正在启动 visionai-inferd (device=$_INFER_DEVICE)..."
    _REPO="$(
      PYTHONPATH="${PYTHONPATH:+$PYTHONPATH:}$PWD/.pip_target" \
      ./env/bin/python -c "from visionai.config.settings import INFER_MODEL_REPOSITORY; print(INFER_MODEL_REPOSITORY)" 2>/dev/null || echo models/repo
    )"
    nohup "$_INFERD_BIN" --uds /tmp/visionai-inferd.sock --repo "$_REPO" --device "$_INFER_DEVICE" \
      > ./logs/inferd.log 2>&1 &
    sleep 1
  fi
fi

export PYTHONPATH="${PYTHONPATH:+$PYTHONPATH:}$PWD/.pip_target"
export WORKER_ID="${WORKER_ID:-$(hostname)-$$}"

echo "启动 alert_worker..."
nohup python3 -m visionai.workers.alert_worker > ./logs/alert_worker.log 2>&1 &
echo "启动 stream worker..."
nohup python3 -m visionai.worker > ./logs/worker.log 2>&1 &
echo "启动 API..."
nohup python3 -m visionai.api > ./logs/visionai.log 2>&1 &

sleep 2

if [ -n "$(_visionai_api_pids)" ]; then
    echo "✅ JXVisionAI 已启动（api + worker + alert_worker）"
    echo "📋 Web: http://0.0.0.0:5000"
    echo "🩺 healthz: http://127.0.0.1:5000/healthz"
    echo "📝 日志: ./logs/visionai.log ./logs/worker.log ./logs/alert_worker.log"
    echo "🔧 停止: ./stop.sh"
else
    echo "❌ API 启动失败，请查看 ./logs/visionai.log"
    exit 1
fi

echo "========================================="
