# 快速开始

## 环境要求

- **Docker / Docker Compose**（推荐整栈）或 **Python** 3.10+（宿主机多进程）
- **Redis** 7+（流配置与检测记录）
- **可选**：MinIO / S3；**ZLMediaKit**（预览与本地回源）
- **GPU**：可选；Compose 默认 CPU；有 NVIDIA Container Toolkit 时可改 `INFERENCE_DEVICE=gpu`

---

## 推荐：整栈 Docker

```bash
git clone https://github.com/jiaxu-wang/JXVisionAI.git
cd JXVisionAI
cp config/config.example.ini config/config.ini   # 若尚无 config.ini
# 下载 YOLO26 权重到 models/（见 §4）
./scripts/download_yolo26.sh
docker compose up -d --build
```

或使用封装脚本（会先停掉宿主机 `./start.sh` 进程）：

```bash
bash scripts/compose_up.sh
```

| 项 | 地址 / 说明 |
|----|-------------|
| 管理端 | <http://服务器IP:15000> |
| 健康检查 | `curl -s http://127.0.0.1:15000/healthz` · `curl -s http://127.0.0.1:15000/readyz` |
| Redis（宿主机） | `127.0.0.1:16379`，密码见 compose（默认 `VisionAI@2026`） |
| MinIO 控制台 | <http://127.0.0.1:19001> |
| ZLM HTTP | `http://127.0.0.1:18080` |

服务：`visionai-api` / `visionai-worker` / `visionai-alert` + `redis` / `minio` / `zlmediakit`。

改 `config.ini` 或主模型后：

```bash
docker compose restart visionai-api visionai-worker visionai-alert
```

容器内访问摄像机 RTSP **勿用** `127.0.0.1`，应使用摄像头局域网 IP。  
**ONVIF 扫描**：桥接网络下组播常失败，请用管理端 **手动 IP**。

登录密钥：`VISIONAI_SECRET`（compose 环境变量）或 `config.ini` → `visionai_secret`（生产务必修改）。

---

## 备选：宿主机 Python + 依赖容器

### 1. 克隆与依赖

```bash
git clone https://github.com/jiaxu-wang/JXVisionAI.git
cd JXVisionAI
python3 -m venv env && source env/bin/activate   # Windows: env\Scripts\activate
pip install -r requirements.txt
```

`requirements.txt` 默认包含 **`onnxruntime-gpu`**。无 NVIDIA GPU 时可改为 `onnxruntime>=1.16.0,<2.0`。

推理设备：`config.ini` → **`[basic]` → `inference_device = cpu | gpu`**，改完重启生效。

除内置检测（COCO 80、玩手机、聚集、人脸识别、车牌识别）外，其它场景可：

- **导入现成专模**：训练实验室上传社区 YOLO 权重（见 [detection.md](detection.md#导入现成专模社区--平台权重)）
- **自训专模**：训练实验室标注训练后部署到 `models/specialists/<key>/`

### 2. 配置文件

```bash
cp config/config.example.ini config/config.ini
# 编辑分节： [basic] 密钥、[redis]、[minio]、[email]、[models]、[zlm] 等
```

### 3. 启动 Redis / MinIO / ZLM

```bash
docker compose up -d redis minio zlmediakit
```

默认 Redis：`127.0.0.1:16379`，密码 `VisionAI@2026`。

启用 ZLM 时：

1. `config.ini` → `[zlm] enabled = true`
2. `secret` 与 `config/zlm/config.ini` → `[api] secret` **一致**
3. 宿主机端口：HTTP **18080**，RTSP **18554**，WebRTC **18000**（与当前 `docker-compose.yaml` 一致）
4. 改 secret 后：`docker compose restart zlmediakit`，再重启应用

详见 [configuration.md § ZLMediaKit](configuration.md#zlmediakit-zlm可选)。

### 4. 准备模型（YOLO26）

本项目**统一使用 Ultralytics YOLO26**（文件名是 `yolo26s.pt`，**没有**中间的 `v`）。权重放在 **`models/`**（大文件不入 Git）。

> 配置了路径但文件不存在时，Ultralytics 可能联网下载并卡住。请先放到 `models/` 再启动。

#### 4.1 官方来源与档位

| 来源 | 地址 |
|------|------|
| 模型说明 | https://docs.ultralytics.com/models/yolo26/ |
| 权重 Release | https://github.com/ultralytics/assets/releases/tag/v8.4.0 |
| 直链模板 | `https://github.com/ultralytics/assets/releases/download/v8.4.0/<文件名>` |
| 国内镜像示例 | `https://gh-proxy.com/https://github.com/ultralytics/assets/releases/download/v8.4.0/<文件名>` |

**检测（主检 `yolo_model`）**

| 档位 | 文件 | 约体积 | 说明 |
|------|------|--------|------|
| n | [yolo26n.pt](https://github.com/ultralytics/assets/releases/download/v8.4.0/yolo26n.pt) | 5 MB | 最快 / 精度最低 |
| s | [yolo26s.pt](https://github.com/ultralytics/assets/releases/download/v8.4.0/yolo26s.pt) | 20 MB | **默认**，平衡 |
| m | [yolo26m.pt](https://github.com/ultralytics/assets/releases/download/v8.4.0/yolo26m.pt) | 43 MB | 更高精度 |
| l | [yolo26l.pt](https://github.com/ultralytics/assets/releases/download/v8.4.0/yolo26l.pt) | 51 MB | 精度优先 |
| x | [yolo26x.pt](https://github.com/ultralytics/assets/releases/download/v8.4.0/yolo26x.pt) | 114 MB | 最高精度 / 最慢 |

**姿态（`pose_model`，玩手机辅助）**：`yolo26n-pose.pt` … `yolo26x-pose.pt`；项目默认 `yolo26s-pose.pt`。

#### 4.2 下载

```bash
./scripts/download_yolo26.sh
# MODELS="n s" ./scripts/download_yolo26.sh
# DOWNLOAD_POSE=1 ./scripts/download_yolo26.sh
```

#### 4.3 切换档位

```ini
[models]
yolo_model = models/yolo26m.pt
pose_model = models/yolo26s-pose.pt
```

Compose：`docker compose restart visionai-api visionai-worker visionai-alert`  
宿主机：`./stop.sh && ./start.sh`

#### 4.4 默认需要的权重

| 文件 | 用途 | 配置项 |
|------|------|--------|
| `models/yolo26s.pt`（或 n/m/l/x） | 主检测 COCO 80 | `[models] yolo_model` |
| `models/yolo26s-pose.pt` | 玩手机姿态辅助 | `[models] pose_model` |

#### 4.5 人脸识别（可选）

将 InsightFace **buffalo_l** 解压到 `models/buffalo_l/`（`det_10g.onnx`、`w600k_r50.onnx`、可选 `genderage.onnx`）。

#### 4.6 内置扩展与训练专模

| 能力 | 说明 |
|------|------|
| 玩手机 | `pose_model`（默认 `models/yolo26s-pose.pt`） |
| 人员聚集 | 仅依赖 YOLO26 人物框 |
| 人脸识别 | `models/buffalo_l/` |
| 车牌识别 | `models/specialists/plate/` + RapidOCR |
| 其它检测 | 训练实验室自训/导入 → `models/specialists/<key>/` |

打电话能力已下线；需要时自训/导入专模。权重**不入 Git**。

### 5. 启动应用（宿主机）

```bash
./start.sh
```

会拉起：`alert_worker` + `visionai.worker` + `visionai.api`（Web **:5000**）；可选 inferd。

健康检查：`curl -s http://127.0.0.1:5000/healthz` · `curl -s http://127.0.0.1:5000/readyz`

- 管理端：<http://服务器IP:5000>
- 停止：`./stop.sh`
- 日志：`logs/visionai.log`、`logs/worker.log`、`logs/alert_worker.log`

`start.sh` 本机友好环境变量示例：`REDIS_HOST=127.0.0.1`、`REDIS_PORT=16379`、`S3_ENDPOINT_URL=http://127.0.0.1:19000`（以脚本实际 export 为准）。

---

## 下一步

- [系统架构](architecture.md)
- [配置说明](configuration.md)
- [使用指南](user-guide.md)
- [运维与排障](operations.md)
