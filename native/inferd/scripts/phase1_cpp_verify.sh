#!/usr/bin/env bash
# Build + verify S2/S3/S4 for visionai-inferd (run as root or user with build tools).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../../.." && pwd)"
INFERD="$ROOT/native/inferd"
BUILD="$INFERD/build-user"
mkdir -p "$BUILD"
# prefer user build; fall back to build/
if [[ ! -x "$INFERD/build-user/visionai-inferd" && -x "$INFERD/build/visionai-inferd" ]]; then
  BUILD="$INFERD/build"
fi
SOCK="/tmp/visionai-inferd-phase1.sock"
REPO="$ROOT/models/repo"
IMG="$INFERD/testdata/sample.bgr"

cd "$ROOT"
"$INFERD/scripts/setup_ort.sh"

cmake -S "$INFERD" -B "$BUILD" -DCMAKE_BUILD_TYPE=Release
cmake --build "$BUILD" -j"$(nproc)"
BIN="$BUILD/visionai-inferd"

# Prepare a sample BGR from ultralytics / opencv if missing
mkdir -p "$INFERD/testdata"
if [[ ! -f "$IMG" ]]; then
  "$ROOT/env/bin/python" - <<PY
import urllib.request, cv2, numpy as np, pathlib
url = "https://ultralytics.com/images/bus.jpg"
p = pathlib.Path("$INFERD/testdata/bus.jpg")
try:
    urllib.request.urlretrieve(url, p)
    im = cv2.imread(str(p))
except Exception:
    im = np.zeros((480, 640, 3), np.uint8)
    cv2.rectangle(im, (100, 80), (280, 400), (0, 255, 0), -1)
bgr = pathlib.Path("$IMG")
bgr.write_bytes(im.tobytes())
bgr.with_suffix(".bgr.meta").write_text(f"{im.shape[1]} {im.shape[0]}\n")
# also write .meta expected by check-infer: sample.bgr.meta
pathlib.Path("$IMG.meta").write_text(f"{im.shape[1]} {im.shape[0]}\n")
print("wrote", bgr, im.shape)
PY
fi

rm -f "$SOCK"
"$BIN" --uds "$SOCK" --repo "$REPO" --device cpu &
PID=$!
cleanup() {
  kill -TERM "$PID" >/dev/null 2>&1 || true
  for _ in $(seq 1 50); do kill -0 "$PID" 2>/dev/null || break; sleep 0.1; done
  kill -KILL "$PID" >/dev/null 2>&1 || true
  wait "$PID" 2>/dev/null || true
  rm -f "$SOCK"
}
trap cleanup EXIT

for i in $(seq 1 100); do [[ -S "$SOCK" ]] && break; sleep 0.1; done
[[ -S "$SOCK" ]] || { echo "UDS missing"; exit 1; }

"$BIN" --check-live "$SOCK"
"$BIN" --check-s2 "$SOCK"
"$BIN" --check-infer "$IMG" --uds "$SOCK"
echo "PHASE1 C++ S2-S4 PASSED"
