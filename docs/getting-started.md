# 快速开始

## 环境要求

- **Python** 3.10+（推荐 3.10/3.12）
- **Redis** 7+（流配置与检测记录）
- **可选**：MinIO 或 S3 兼容对象存储；**ZLMediaKit**（`docker compose up -d zlmediakit`，`[zlm] enabled=true`，管理端 WebRTC 预览）
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

除内置检测（COCO 80、打电话、玩手机、聚集、人脸识别）外，其它场景可：

- **导入现成专模**：训练实验室上传社区 YOLO 权重（见 [detection.md](detection.md#导入现成专模社区--平台权重)）
- **自训专模**：训练实验室标注训练后部署到 `models/specialists/<key>/`

详见 [检测与模型](detection.md)。

---

## 2. 配置文件

```bash
cp config/config.example.ini config/config.ini
# 编辑分节： [basic] 密钥、[redis]、[minio]、[email]、[models] 等
```

---

## 3. 启动 Redis / MinIO /（可选）ZLM

```bash
docker compose up -d redis minio          # 常用依赖
# 可选媒体面（预览/本地回源）：
docker compose up -d zlmediakit
```

```bash
docker compose up -d redis                # 仅 Redis
# 或
docker compose up -d                      # Redis + MinIO + zlmediakit（若已定义）
```

默认 Redis：`127.0.0.1:16379`，密码 `VisionAI@2026`（见 `docker-compose.yaml`）。

启用 ZLM 时：

1. `config.ini` → `[zlm] enabled = true`
2. `secret` 与 `config/zlm/config.ini` → `[api] secret` **一致**（勿用 ZLM 出厂默认 UUID）
3. 端口：HTTP API/播放 `8080`，本地回源 RTSP `8554`
4. 改 secret 后执行 `docker compose restart zlmediakit`，再 `./stop.sh && ./start.sh`

详见 [configuration.md § ZLMediaKit](configuration.md#zlmediakit-zlm可选)。

---

## 4. 准备模型（YOLO26）

本项目**统一使用 Ultralytics YOLO26**（文件名是 `yolo26s.pt`，**没有**中间的 `v`，不要写成 `yolov26s.pt`）。权重放在 **`models/`**（大文件不入 Git）。

> 配置了路径但文件不存在时，Ultralytics 可能联网下载并卡住。请先放到 `models/` 再启动。

### 4.1 官方来源与档位

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

**姿态（`pose_model`，打电话/玩手机）**：`yolo26n-pose.pt` … `yolo26x-pose.pt`（同 Release）；项目默认 `yolo26s-pose.pt`。

官方 COCO mAP（仅作参考，现场效果因场景而异）：n≈40.9 → s≈48.6 → m≈53.1 → l≈55.0 → x≈57.5（mAP50-95）。

### 4.2 下载到本项目

**一键脚本（推荐）**

```bash
cd /path/to/JXVisionAI
# 下载 n/s/m/l/x 到 models/
./scripts/download_yolo26.sh
# 只要 n 和 s：MODELS="n s" ./scripts/download_yolo26.sh
# 连带姿态：DOWNLOAD_POSE=1 ./scripts/download_yolo26.sh
```

**手动 curl**

```bash
mkdir -p models
BASE='https://gh-proxy.com/https://github.com/ultralytics/assets/releases/download/v8.4.0'
for f in yolo26n.pt yolo26s.pt yolo26m.pt yolo26l.pt yolo26x.pt yolo26s-pose.pt; do
  curl -fL --retry 5 -o "models/$f" "$BASE/$f"
done
ls -lh models/yolo26*.pt
```

也可 `YOLO('yolo26m.pt')` 自动下载后 `mv` 进 `models/`，或浏览器打开 Release 页保存。

### 4.3 切换档位对比精度

编辑 `config/config.ini`：

```ini
[models]
# 只改这一行即可对比 n/s/m/l/x（文件须已在 models/）
yolo_model = models/yolo26m.pt
# 姿态可保持 s，或换成同档：models/yolo26m-pose.pt
pose_model = models/yolo26s-pose.pt
```

```bash
./stop.sh && ./start.sh
```

建议：固定同一路 RTSP、`conf_threshold`、检测项，只改 `yolo_model`，在预览/历史告警里对比漏检与误检。更大模型更吃 GPU/显存与每路耗时。

### 4.4 默认需要的权重

| 文件 | 用途 | 配置项 |
|------|------|--------|
| `models/yolo26s.pt`（或 n/m/l/x） | 主检测 COCO 80 | `[models] yolo_model` |
| `models/yolo26s-pose.pt` | 打电话/玩手机姿态 | `[models] pose_model` |

训练专模基座也请用 YOLO26（如 `yolo26s.pt`）。

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

会拉起：`alert_worker`（异步告警）+ `visionai.worker`（拉流检测）+ `visionai.api`（Web :5000）；可选 inferd / compose 依赖。

健康检查：`curl -s http://127.0.0.1:5000/healthz` · `curl -s http://127.0.0.1:5000/readyz`

- 管理端：<http://服务器IP:5000>
- 默认登录密钥：`config.ini` 中 `visionai_secret`（生产务必修改）
- 停止：`./stop.sh`
- 日志：`logs/visionai.log`、`logs/worker.log`、`logs/alert_worker.log`

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
