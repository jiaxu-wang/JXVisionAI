# 快速开始

## 环境要求

- **Python** 3.10+（推荐 3.10/3.12）
- **Redis** 7+（流配置与检测记录）
- **可选**：MinIO 或 S3 兼容对象存储；`ffmpeg`（HLS 预览）
- **GPU**：可选；YOLO / ONNX 无 GPU 时走 CPU

---

## 1. 克隆与依赖

```bash
git clone https://github.com/jiaxu-wang/visionai.git
cd visionai
python3 -m venv env && source env/bin/activate   # Windows: env\Scripts\activate
pip install -r requirements.txt
```

---

## 2. 配置文件

```bash
cp config/config.example.ini config/config.ini
# 编辑 config.ini：visionai_secret、redis、SMTP、模型路径等
```

---

## 3. 启动 Redis（及可选 MinIO）

```bash
docker compose up -d redis          # 仅 Redis
# 或
docker compose up -d                # Redis + MinIO
```

默认 Redis：`127.0.0.1:16379`，密码 `VisionAI@2026`（见 `docker-compose.yaml`）。

---

## 4. 准备模型

所有模型权重统一放在项目根下 **`models/`** 目录。`config.ini` 中路径支持：

- **相对路径**（推荐）：`models/yolov8n.pt` → 解析为 `<项目根>/models/yolov8n.pt`
- **绝对路径**：`/data/models/yolov8n.pt`
- 也支持 `./models/xxx` 写法

> **重要**：配置写了 `models/xxx` 但文件不存在时，Ultralytics 会尝试联网下载；代理不可用会导致**检测线程卡在加载**，界面显示流在线但无任何告警。请确保文件已就位后再启动。

### 必需模型

| 文件 | 用途 | 获取方式 |
|------|------|----------|
| `models/yolov8n.pt` | YOLO 主检测 | [Ultralytics 发布页](https://github.com/ultralytics/assets/releases) 或首次联网自动下载 |

### 人脸识别（可选）

将 InsightFace **buffalo_l** 包解压到 `models/buffalo_l/`，至少需要：

```
models/buffalo_l/
├── det_10g.onnx      # SCRFD 人脸检测（含 5 点关键点）
└── w600k_r50.onnx    # ArcFace 特征提取
```

### 扩展专模（按需在「检测类型配置」中开启）

| 配置键 | 默认相对路径 |
|--------|----------------|
| `face_model_path` | `models/face_detection.onnx` |
| `fall_model_path` | `models/fall_detection.onnx` |
| `smoking_cigarette_detector_path` | `models/smoking_detection.pt` |
| `pose_model` | `models/yolov8n-pose.pt` |
| … | 见 `config.example.ini` |

权重文件体积大，**不入 Git**（见 `.gitignore`），需在部署环境自行放置或从训练管线导出。

---

## 5. 启动应用

```bash
./start.sh
```

- 管理端：<http://服务器IP:5000>
- 默认登录密钥：`config.ini` 中 `visionai_secret`（生产务必修改）
- 停止：`./stop.sh`
- 日志：`tail -f logs/visionai.log`

`start.sh` 会自动设置本机友好环境变量：

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `REDIS_HOST` | `127.0.0.1` | 覆盖 ini 中 Docker 用的 `redis` |
| `REDIS_PORT` | `16379` | compose 对外映射端口 |
| `SAVE_DIR` | `./snapshots` | 截图目录 |
| `LOG_DIR` | `./logs` | 日志目录 |
| `S3_ENDPOINT_URL` | `http://127.0.0.1:9000` | 本机 MinIO |

---

## Docker 部署应用（可选）

`docker-compose.yaml` 中 `visionai` 服务块默认注释。取消注释并挂载 `./config`、`./snapshots`、`./logs`、`./models` 后可容器化运行。容器内访问摄像机 RTSP **勿用** `127.0.0.1`，应使用摄像头局域网 IP。

---

## 下一步

- [配置说明](configuration.md)
- [使用指南](user-guide.md)
- [运维与排障](operations.md)
