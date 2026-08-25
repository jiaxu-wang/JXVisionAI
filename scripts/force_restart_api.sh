#!/bin/sh
# docker compose restart 有时杀不掉卡住的 api 进程；用 kill + up 强制拉起
set -e
cd "$(dirname "$0")/.."
echo "Force restart visionai-api..."
docker compose kill visionai-api || true
# 清掉可能卡住的旧字节码（容器内 root 写的 __pycache__）
find ./visionai -type d -name '__pycache__' -exec rm -rf {} + 2>/dev/null || true
docker compose up -d visionai-api
echo "Waiting for health..."
i=0
while [ "$i" -lt 60 ]; do
  if curl -fsS "http://127.0.0.1:15000/healthz" >/dev/null 2>&1; then
    code=$(curl -sS -o /dev/null -w '%{http_code}' "http://127.0.0.1:15000/api/gb28181/preview-channel-id" || true)
    echo "healthz ok; preview-channel-id HTTP $code (302=需登录且路由已加载, 404=仍是旧进程)"
    exit 0
  fi
  i=$((i + 1))
  sleep 1
done
echo "visionai-api healthz timeout" >&2
exit 1
