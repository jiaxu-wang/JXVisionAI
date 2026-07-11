#!/bin/bash

echo "========================================="
echo "          JXVisionAI 停止脚本"
echo "========================================="

# 仅匹配真实服务进程，避免误杀/误判含该字符串的 shell
# 同时兼容旧包名 jxvisionai（重命名过渡）
_visionai_pids() {
    ps -eo pid=,args= | awk '
      $2 == "python3" && $3 == "-m" && ($4 == "visionai" || $4 == "jxvisionai") { print $1 }
    '
}

pids="$(_visionai_pids)"
if [ -z "$pids" ]; then
    echo "提示: JXVisionAI 服务未运行！"
    exit 0
fi

echo "正在停止 JXVisionAI 服务..."
# shellcheck disable=SC2086
kill $pids 2>/dev/null

sleep 2

pids="$(_visionai_pids)"
if [ -z "$pids" ]; then
    echo "✅ JXVisionAI 服务已成功停止！"
else
    echo "警告: 部分进程可能未完全停止，尝试强制终止..."
    # shellcheck disable=SC2086
    kill -9 $pids 2>/dev/null
    sleep 1

    if [ -z "$(_visionai_pids)" ]; then
        echo "✅ JXVisionAI 服务已强制停止！"
    else
        echo "❌ 无法停止 JXVisionAI 服务！"
        exit 1
    fi
fi

echo "========================================="
