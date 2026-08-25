#!/bin/bash
# 需能访问 docker.sock（root 或 docker 组成员）
set -euo pipefail
cd "$(dirname "$0")/.."

echo "== 停止宿主机直跑的 visionai 进程（避免抢端口）=="
./stop.sh 2>/dev/null || true
pkill -f '[p]ython3 -m visionai' 2>/dev/null || true
sleep 1

COMPOSE_ARGS=(-f docker-compose.yaml)

echo "== docker compose up -d --build =="
docker compose "${COMPOSE_ARGS[@]}" up -d --build

echo "== 等待 API healthz =="
for i in $(seq 1 90); do
  if curl -fsS http://127.0.0.1:15000/healthz >/dev/null 2>&1; then
    echo "API ready"
    break
  fi
  sleep 2
  if [ "$i" -eq 90 ]; then
    echo "API 未就绪，最近日志："
    docker compose "${COMPOSE_ARGS[@]}" logs --tail=100 visionai-api visionai-worker visionai-alert || true
    exit 1
  fi
done

docker compose "${COMPOSE_ARGS[@]}" ps
echo "Web:      http://127.0.0.1:15000"
echo "healthz:  http://127.0.0.1:15000/healthz"
echo "MinIO:    http://127.0.0.1:19001  (API :19000)"
echo "ZLM HTTP: http://127.0.0.1:18080  RTSP:18554 RTMP:11935 WebRTC:18000"
