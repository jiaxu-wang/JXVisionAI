#!/bin/bash

echo "========================================="
echo "          JXVisionAI 停止脚本"
echo "========================================="

# 模式不能以 - 开头，否则 pgrep/pkill 会把 -m 当成选项
_kill_mod() {
  local pat="[p]ython.* -m $1( |$)"
  local pids
  pids="$(pgrep -f "$pat" 2>/dev/null || true)"
  if [ -n "$pids" ]; then
    # shellcheck disable=SC2086
    kill $pids 2>/dev/null || true
  fi
}

echo "正在停止 API / worker / alert_worker / sip / inferd..."
_kill_mod 'visionai.api'
_kill_mod 'visionai.worker'
_kill_mod 'visionai.workers.alert_worker'
_kill_mod 'visionai.sip'
_kill_mod 'visionai'
_kill_mod 'jxvisionai'
pkill -f '[v]isionai-inferd' 2>/dev/null || true

sleep 2

_kill_mod 'visionai.api'
_kill_mod 'visionai.worker'
_kill_mod 'visionai.workers.alert_worker'
_kill_mod 'visionai.sip'
_kill_mod 'visionai'
pkill -f '[v]isionai-inferd' 2>/dev/null || true

for pat in '[p]ython.* -m visionai' '[v]isionai-inferd'; do
  pids="$(pgrep -f "$pat" 2>/dev/null || true)"
  if [ -n "$pids" ]; then
    # shellcheck disable=SC2086
    kill -9 $pids 2>/dev/null || true
  fi
done

echo "✅ 已发送停止信号"
echo "========================================="
