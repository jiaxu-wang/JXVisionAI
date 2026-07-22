# JXVisionAI

<p align="center">
  <img src="logo.png" alt="JXVisionAI" width="420">
</p>

多路 **RTSP** 视频智能分析平台：YOLO 主检测 + 行为扩展（吸烟、打电话等）+ 人脸识别；告警写入 Redis，截图可落盘或上传 MinIO/S3；Flask Web 管理端配置每路流与检测项。

> 品牌名 **JXVisionAI**。GitHub 仓库与 Python 包分别为 `JXVisionAI` / `visionai`。`visionai_secret`、Redis 键 `visionai:*`、对象存储前缀 `visionai/` 等技术标识保持不变，以免破坏现有部署。

**仓库**：<https://github.com/jiaxu-wang/JXVisionAI>

本项目由 **JX** 持续维护。欢迎 Issue 与 PR。

---

## 文档

详细说明见 [`docs/`](docs/) 目录：

| 文档 | 内容 |
|------|------|
| [快速开始](docs/getting-started.md) | 环境、安装、模型、启动 |
| [系统架构](docs/architecture.md) | 进程模型、流水线、存储、目录结构 |
| [配置说明](docs/configuration.md) | `config.ini` 与环境变量 |
| [使用指南](docs/user-guide.md) | Web 管理端、人脸识别操作 |
| [检测与模型](docs/detection.md) | 检测类型、专模、训练管线 |
| [训练示例：戴眼镜](docs/training-glasses-guide.md) | 采图→标注→训练→测试→一键部署全流程 |
| [HTTP API](docs/api.md) | 管理端 API 一览 |
| [运维与排障](docs/operations.md) | 日志、常见问题、路线图 |
| [人脸识别设计](docs/face_recognition_design.md) | 人脸识别详细设计与实现 |

---

## 快速体验

```bash
git clone https://github.com/jiaxu-wang/JXVisionAI.git
cd JXVisionAI
python3 -m venv env && source env/bin/activate
pip install -r requirements.txt
cp config/config.example.ini config/config.ini
docker compose up -d redis
# 自备 models/yolov8n.pt，见 docs/getting-started.md
./start.sh
```

管理端：<http://服务器IP:5000>，登录密钥见 `config.ini` 中 `visionai_secret`。

---

## 技术栈

Python 3.10+ · OpenCV · Ultralytics YOLOv8 · Flask · Redis · onnxruntime · MinIO/S3
