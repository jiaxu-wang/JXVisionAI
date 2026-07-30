#!/usr/bin/env bash
# Build visionai-inferd inside Docker (Ubuntu 24.04 + system gRPC).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../../.." && pwd)"
INFERD="$ROOT/native/inferd"
IMAGE="${VISIONAI_INFERD_IMAGE:-visionai-inferd-build:24.04}"
BUILD_DIR="${INFERD}/build-docker"

mkdir -p "$BUILD_DIR"

echo "[inferd] building image $IMAGE ..."
docker build -t "$IMAGE" -f "$INFERD/Dockerfile" "$INFERD"

echo "[inferd] cmake + build ..."
docker run --rm \
  -v "$ROOT:/src:rw" \
  -w /src/native/inferd \
  "$IMAGE" \
  bash -lc '
    set -euo pipefail
    cmake -S . -B build-docker -DCMAKE_BUILD_TYPE=Release
    cmake --build build-docker -j"$(nproc)"
  '

BIN="$BUILD_DIR/visionai-inferd"
if [[ ! -x "$BIN" ]]; then
  echo "ERROR: binary not found: $BIN" >&2
  exit 1
fi

echo "[inferd] OK: $BIN"
"$BIN" --version || true
