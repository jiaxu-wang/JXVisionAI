#!/usr/bin/env bash
# 在宿主机拉起 visionai-inferd。容器通过 ./run 挂载看到同一个套接字。
set -euo pipefail
cd "$(dirname "$0")/.."
ROOT="$(pwd)"
mkdir -p "$ROOT/run" "$ROOT/logs"
SOCK="$ROOT/run/visionai-inferd.sock"
BIN=""
for c in native/inferd/build-user/visionai-inferd native/inferd/build/visionai-inferd; do
  if [ -x "$c" ]; then BIN="$ROOT/$c"; break; fi
done
if [ -z "$BIN" ]; then
  echo "错误: 未找到 visionai-inferd。请先在 native/inferd 下 cmake 构建。" >&2
  exit 1
fi
if pgrep -f '[v]isionai-inferd' >/dev/null 2>&1; then
  exit 0
fi
echo "正在启动 visionai-inferd -> $SOCK"
# 随仓库打包的 ONNX Runtime 只有 CPU。
nohup "$BIN" --uds "$SOCK" --repo "$ROOT/models/repo" --device cpu \
  > "$ROOT/logs/inferd.log" 2>&1 &
sleep 0.5
if ! pgrep -f '[v]isionai-inferd' >/dev/null 2>&1; then
  echo "错误: visionai-inferd 没有留下来，见 logs/inferd.log" >&2
  exit 1
fi
