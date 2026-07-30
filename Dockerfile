# JXVisionAI：YOLO 视频检测 + Flask 管理端
FROM python:3.12-slim-bookworm

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# OpenCV headless / ultralytics 常用系统库
RUN apt-get update && apt-get install -y --no-install-recommends \
    libglib2.0-0 \
    libgomp1 \
    libjpeg62-turbo \
    libpng16-16 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY visionai/ ./visionai/
COPY config/ ./config/

RUN mkdir -p /app/snapshots /app/logs

EXPOSE 5000

# 首次运行若无 yolov8n.pt，ultralytics 会自动下载
CMD ["python", "-m", "visionai"]
