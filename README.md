# JXVisionAI

[![License: AGPL v3](https://img.shields.io/badge/License-AGPL_v3-blue.svg)](LICENSE)

<p align="center">
  <img src="logo.png" alt="JXVisionAI" width="420">
</p>

多路 **RTSP / ONVIF / 国标 28181** 视频智能分析平台：YOLO26 主检测（COCO 80）+ 行为扩展（玩手机、人员聚集、人脸识别）+ **训练实验室专模**（吸烟、安全帽、未戴眼镜等，可自训）；告警写入 Redis，截图可落盘或上传 MinIO/S3；Flask Web 管理端配置接入与检测。

**许可证**：[GNU AGPL v3](LICENSE)。通过网络提供修改后的服务时，须向使用者提供对应源码（见 AGPL §13）。第三方模型/运行时见 [NOTICE](NOTICE)。

本仓库**不附带** YOLO / buffalo_l 权重、人脸库照片或告警截图。

> 品牌名 **JXVisionAI**。GitHub 仓库与 Python 包分别为 `JXVisionAI` / `visionai`。`visionai_secret`、Redis 键 `visionai:*`、对象存储前缀 `visionai/` 等技术标识保持不变，以免破坏现有部署。

**仓库**：<https://github.com/jiaxu-wang/JXVisionAI>

本项目由 **JX** 持续维护。欢迎 Issue 与 PR（见 [CONTRIBUTING.md](CONTRIBUTING.md)）。安全问题请按 [SECURITY.md](SECURITY.md) 私下报告。

---

## 文档

详细说明见 [`docs/`](docs/) 目录：

| 文档 | 内容 |
|------|------|
| [快速开始](docs/getting-started.md) | 安装、**YOLO26 n/s/m/l/x 下载与切换**、启动 |
| [系统架构](docs/architecture.md) | 进程模型、流水线、模型档位、存储 |
| [配置说明](docs/configuration.md) | `config.ini` 与环境变量 |
| [使用指南](docs/user-guide.md) | Web 管理端：设备接入、检测配置、人脸识别 |
| [国标 28181](docs/gb28181.md) | SIP 平台、通道预览与接入分析 |
| [检测与模型](docs/detection.md) | 检测类型、专模、训练概要 |
| [训练示例](docs/training-glasses-guide.md) | 采图→标注→训练→部署 |
| [HTTP API](docs/api.md) | 管理端 API |
| [运维与排障](docs/operations.md) | 日志、常见问题 |
| [ONVIF 对讲](docs/talk-onvif.md) | Audio Backchannel 探测与对讲 |
| [第三方接入](docs/integration.md) | Webhook / 开放 API / 侧栏嵌入页 |

---

## 快速体验

**推荐整栈 Docker**（API + worker + alert + sip + Redis + MinIO + ZLM）：

```bash
git clone https://github.com/jiaxu-wang/JXVisionAI.git
cd JXVisionAI
cp config/config.example.ini config/config.ini
cp .env.example .env                  # 填写 VISIONAI_SECRET / REDIS_PASSWORD / MinIO / ZLM_SECRET
./scripts/download_yolo26.sh          # YOLO26 权重 → models/
docker compose up -d --build
# 或：bash scripts/compose_up.sh
```

文档或旧 compose 里出现过的口令均视为**已公开**，生产必须轮换。

管理端：<http://服务器IP:15000>。  
健康检查：`curl -s http://127.0.0.1:15000/readyz`。  
宿主机映射见 `docker-compose.yaml` 注释（Redis `16379`、MinIO `19000/19001`、ZLM `18080/18554/18000`、国标 SIP `15060`、PS/RTP `10000-10200`）。

可选第三方对接见 [docs/integration.md](docs/integration.md)，不是运行本仓库的前提。

备选：本机 venv + `./start.sh`（Web `:5000`），依赖仍可用 `docker compose up -d redis minio zlmediakit`。详见 [docs/getting-started.md](docs/getting-started.md)。

---

## 技术栈

Python 3.10+ · OpenCV · Ultralytics YOLO26 · Flask · Redis · onnxruntime-gpu · MinIO/S3 · ZLMediaKit（可选）· visionai-inferd（可选）
