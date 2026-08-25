# JXVisionAI：YOLO 视频检测 + Flask 管理端（api / worker / alert_worker 共用镜像）
# 构建：docker compose build visionai-api
# 默认装 CPU 版 onnxruntime（镜像更小、无 GPU 也能起）；需要 GPU 时：
#   docker compose build --build-arg ORT_PKG=onnxruntime-gpu visionai-api
FROM python:3.12-slim-bookworm

ARG ORT_PKG=onnxruntime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    VISIONAI_ROLE=api \
    TZ=Asia/Shanghai \
    VISIONAI_TIMEZONE=Asia/Shanghai \
    LANG=C.UTF-8

# tzdata：运行时可按 VISIONAI_TIMEZONE / TZ 覆盖（compose 注入），不写死某地区
RUN apt-get update && apt-get install -y --no-install-recommends \
    libglib2.0-0 \
    libgomp1 \
    libgl1 \
    libjpeg62-turbo \
    libpng16-16 \
    curl \
    tzdata \
    fonts-wqy-microhei \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
# Docker 默认用 ORT_PKG 替换 onnxruntime-gpu，避免无 CUDA 基础镜像时装失败/体积过大
RUN sed "s/onnxruntime-gpu.*/${ORT_PKG}>=1.16.0,<2.0/" requirements.txt > /tmp/requirements.docker.txt \
    && pip install --no-cache-dir -r /tmp/requirements.docker.txt \
    && pip install --no-cache-dir "waitress>=3.0.0" "requests>=2.31.0" \
    && python -c "from rapidocr_onnxruntime import RapidOCR; RapidOCR()" || true

COPY visionai/ ./visionai/
COPY config/ ./config/
COPY training_system/ ./training_system/
COPY docker/docker-entrypoint.sh /docker-entrypoint.sh

RUN chmod +x /docker-entrypoint.sh \
    && mkdir -p /app/snapshots /app/logs /app/models

EXPOSE 5000

ENTRYPOINT ["/docker-entrypoint.sh"]
CMD ["api"]
