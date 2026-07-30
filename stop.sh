#!/bin/bash

echo "========================================="
echo "          JXVisionAI 停止脚本"
echo "========================================="

_kill_pattern() {
  local pat="$1"
  local pids
  pids="$(pgrep -f "$pat" || true)"
  if [ -n "$pids" ]; then
    # shellcheck disable=SC2086
    kill $pids 2>/dev/null || true
  fi
}

echo "正在停止 API / worker / alert_worker / inferd..."
_kill_pattern '[p]ython3 -m visionai.api'
_kill_pattern '[p]ython3 -m visionai.worker'
_kill_pattern '[p]ython3 -m visionai.workers.alert_worker'
_kill_pattern '[p]ython3 -m visionai'
_kill_pattern '[p]ython3 -m jxvisionai'
_kill_pattern '[v]isionai-inferd'

sleep 2

_kill_pattern '[p]ython3 -m visionai.api'
_kill_pattern '[p]ython3 -m visionai.worker'
_kill_pattern '[p]ython3 -m visionai.workers.alert_worker'
_kill_pattern '[p]ython3 -m visionai'
_kill_pattern '[v]isionai-inferd'
# force
for pat in '[p]ython3 -m visionai' '[v]isionai-inferd'; do
  pids="$(pgrep -f "$pat" || true)"
  if [ -n "$pids" ]; then
    # shellcheck disable=SC2086
    kill -9 $pids 2>/dev/null || true
  fi
done

echo "✅ 已发送停止信号"
echo "========================================="
