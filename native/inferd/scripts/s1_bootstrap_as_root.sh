#!/usr/bin/env bash
# S1: install deps (host), build, verify Live.
# Run in an already-root shell (e.g. `sudo su`), from anywhere:
#   /home/wjx/code/python/JXVisionAI/native/inferd/scripts/s1_bootstrap_as_root.sh
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../../.." && pwd)"
INFERD="$ROOT/native/inferd"
BUILD="$INFERD/build"
SOCK="/tmp/visionai-inferd-s1-test.sock"

if [[ "$(id -u)" -ne 0 ]]; then
  echo "Please run as root (sudo su)." >&2
  exit 1
fi

export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq cmake build-essential pkg-config \
  protobuf-compiler libprotobuf-dev libgrpc++-dev protobuf-compiler-grpc

cmake -S "$INFERD" -B "$BUILD" -DCMAKE_BUILD_TYPE=Release
cmake --build "$BUILD" -j"$(nproc)"

BIN="$BUILD/visionai-inferd"
"$BIN" --version

rm -f "$SOCK"
"$BIN" --uds "$SOCK" &
PID=$!
cleanup() {
  if kill -0 "$PID" >/dev/null 2>&1; then
    kill -TERM "$PID" >/dev/null 2>&1 || true
    for _ in $(seq 1 50); do
      kill -0 "$PID" >/dev/null 2>&1 || break
      sleep 0.1
    done
    kill -KILL "$PID" >/dev/null 2>&1 || true
    wait "$PID" 2>/dev/null || true
  fi
  rm -f "$SOCK"
}
trap cleanup EXIT

for i in $(seq 1 50); do
  [[ -S "$SOCK" ]] && break
  sleep 0.1
done
[[ -S "$SOCK" ]] || { echo "UDS not created"; exit 1; }

"$BIN" --check-live "$SOCK"
echo "S1 Live verification PASSED"
