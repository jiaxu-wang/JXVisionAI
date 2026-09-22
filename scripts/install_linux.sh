#!/usr/bin/env bash
# JXVisionAI 一键安装（Docker Compose），适用 x86_64 Linux。
# ARM64 / aarch64 系统请改用 scripts/install_linux_arm.sh。
# 用法：
#   ./scripts/install_linux.sh                 # 交互式选择推理设备 / 模型档位 / MinIO / ZLM
#   DEPLOY_NONINTERACTIVE=1 ./scripts/install_linux.sh   # 全部用默认值，不提问
#   DEPLOY_INFERENCE=gpu DEPLOY_YOLO_SIZE=m ./scripts/install_linux.sh
#
# 环境变量（可选）：
#   DEPLOY_INFERENCE   cpu|gpu           默认 cpu
#   DEPLOY_YOLO_SIZE   n|s|m|l|x         默认 s
#   DEPLOY_MINIO       1|0               默认 1（启用对象存储）
#   DEPLOY_ZLM         1|0               默认 1（启用 ZLM 预览/代理）
#   DEPLOY_NONINTERACTIVE 1              不提问，全用默认/环境变量
#   DEPLOY_SKIP_MODEL_DOWNLOAD 1         跳过模型下载（已手动放好权重时）
#
# 幂等：重复执行会复用已生成的 .env / config.ini / models，只重启服务。

set -euo pipefail
cd "$(dirname "$0")/.."
ROOT="$(pwd)"

# 架构检查：本脚本面向 x86_64；ARM64 走 install_linux_arm.sh
ARCH="$(uname -m)"
if [ "$ARCH" != "x86_64" ]; then
    echo "⚠ 当前架构: $ARCH。本脚本面向 x86_64。" >&2
    if [ "$ARCH" = "aarch64" ] || [ "$ARCH" = "arm64" ]; then
        echo "  ARM64 请使用: ./scripts/install_linux_arm.sh" >&2
        exit 1
    fi
    echo "  未测试的架构，继续执行可能失败。" >&2
fi

# ---------- 输出 ----------
c_green=$'\033[32m'; c_yellow=$'\033[33m'; c_red=$'\033[31m'; c_cyan=$'\033[36m'; c_reset=$'\033[0m'
info()  { echo "${c_cyan}==>${c_reset} $*"; }
ok()    { echo "${c_green}✔${c_reset} $*"; }
warn()  { echo "${c_yellow}⚠${c_reset} $*"; }
die()   { echo "${c_red}✘ $*${c_reset}" >&2; exit 1; }

# ---------- 小工具 ----------
gen_secret() {
    # 生成 URL 安全随机串
    if command -v openssl >/dev/null 2>&1; then
        openssl rand -hex 24
    else
        head -c 24 /dev/urandom | od -An -tx1 | tr -d ' \n'
    fi
}

# ini_set <file> <section> <key> <value>
# 就地修改/新增 ini 键；保留注释；节不存在则追加。
ini_set() {
    local file="$1" section="$2" key="$3" value="$4"
    python3 - "$file" "$section" "$key" "$value" <<'PYEOF'
import re, sys
path, section, key, value = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]
with open(path, encoding="utf-8") as f:
    lines = f.readlines()
sec_re = re.compile(r"^\s*\[([^\]]+)\]")
assign_re = re.compile(r"^(\s*)([A-Za-z_][\w]*)\s*=")
cur = None
sec_start = sec_end = None
done = False
for i, line in enumerate(lines):
    m = sec_re.match(line)
    if m:
        if cur == section and sec_end is None:
            sec_end = i
        cur = m.group(1).strip()
        if cur == section:
            sec_start = i
        continue
    if cur == section:
        am = assign_re.match(line)
        if am and am.group(2) == key:
            lines[i] = f"{am.group(1)}{key} = {value}\n"
            done = True
            break
if not done:
    if sec_start is None:
        if lines and not lines[-1].endswith("\n"):
            lines[-1] += "\n"
        lines.append(f"\n[{section}]\n{key} = {value}\n")
    else:
        # 插到节尾（下一节标题前）
        end = len(lines)
        for j in range(sec_start + 1, len(lines)):
            if sec_re.match(lines[j]):
                end = j
                break
        lines.insert(end, f"{key} = {value}\n")
with open(path, "w", encoding="utf-8") as f:
    f.writelines(lines)
PYEOF
}

# env_set <key> <value>  —— 写进 .env（存在则替换，否则追加）
env_set() {
    local key="$1" value="$2"
    if grep -qE "^${key}=" .env 2>/dev/null; then
        # 用 | 作分隔符，避免值里的 / & 干扰
        sed -i "s|^${key}=.*|${key}=${value}|" .env
    else
        echo "${key}=${value}" >> .env
    fi
}

# env_get <key> —— 从 .env 读取（去掉引号）
env_get() {
    local key="$1"
    grep -E "^${key}=" .env 2>/dev/null | tail -n1 | cut -d= -f2- | sed -e 's/^"//' -e 's/"$//' -e "s/^'//" -e "s/'\$//"
}

ask() {
    # ask <varname> <prompt> <default>
    local var="$1" prompt="$2" def="$3" ans
    if [ "${DEPLOY_NONINTERACTIVE:-0}" = "1" ]; then
        printf -v "$var" '%s' "${!var:-$def}"
        return
    fi
    read -r -p "$prompt [$def]: " ans || true
    ans="${ans:-$def}"
    printf -v "$var" '%s' "$ans"
}

ask_yn() {
    # ask_yn <varname> <prompt> <default y|n>
    local var="$1" prompt="$2" def="$3" ans
    if [ "${DEPLOY_NONINTERACTIVE:-0}" = "1" ]; then
        printf -v "$var" '%s' "${!var:-$def}"
        return
    fi
    local hint="Y/n"; [ "$def" = "n" ] && hint="y/N"
    read -r -p "$prompt [$hint]: " ans || true
    ans="${ans:-$def}"
    case "$ans" in y|Y|yes|YES|1) ans=y ;; *) ans=n ;; esac
    printf -v "$var" '%s' "$ans"
}

# ---------- 0. 预检 ----------
info "预检：docker / compose / 网络"
command -v docker >/dev/null 2>&1 || die "未安装 docker。请先安装 Docker 后重试。"
docker info >/dev/null 2>&1 || die "无法访问 docker daemon（试试 sudo，或把当前用户加入 docker 组）。"
if docker compose version >/dev/null 2>&1; then
    COMPOSE=(docker compose)
elif command -v docker-compose >/dev/null 2>&1; then
    COMPOSE=(docker-compose)
else
    die "未找到 docker compose 插件或 docker-compose。"
fi
command -v curl >/dev/null 2>&1 || die "未安装 curl。"
command -v python3 >/dev/null 2>&1 || die "未安装 python3（脚本写 ini 需要）。"
ok "docker / compose / curl / python3 就绪"

# ---------- 1. 配置文件 ----------
info "准备 config.ini 与 .env"
if [ ! -f config/config.ini ]; then
    cp config/config.example.ini config/config.ini
    ok "已从 config.example.ini 生成 config.ini"
else
    ok "config.ini 已存在，保留"
fi
if [ ! -f .env ]; then
    cp .env.example .env
    ok "已从 .env.example 生成 .env"
else
    ok ".env 已存在，保留"
fi

# ---------- 2. 交互选择 ----------
echo
info "部署选项（直接回车用默认值）"

DEPLOY_INFERENCE="${DEPLOY_INFERENCE:-}"
if [ -z "$DEPLOY_INFERENCE" ] && [ "${DEPLOY_NONINTERACTIVE:-0}" != "1" ]; then
    echo "  推理设备：cpu 无需显卡；gpu 需要 NVIDIA 显卡 + nvidia-container-toolkit"
fi
ask DEPLOY_INFERENCE "推理设备 cpu/gpu" "cpu"
DEPLOY_INFERENCE="$(echo "$DEPLOY_INFERENCE" | tr 'A-Z' 'a-z')"
[ "$DEPLOY_INFERENCE" = "gpu" ] || DEPLOY_INFERENCE="cpu"

DEPLOY_YOLO_SIZE="${DEPLOY_YOLO_SIZE:-}"
if [ -z "$DEPLOY_YOLO_SIZE" ] && [ "${DEPLOY_NONINTERACTIVE:-0}" != "1" ]; then
    echo "  模型档位：n 最快 / s 平衡(默认) / m / l / x 最准最慢"
fi
ask DEPLOY_YOLO_SIZE "YOLO 档位 n/s/m/l/x" "s"
DEPLOY_YOLO_SIZE="$(echo "$DEPLOY_YOLO_SIZE" | tr 'A-Z' 'a-z')"
case "$DEPLOY_YOLO_SIZE" in n|s|m|l|x) ;; *) DEPLOY_YOLO_SIZE="s" ;; esac

DEPLOY_MINIO="${DEPLOY_MINIO:-}"
ask_yn DEPLOY_MINIO "启用对象存储 MinIO（截图上传；选 n 则只存本地）" "y"
[ "$DEPLOY_MINIO" = "y" ] && DEPLOY_MINIO=1 || DEPLOY_MINIO=0

DEPLOY_ZLM="${DEPLOY_ZLM:-}"
ask_yn DEPLOY_ZLM "启用 ZLM 媒体面（WebRTC 预览 / 拉流代理）" "y"
[ "$DEPLOY_ZLM" = "y" ] && DEPLOY_ZLM=1 || DEPLOY_ZLM=0

# GPU 可行性检查
if [ "$DEPLOY_INFERENCE" = "gpu" ]; then
    if ! command -v nvidia-smi >/dev/null 2>&1; then
        warn "未检测到 nvidia-smi，回退 CPU"
        DEPLOY_INFERENCE="cpu"
    elif ! docker run --rm --gpus all nvidia/cuda:12.0.0-base nvidia-smi >/dev/null 2>&1; then
        warn "Docker 无法使用 GPU（缺 nvidia-container-toolkit？），回退 CPU"
        DEPLOY_INFERENCE="cpu"
    fi
fi
ok "推理设备: $DEPLOY_INFERENCE | 模型: yolo26$DEPLOY_YOLO_SIZE | MinIO: $DEPLOY_MINIO | ZLM: $DEPLOY_ZLM"

# ---------- 3. 生成/同步密钥 ----------
info "检查并生成密钥（已存在的保留）"

VISIONAI_SECRET="$(env_get VISIONAI_SECRET)"
if [ -z "$VISIONAI_SECRET" ]; then
    VISIONAI_SECRET="$(gen_secret)"
    env_set VISIONAI_SECRET "$VISIONAI_SECRET"
    ok "已生成 VISIONAI_SECRET"
fi

REDIS_PASSWORD="$(env_get REDIS_PASSWORD)"
if [ -z "$REDIS_PASSWORD" ]; then
    REDIS_PASSWORD="$(gen_secret)"
    env_set REDIS_PASSWORD "$REDIS_PASSWORD"
    ok "已生成 REDIS_PASSWORD"
fi

MINIO_ROOT_USER="$(env_get MINIO_ROOT_USER)"; MINIO_ROOT_USER="${MINIO_ROOT_USER:-minio}"
env_set MINIO_ROOT_USER "$MINIO_ROOT_USER"
MINIO_ROOT_PASSWORD="$(env_get MINIO_ROOT_PASSWORD)"
if [ -z "$MINIO_ROOT_PASSWORD" ]; then
    MINIO_ROOT_PASSWORD="$(gen_secret)"
    env_set MINIO_ROOT_PASSWORD "$MINIO_ROOT_PASSWORD"
    ok "已生成 MINIO_ROOT_PASSWORD"
fi

ZLM_SECRET="$(env_get ZLM_SECRET)"
if [ -z "$ZLM_SECRET" ]; then
    ZLM_SECRET="$(gen_secret)"
    env_set ZLM_SECRET "$ZLM_SECRET"
    ok "已生成 ZLM_SECRET"
fi

# 同步到 config.ini（compose 环境变量优先，但宿主机 ./start.sh 读 ini）
ini_set config/config.ini basic visionai_secret "$VISIONAI_SECRET"
ini_set config/config.ini redis password "$REDIS_PASSWORD"
ini_set config/config.ini minio access_key_id "$MINIO_ROOT_USER"
ini_set config/config.ini minio secret_access_key "$MINIO_ROOT_PASSWORD"
ini_set config/config.ini basic inference_device "$DEPLOY_INFERENCE"
ini_set config/config.ini models yolo_model "models/yolo26${DEPLOY_YOLO_SIZE}.pt"
ini_set config/config.ini models pose_model "models/yolo26${DEPLOY_YOLO_SIZE}-pose.pt"
if [ "$DEPLOY_MINIO" = "1" ]; then
    ini_set config/config.ini minio enabled true
else
    ini_set config/config.ini minio enabled false
fi
if [ "$DEPLOY_ZLM" = "1" ]; then
    ini_set config/config.ini zlm enabled true
    ini_set config/config.ini zlm secret "$ZLM_SECRET"
else
    ini_set config/config.ini zlm enabled false
fi

# 推理设备写进 .env，让 compose 注入容器
env_set INFERENCE_DEVICE "$DEPLOY_INFERENCE"
if [ "$DEPLOY_INFERENCE" = "gpu" ]; then
    env_set ONNX_PROVIDER "cuda_first"
    env_set ORT_PKG "onnxruntime-gpu"
else
    env_set ONNX_PROVIDER "cpu"
    env_set ORT_PKG "onnxruntime"
fi

# 同步 ZLM 旁路配置里的 api secret（compose 挂载 config/zlm/config.ini）
for zf in config/zlm/config.ini config/zlm/config.host.ini; do
    if [ -f "$zf" ]; then
        ini_set "$zf" api secret "$ZLM_SECRET"
    fi
done
ok "密钥与 config.ini / ZLM 配置已同步"

# ---------- 4. 模型权重 ----------
if [ "${DEPLOY_SKIP_MODEL_DOWNLOAD:-0}" != "1" ]; then
    info "下载 YOLO26 权重（已存在则跳过）"
    MODELS="$DEPLOY_YOLO_SIZE" DOWNLOAD_POSE=1 bash scripts/download_yolo26.sh
else
    warn "DEPLOY_SKIP_MODEL_DOWNLOAD=1，跳过模型下载"
fi

# ---------- 5. MinIO 镜像拉取兜底（DaoCloud 403 场景） ----------
ensure_image() {
    # ensure_image <compose引用名> <候选1> <候选2> ...
    local ref="$1"; shift
    if docker image inspect "$ref" >/dev/null 2>&1; then
        ok "镜像已存在: $ref"
        return 0
    fi
    local cand
    for cand in "$@"; do
        info "拉取镜像: $cand"
        if docker pull "$cand"; then
            if [ "$cand" != "$ref" ]; then
                docker tag "$cand" "$ref"
                ok "已标记 $cand -> $ref"
            fi
            return 0
        fi
        warn "拉取失败: $cand"
    done
    return 1
}

if [ "$DEPLOY_MINIO" = "1" ]; then
    ensure_image "minio/minio:latest" \
        "minio/minio:latest" \
        "quay.io/minio/minio:latest" \
        || die "MinIO 镜像拉取失败。请检查网络或 Docker 镜像加速器后重试。"
fi

# ---------- 6. 启动 ----------
info "停止可能占用端口的宿主机进程"
./stop.sh 2>/dev/null || true
pkill -f '[p]ython3 -m visionai' 2>/dev/null || true
sleep 1

# 不启用 MinIO 时：override 移除应用对 minio 的依赖，启动时排除 minio 服务。
# compose 对 map 形式 depends_on 是按键合并，必须用 !override 标签整体替换才能删掉 minio。
OVERRIDE=""
UP_SERVICES=(redis zlmediakit visionai-api visionai-worker visionai-alert visionai-sip)
if [ "$DEPLOY_MINIO" = "1" ]; then
    UP_SERVICES=(minio redis zlmediakit visionai-api visionai-worker visionai-alert visionai-sip)
else
    OVERRIDE="$(mktemp /tmp/visionai-deploy-override.XXXXXX.yaml)"
    cat > "$OVERRIDE" <<'YAML'
services:
  visionai-api:
    depends_on: !override
      redis:
        condition: service_healthy
      zlmediakit:
        condition: service_started
  visionai-worker:
    depends_on: !override
      redis:
        condition: service_healthy
      zlmediakit:
        condition: service_started
  visionai-alert:
    depends_on: !override
      redis:
        condition: service_healthy
      zlmediakit:
        condition: service_started
  visionai-sip:
    depends_on: !override
      redis:
        condition: service_healthy
      zlmediakit:
        condition: service_started
YAML
    ok "MinIO 已禁用（截图仅本地），将不启动 minio 容器"
fi

COMPOSE_FILES=(-f docker-compose.yaml)
[ -n "$OVERRIDE" ] && COMPOSE_FILES+=(-f "$OVERRIDE")

# GPU：给四个应用容器挂 NVIDIA 设备
if [ "$DEPLOY_INFERENCE" = "gpu" ]; then
    GPU_OVERRIDE="$(mktemp /tmp/visionai-deploy-gpu.XXXXXX.yaml)"
    cat > "$GPU_OVERRIDE" <<'YAML'
services:
  visionai-api:
    deploy:
      resources:
        reservations:
          devices:
            - driver: nvidia
              count: all
              capabilities: [gpu]
  visionai-worker:
    deploy:
      resources:
        reservations:
          devices:
            - driver: nvidia
              count: all
              capabilities: [gpu]
  visionai-alert:
    deploy:
      resources:
        reservations:
          devices:
            - driver: nvidia
              count: all
              capabilities: [gpu]
  visionai-sip:
    deploy:
      resources:
        reservations:
          devices:
            - driver: nvidia
              count: all
              capabilities: [gpu]
YAML
    COMPOSE_FILES+=(-f "$GPU_OVERRIDE")
    ok "已启用 GPU 设备挂载"
fi

info "构建并启动服务（首次构建较慢）: ${UP_SERVICES[*]}"
"${COMPOSE[@]}" "${COMPOSE_FILES[@]}" up -d --build "${UP_SERVICES[@]}"

# ZLM secret 一致性：容器是长驻的，配置变了 compose 不会自动重启。
# 比较容器内实际加载的 secret 与本次期望值，不一致则强制重建。
if [ "$DEPLOY_ZLM" = "1" ]; then
    RUNNING_ZLM_SECRET="$(docker exec visionai-zlm sh -c 'grep -E "^secret" /opt/media/conf/config.ini 2>/dev/null | head -n1 | cut -d= -f2' 2>/dev/null | tr -d '[:space:]' || true)"
    if [ -n "$RUNNING_ZLM_SECRET" ] && [ "$RUNNING_ZLM_SECRET" != "$ZLM_SECRET" ]; then
        warn "ZLM 容器 secret 与本次配置不一致，强制重建 zlmediakit"
        "${COMPOSE[@]}" "${COMPOSE_FILES[@]}" up -d --force-recreate zlmediakit
        sleep 2
    fi
fi

# ---------- 7. 等待就绪 ----------
info "等待 API 就绪"
ready=0
for i in $(seq 1 120); do
    if curl -fsS http://127.0.0.1:15000/healthz >/dev/null 2>&1; then
        ready=1
        break
    fi
    sleep 2
done
if [ "$ready" != "1" ]; then
    warn "API 未在预期时间内就绪，最近日志："
    "${COMPOSE[@]}" "${COMPOSE_FILES[@]}" logs --tail=120 visionai-api visionai-worker visionai-alert || true
    die "部署未完成。把上面日志发给我排查。"
fi

"${COMPOSE[@]}" "${COMPOSE_FILES[@]}" ps

echo
ok "部署完成"
echo "  管理端:        http://$(hostname -I 2>/dev/null | awk '{print $1}' || echo 127.0.0.1):15000"
echo "  登录密钥:      $VISIONAI_SECRET"
echo "  健康检查:      curl -s http://127.0.0.1:15000/readyz"
[ "$DEPLOY_MINIO" = "1" ] && echo "  MinIO 控制台:  http://127.0.0.1:19001  ($MINIO_ROOT_USER / $MINIO_ROOT_PASSWORD)"
[ "$DEPLOY_ZLM" = "1" ] && echo "  ZLM HTTP:      http://127.0.0.1:18080"
echo
echo "  密钥已写入 .env 与 config/config.ini，请妥善保存。"
