#!/usr/bin/env bash
# Prepare third_party/onnxruntime: headers (apt deb) + self-contained .so (Python wheel).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../../.." && pwd)"
TP="$ROOT/native/inferd/third_party/onnxruntime"
PY_SO="$ROOT/env/lib/python3.14/site-packages/onnxruntime/capi/libonnxruntime.so.1.28.0"
if [[ ! -f "$PY_SO" ]]; then
  PY_SO="$(find "$ROOT/env" -name 'libonnxruntime.so.*' | head -1 || true)"
fi
[[ -n "${PY_SO:-}" && -f "$PY_SO" ]] || { echo "Python onnxruntime .so not found"; exit 1; }

mkdir -p "$TP/include" "$TP/lib"
TMP="$(mktemp -d)"
cleanup() { rm -rf "$TMP"; }
trap cleanup EXIT

cd "$TMP"
apt-get download libonnxruntime-dev >/dev/null
dpkg-deb -x libonnxruntime-dev*.deb .
cp -a usr/include/onnxruntime/. "$TP/include/"
cp -a "$PY_SO" "$TP/lib/libonnxruntime.so.1.28.0"
ln -sfn libonnxruntime.so.1.28.0 "$TP/lib/libonnxruntime.so"
ln -sfn libonnxruntime.so.1.28.0 "$TP/lib/libonnxruntime.so.1"
echo "ORT ready under $TP"
