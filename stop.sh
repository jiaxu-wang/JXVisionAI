#!/bin/bash

echo "========================================="
echo "          VisionAI 停止脚本"
echo "========================================="

# 检查是否有运行中的进程
if ! pgrep -f "python3 -m visionai" > /dev/null; then
    echo "提示: VisionAI 服务未运行！"
    exit 0
fi

# 停止所有VisionAI进程
echo "正在停止 VisionAI 服务..."
pkill -f "python3 -m visionai"

# 等待进程退出
sleep 2

# 检查服务是否成功停止
if ! pgrep -f "python3 -m visionai" > /dev/null; then
    echo "✅ VisionAI 服务已成功停止！"
else
    echo "警告: 部分进程可能未完全停止，尝试强制终止..."
    pkill -9 -f "python3 -m visionai"
    sleep 1
    
    if ! pgrep -f "python3 -m visionai" > /dev/null; then
        echo "✅ VisionAI 服务已强制停止！"
    else
        echo "❌ 无法停止 VisionAI 服务！"
        exit 1
    fi
fi

echo "========================================="