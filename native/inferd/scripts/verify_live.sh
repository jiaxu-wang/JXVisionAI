#!/usr/bin/env bash
# S1 gate: start inferd, call Live via --check-live, then stop.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../../.." && pwd)"
INFERD="$ROOT/native/inferd"
IMAGE="${VISIONAI_INFERD_IMAGE:-visionai-inferd-build:24.04}"
BUILD_DIR="${INFERD}/build-docker"
BIN_HOST="$BUILD_DIR/visionai-inferd"
SOCK_HOST="${VISIONAI_INFERD_SOCK:-/tmp/visionai-inferd-s1-test.sock}"
UDS_URI="unix://${SOCK_HOST}"

if [[ ! -x "$BIN_HOST" ]]; then
  echo "[inferd] binary missing; running build_docker.sh ..."
  "$INFERD/scripts/build_docker.sh"
fi

# Binary is linked against Ubuntu 24.04 libs inside the image — run checks in Docker.
rm -f "$SOCK_HOST"

echo "[inferd] starting server on $UDS_URI ..."
docker run --rm -d \
  --name visionai-inferd-s1-verify \
  -v "$ROOT:/src:ro" \
  -v /tmp:/tmp \
  -w /src/native/inferd \
  "$IMAGE" \
  /src/native/inferd/build-docker/visionai-inferd --uds "$SOCK_HOST" >/tmp/visionai-inferd-s1.log 2>&1 || true

# If name conflict from previous run
if ! docker ps --format '{{.Names}}' | grep -qx visionai-inferd-s1-verify; then
  docker rm -f visionai-inferd-s1-verify >/dev/null 2>&1 || true
  docker run --rm -d \
    --name visionai-inferd-s1-verify \
    -v "$ROOT:/src:ro" \
    -v /tmp:/tmp \
    -w /src/native/inferd \
    "$IMAGE" \
    /src/native/inferd/build-docker/visionai-inferd --uds "$SOCK_HOST"
fi

cleanup() {
  docker rm -f visionai-inferd-s1-verify >/dev/null 2>&1 || true
  rm -f "$SOCK_HOST"
}
trap cleanup EXIT

# Wait for socket
for i in $(seq 1 30); do
  if [[ -S "$SOCK_HOST" ]]; then
    break
  fi
  sleep 0.2
done
if [[ ! -S "$SOCK_HOST" ]]; then
  echo "ERROR: UDS not created: $SOCK_HOST" >&2
  docker logs visionai-inferd-s1-verify 2>&1 || true
  exit 1
fi

echo "[inferd] calling Live ..."
docker run --rm \
  -v "$ROOT:/src:ro" \
  -v /tmp:/tmp \
  "$IMAGE" \
  /src/native/inferd/build-docker/visionai-inferd --check-live "$SOCK_HOST"

echo "[inferd] S1 Live verification PASSED"
