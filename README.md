# JXVisionAI

<p align="center">
  <img src="logo.png" alt="JXVisionAI" width="420">
</p>

多路 **RTSP** 视频智能分析平台：YOLO26 主检测（COCO 80）+ 行为扩展（打电话、玩手机、人员聚集、人脸识别）+ **训练实验室专模**（吸烟、安全帽、未戴眼镜等）；告警写入 Redis，截图可落盘或上传 MinIO/S3；Flask Web 管理端配置每路流与检测项。

> 品牌名 **JXVisionAI**。GitHub 仓库与 Python 包分别为 `JXVisionAI` / `visionai`。`visionai_secret`、Redis 键 `visionai:*`、对象存储前缀 `visionai/` 等技术标识保持不变，以免破坏现有部署。

**仓库**：<https://github.com/jiaxu-wang/JXVisionAI>

本项目由 **JX** 持续维护。欢迎 Issue 与 PR。

---

## 文档

详细说明见 [`docs/`](docs/) 目录：

| 文档 | 内容 |
|------|------|
| [快速开始](docs/getting-started.md) | 安装、**YOLO26 n/s/m/l/x 下载与切换**、启动 |
| [系统架构](docs/architecture.md) | 进程模型、流水线、模型档位、存储 |
| [配置说明](docs/configuration.md) | `config.ini` 与环境变量 |
| [使用指南](docs/user-guide.md) | Web 管理端、人脸识别操作 |
| [检测与模型](docs/detection.md) | 检测类型、专模、训练概要 |
| [训练示例](docs/training-glasses-guide.md) | 采图→标注→训练→部署 |
| [HTTP API](docs/api.md) | 管理端 API |
| [运维与排障](docs/operations.md) | 日志、常见问题 |

---

## 快速体验

```bash
git clone https://github.com/jiaxu-wang/JXVisionAI.git
cd JXVisionAI
python3 -m venv env && source env/bin/activate
pip install -r requirements.txt
cp config/config.example.ini config/config.ini
docker compose up -d redis minio          # 可选再加 zlmediakit
# 下载 YOLO26 权重（n/s/m/l/x），见 docs/getting-started.md
./scripts/download_yolo26.sh
# 配置 [models] yolo_model = models/yolo26s.pt 后启动
./start.sh
```

`./start.sh` 拉起多进程：`visionai.api`（Web :5000）+ `visionai.worker`（拉流检测）+ `alert_worker`（异步告警）；可选 `visionai-inferd`（`[infer] backend=cpp`）与 compose 中的 ZLMediaKit。流在线状态写入 Redis，供管理端跨进程展示。

管理端：<http://服务器IP:5000>，登录密钥见 `config.ini` 的 `[basic]` → `visionai_secret`。

---

## 技术栈

Python 3.10+ · OpenCV · Ultralytics YOLO26 · Flask · Redis · onnxruntime-gpu · MinIO/S3 · ZLMediaKit（可选）· visionai-inferd（可选）
