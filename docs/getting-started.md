# 快速开始

## 环境要求

- **Python** 3.10+（推荐 3.10/3.12）
- **Redis** 7+（流配置与检测记录）
- **可选**：MinIO 或 S3 兼容对象存储；`ffmpeg`（HLS 预览）
- **GPU**：可选；YOLO / ONNX 无 GPU 时走 CPU

---

## 1. 克隆与依赖

```bash
git clone https://github.com/jiaxu-wang/JXVisionAI.git
cd JXVisionAI
python3 -m venv env && source env/bin/activate   # Windows: env\Scripts\activate
pip install -r requirements.txt
```

`requirements.txt` 默认包含 **`onnxruntime-gpu`**（人脸 SCRFD/ArcFace 与 ONNX 专模用 CUDA 加速）。无 NVIDIA GPU 或装不上 GPU 轮子时，可改为 `onnxruntime>=1.16.0,<2.0`。

推理设备在 `config.ini` 的 **`[basic]` → `inference_device = cpu | gpu`** 切换（YOLO + ONNX 总开关），改完后 **`./stop.sh && ./start.sh` 重启** 生效。

除内置检测（COCO 80、打电话、玩手机、聚集、人脸识别）外，其它场景可在 **训练实验室** 训练并部署为 **专模**（`models/specialists/<key>/`），详见 [检测与模型](detection.md)。

---

## 2. 配置文件

```bash
cp config/config.example.ini config/config.ini
# 编辑分节： [basic] 密钥、[redis]、[minio]、[email]、[models] 等
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

## 4. 准备模型（YOLO26）

本项目**统一使用 Ultralytics YOLO26**（不再使用 YOLOv8）。权重放在项目根下 **`models/`**（大文件不入 Git）。

官方文件名是 **`yolo26s.pt`**（没有中间的 `v`，不要写成 `yolov26s.pt`）。

`config.ini` 路径写法：

- **相对路径**（推荐）：`models/yolo26s.pt` → `<项目根>/models/yolo26s.pt`
- **绝对路径**：`/data/models/yolo26s.pt`

> **重要**：配置了路径但文件不存在时，Ultralytics 会尝试联网下载；代理/GitHub 不通会导致**检测线程卡在加载**。请先把文件放到 `models/` 再启动。

### 4.1 从哪里下载

| 来源 | 地址 |
|------|------|
| **官方 Release（首选）** | https://github.com/ultralytics/assets/releases/tag/v8.4.0 |
| 主检测 `yolo26s.pt` | https://github.com/ultralytics/assets/releases/download/v8.4.0/yolo26s.pt |
| 姿态 `yolo26s-pose.pt` | https://github.com/ultralytics/assets/releases/download/v8.4.0/yolo26s-pose.pt |
| 轻量备选 `yolo26n.pt` | https://github.com/ultralytics/assets/releases/download/v8.4.0/yolo26n.pt |
| 文档 | https://docs.ultralytics.com/models/yolo26/ |

国内直连 GitHub 较慢时，可用镜像前缀（示例）：

```text
https://gh-proxy.com/https://github.com/ultralytics/assets/releases/download/v8.4.0/yolo26s.pt
```

### 4.2 怎么下载到本项目

在项目根目录执行（任选一种）：

**方式 A：curl（推荐，可控、可走镜像）**

```bash
cd /path/to/JXVisionAI
mkdir -p models

# 主检测（默认）
curl -fL --retry 5 -o models/yolo26s.pt \
  'https://gh-proxy.com/https://github.com/ultralytics/assets/releases/download/v8.4.0/yolo26s.pt'

# 姿态（打电话/玩手机需要）
curl -fL --retry 5 -o models/yolo26s-pose.pt \
  'https://gh-proxy.com/https://github.com/ultralytics/assets/releases/download/v8.4.0/yolo26s-pose.pt'

# 校验体积（s 约 20MB，s-pose 约 24MB；过小说明下载失败）
ls -lh models/yolo26s.pt models/yolo26s-pose.pt
```

**方式 B：Ultralytics 自动下载后再挪入 `models/`**

```bash
source env/bin/activate
python -c "from ultralytics import YOLO; YOLO('yolo26s.pt')"
mv -f yolo26s.pt models/
python -c "from ultralytics import YOLO; YOLO('yolo26s-pose.pt')"
mv -f yolo26s-pose.pt models/
```

浏览器下载：打开上方 Release 链接 → 保存到 `models/` 并改名为对应文件名。

### 4.3 本项目默认需要的权重

| 文件 | 用途 | 配置项（`[models]`） |
|------|------|----------------------|
| `models/yolo26s.pt` | YOLO 主检测（COCO 80 类） | `yolo_model` |
| `models/yolo26s-pose.pt` | 打电话/玩手机姿态 | `pose_model` |

可选更轻量：`yolo26n.pt` / `yolo26n-pose.pt`（改配置即可）。训练专模的预训练基座也请使用 **YOLO26**（如 `models/yolo26s.pt`）。

### 4.4 人脸识别（可选）

将 InsightFace **buffalo_l** 包解压到 `models/buffalo_l/`，至少需要：

```
models/buffalo_l/
├── det_10g.onnx      # SCRFD 人脸检测（含 5 点关键点）
├── w600k_r50.onnx    # ArcFace 特征提取
└── genderage.onnx    # 性别/年龄（可选；在检测类型配置中按流勾选启用）
```

### 4.5 内置扩展与训练专模

| 能力 | 说明 |
|------|------|
| 打电话 / 玩手机 | `pose_model`（默认 `models/yolo26s-pose.pt`）；可选 `make_call_model_path` |
| 人员聚集 | 仅依赖 YOLO26 人物框，无额外权重 |
| 人脸识别 | `models/buffalo_l/`（见上） |
| 其它检测 | 在 **训练实验室** 训练并「一键部署为专模」→ `models/specialists/<key>/`，自动出现在检测类型配置中，可勾选/删除 |

权重文件体积大，**不入 Git**（见 `.gitignore`）。

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

**ONVIF 扫描**：依赖 UDP 组播。桥接网络下「扫描局域网」常无结果，请用管理端 **手动 IP**，或将应用改为 `network_mode: host`。

---

## 下一步

- [配置说明](configuration.md)
- [使用指南](user-guide.md)
- [运维与排障](operations.md)
