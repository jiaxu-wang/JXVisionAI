#!/usr/bin/env bash
# 下载 Ultralytics YOLO26 检测权重到 models/（n/s/m/l/x）。
# 官方 Release：https://github.com/ultralytics/assets/releases/tag/v8.4.0
# 文档：https://docs.ultralytics.com/models/yolo26/
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
mkdir -p models

# 直连 GitHub 慢时可改用镜像（默认走 gh-proxy）
ASSET_BASE="${YOLO26_ASSET_BASE:-https://gh-proxy.com/https://github.com/ultralytics/assets/releases/download/v8.4.0}"

# 默认下齐检测五档；可选：DOWNLOAD_POSE=1 再下姿态；MODELS="n s" 只下部分
MODELS="${MODELS:-n s m l x}"
DOWNLOAD_POSE="${DOWNLOAD_POSE:-0}"

download_one() {
  local name="$1"
  local out="models/${name}"
  if [[ -f "$out" && -s "$out" ]]; then
    echo "skip (exists): $out ($(du -h "$out" | awk '{print $1}'))"
    return 0
  fi
  echo "GET ${ASSET_BASE}/${name}"
  curl -fL --retry 5 --connect-timeout 30 -o "${out}.part" "${ASSET_BASE}/${name}"
  mv "${out}.part" "$out"
  ls -lh "$out"
}

for size in $MODELS; do
  download_one "yolo26${size}.pt"
  if [[ "$DOWNLOAD_POSE" == "1" ]]; then
    download_one "yolo26${size}-pose.pt"
  fi
done

echo
echo "Done. Switch in config.ini [models]:"
echo "  yolo_model = models/yolo26s.pt   # or yolo26n / m / l / x"
echo "Then: ./stop.sh && ./start.sh"
ls -lh models/yolo26*.pt 2>/dev/null || true
