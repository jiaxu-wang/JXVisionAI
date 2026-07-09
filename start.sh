#!/bin/bash

echo "========================================="
echo "          JXVisionAI 启动脚本"
echo "========================================="

# 仅匹配真实服务进程，避免把含该字符串的 shell/脚本误判为已运行
_jxvisionai_pids() {
    ps -eo pid=,args= | awk '$2 == "python3" && $3 == "-m" && $4 == "jxvisionai" { print $1 }'
}

# 检查虚拟环境是否存在（勿对系统 Python 执行 pip：Debian/Ubuntu 上会因 PEP 668 报错）
if [ ! -d "env" ]; then
    echo "错误: 虚拟环境 'env' 不存在！"
    echo "请先执行:"
    echo "  python3 -m venv env"
    echo "  ./env/bin/pip install -r requirements.txt"
    exit 1
fi

# 检查是否已存在运行中的进程
if [ -n "$(_jxvisionai_pids)" ]; then
    echo "警告: JXVisionAI 服务已在运行中！"
    echo "如果需要重启，请先运行: ./stop.sh"
    exit 1
fi

# 激活虚拟环境并启动服务
echo "正在启动 JXVisionAI 服务..."
source env/bin/activate

# 与 requirements.txt 保持同步（新增依赖后无需手动 pip）
if ! pip install -q -r requirements.txt; then
    echo "错误: pip install -r requirements.txt 失败，请检查网络与虚拟环境"
    exit 1
fi

# 本机直跑时覆盖「Docker 专用」的 config（config.ini 里常有 redis:6379、/app/...）
# 优先级：你手动 export 的环境变量 > 本脚本默认值 > config.ini
# 确保宿主机上 Redis 已监听（如 compose 映射的 16379）：docker compose up -d redis
export REDIS_HOST="${REDIS_HOST:-127.0.0.1}"
export REDIS_PORT="${REDIS_PORT:-16379}"
export SAVE_DIR="${SAVE_DIR:-./snapshots}"
export LOG_DIR="${LOG_DIR:-./logs}"
# 本机直跑 + compose 起 MinIO 时：须用宿主机端口，且勿让 http(s)_proxy 劫持 S3（否则 CreateBucket/PutObject 常 502）
if [ -n "${NO_PROXY:-}" ]; then
    export NO_PROXY="$NO_PROXY,127.0.0.1,localhost"
else
    export NO_PROXY="127.0.0.1,localhost"
fi
export S3_ENDPOINT_URL="${S3_ENDPOINT_URL:-http://127.0.0.1:9000}"
# 若本机不用 MinIO：export OBJECT_STORAGE_ENABLED=false

# 与 TimedRotating 日志路径一致
mkdir -p "$LOG_DIR" ./logs
nohup python3 -m jxvisionai > ./logs/visionai.log 2>&1 &

# 等待服务启动
sleep 2

# 检查服务是否成功启动
if [ -n "$(_jxvisionai_pids)" ]; then
    echo "✅ JXVisionAI 服务启动成功！"
    echo "📋 Web管理界面地址: http://0.0.0.0:5000"
    echo "📝 日志文件: ./logs/visionai.log"
    echo "🔧 停止服务: ./stop.sh"
else
    echo "❌ JXVisionAI 服务启动失败！"
    echo "请查看日志: ./logs/visionai.log"
    exit 1
fi

echo "========================================="
