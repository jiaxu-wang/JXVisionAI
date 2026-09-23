# 配置说明

**优先级**：环境变量 → `config/config.ini`（**多分节**）→ `visionai/config/settings.py` 内置默认。

修改 `config.ini` 或环境变量后须重启应用：  
- **Compose**：管理端「系统设置 → 重启服务」按钮（`VISIONAI_RESTART_MODE=exit`，写 Redis 信号后各容器进程退出、由 Docker `restart: unless-stopped` 拉起，约 10~30 秒）；或命令行 `docker compose restart visionai-api visionai-worker visionai-alert` / `./scripts/install_linux.sh restart`
- **宿主机**：`./stop.sh && ./start.sh`（页面重启需显式 `VISIONAI_ALLOW_PROCESS_RESTART=1`）  

也可用 `VISIONAI_CONFIG` 指定其它 ini 路径。

---

## 分节结构

模板见 `config/config.example.ini`。推荐按职责分节（节内可用短键）：

| 节 | 说明 | 示例键 |
|----|------|--------|
| `[basic]` | 登录密钥、时区、检测间隔、截图/日志目录、设备选择 | `visionai_secret`、`timezone`、`detection_interval`、`save_dir` |
| `[redis]` | Redis 连接 | `host`、`port`、`password`、`db`、`key_prefix` |
| `[minio]` | MinIO / S3 兼容对象存储 | `enabled`、`endpoint_url`、`access_key_id`、… |
| `[email]` | 全局 SMTP 告警邮件 | `alert_enabled`、`host`、`port`、`user`、… |
| `[models]` | YOLO 主模型、姿态、人脸、车牌 OCR 等；**训练专模不在 ini** | `yolo_model`、`pose_model`、… |
| `[infer]` | 主检后端：`python`（默认）或 `cpp`（visionai-inferd） | `backend`、`endpoint`、`on_daemon_error` |
| `[preview]` | 检测框标签字号（流预览仅 ZLM WebRTC） | `label_font_px`、… |
| `[zlm]` | ZLMediaKit 媒体面（可选） | `enabled`、`api_base`、`secret`、`fallback_direct_rtsp`、… |
| `[integration]` | 开放 API、全局告警 Webhook、侧栏「平台接入」嵌入页 | `open_api_key`、`outbound_webhook_url`、`platform_embed_url` |
| `[ui]` | 管理端默认语言；告警 webhook/邮件的类型展示名也用此值。浏览器已选语言时管理端以 localStorage 为准，推送仍读 ini | `language`（`zh` / `en`） |

**兼容**：旧版单节 `[visionai]`（键为规范全名，如 `redis_host`、`smtp_host`）仍可读取。

环境变量仍用规范全名大写，例如 `REDIS_HOST`、`S3_ENDPOINT_URL`、`SMTP_HOST`。

---

## 常用配置项

| 规范键 / 环境变量 | ini 位置（推荐） | 含义 | 默认 |
|-------------------|------------------|------|------|
| `visionai_secret` / `VISIONAI_SECRET` | `[basic]` | 管理端登录密钥 | 见 example |
| `timezone` / `VISIONAI_TIMEZONE` | `[basic]` | 应用时区（IANA，告警落库与历史页）；也可用 `TZ` | `Asia/Shanghai` |
| `detection_interval` | `[basic]` | 两轮检测的间隔（秒）；代码默认 **15**，`config.example.ini` 示例可能为 `1` | 15 |
| `detect_burst_duration_ms` | `[basic]` | 一轮采样窗（毫秒）；`0` 关闭多帧 | 500 |
| `detect_burst_frames` | `[basic]` | 一轮最多抽几帧推理；`1` 关闭多帧 | 15 |
| `detect_burst_min_frames` | `[basic]` | 实际抽到少于此值则跳过本轮 | 1 |
| `detect_burst_hit_ratio` | `[basic]` | 类型阳性帧占比阈值（0~1） | 0.4 |
| `conf_threshold` | `[basic]` | YOLO 主检测置信度 | 0.5 |
| `save_dir` / `SAVE_DIR` | `[basic]` | 截图目录 | `./snapshots` |
| `yolo_model` | `[models]` | YOLO26 主检：`yolo26n/s/m/l/x.pt`，改完重启 | `models/yolo26s.pt` |
| `inference_device` | `[basic]` | **总开关** `cpu` / `gpu`（YOLO+ONNX，改完重启） | `gpu` |
| `yolo_device` | `[basic]` | 总开关留空时：空=自动，`cpu`，`0` | 自动 |
| `pose_model` | `[models]` | 姿态模型（YOLO26-pose） | `models/yolo26s-pose.pt` |
| `onnx_provider` | `[basic]` | 总开关留空时：`cpu` 或 `cuda_first`/`gpu` | `cpu` |
| `redis_host` / `REDIS_HOST` | `[redis]` → `host` | Redis 主机 | 见 ini |
| `redis_port` / `REDIS_PORT` | `[redis]` → `port` | Redis 端口 | 6379 / 16379 |
| `detection_retention_days` | `[basic]` | 检测记录 Redis TTL（天） | 1 |
| `face_recog_det_model_path` | `[models]` | buffalo_l 检测 | `models/buffalo_l/det_10g.onnx` |
| `face_recognition_threshold` | `[models]` | 人脸相似度阈值 | 0.45 |
| `plate_recognition_min_duration_sec` | `[models]` | 车牌识别持续秒数 | 1.0 |
| `plate_recognition_ocr_min_conf` | `[models]` | 车牌 OCR 最低置信度 | 0.35 |
| `smtp_*` | `[email]` 短键 | 全局邮件告警 SMTP | 默认关 |
| `label_font_px` | `[preview]` | 检测框标签字号（像素）；`>0` 固定，`0` 按短边×ratio | 0（自动） |
| `label_font_min_px` / `max_px` / `ratio` | `[preview]` | 自动字号下限/上限/短边比例 | 36 / 72 / 0.05 |
| `zlm_enabled` | `[zlm]` → `enabled` | 经 ZLMediaKit 代理后再本地取流；管理端预览为 ZLM WebRTC | false |
| `zlm_api_base` / `secret` | `[zlm]` | ZLM HTTP API；**secret 须与 `config/zlm/config.ini` 一致** | 见下节 |
| `zlm_fallback_direct_rtsp` | `[zlm]` → `fallback_direct_rtsp` | 代理失败时直连摄像机 RTSP | true |
| `ui_language` | `[ui]` → `language` | 管理端首次访问默认语言，以及告警推送类型展示名 `zh`/`en`（顶栏切换只改浏览器缓存，不改推送） | `zh` |
| `STREAM_LEASE_ENABLED` | 环境变量 | 多 worker 流租约 HA | false |

完整字段与 Web「系统设置」页同步。

生产请修改默认 `visionai_secret`；HTTPS 反代见 [`deploy/nginx.example.conf`](../deploy/nginx.example.conf)。多节点见 [ha.md](ha.md)。

---

## 推理设备：`inference_device` 与分项配置

`[basic]` 中 **`inference_device = cpu | gpu`** 为 **总开关**，同时影响 YOLO（Ultralytics）与 ONNX（人脸、专模等）。修改后须 **重启**。

| 场景 | 行为 |
|------|------|
| 已设置 `inference_device` | YOLO 走 CPU 或 GPU（`0`）；ONNX 走 `CPUExecutionProvider` 或 `CUDAExecutionProvider` |
| 未设置 `inference_device` | 可分别用 `yolo_device`（空/`cpu`/`0`）与 `onnx_provider`（`cpu` / `cuda_first`）细调 |

**依赖**：GPU 推理 ONNX 须安装 **`onnxruntime-gpu`**（见 `requirements.txt`）；纯 CPU 环境可改为 `onnxruntime`。人脸识别与专模 ONNX 共用同一 provider 策略。

**训练专模**：部署到 `models/specialists/<key>/` 的权重与阈值在 **`specialist.json`** 中维护，**不在** `[models]` 为每项单独写路径。

---

## 切换 YOLO26 档位（n/s/m/l/x）

```ini
[models]
yolo_model = models/yolo26s.pt   # 改为 yolo26n / m / l / x.pt
```

文件须已在 `models/`（可用 `./scripts/download_yolo26.sh`）。改完重启应用（Compose：`visionai-api` / `visionai-worker` / `visionai-alert`，或 `./stop.sh && ./start.sh`）。对比精度时固定 `conf_threshold` 与同一路视频。详见 [getting-started.md §4](getting-started.md)。

---

## 主检后端 `[infer]`（可选）

| 键 | 含义 | 默认 |
|----|------|------|
| `backend` | `python` = Ultralytics；`cpp` = `visionai-inferd` | `python` |
| `endpoint` | 同机 UDS | `unix:///tmp/visionai-inferd.sock` |
| `on_daemon_error` | `fail` 或 `fallback_python` | `fail` |

`backend=cpp` 时 `start.sh` 会拉起 `native/inferd` 中的可执行文件；需已构建且 `models/repo/primary/` 有 ONNX。日常对比精度用 `python` 后端改 `yolo_model` 即可。构建说明见 [`native/inferd/README.md`](../native/inferd/README.md)。

---

## ZLMediaKit `[zlm]`（可选）

经 ZLM 拉流代理后，worker 从本机 RTSP 取流；管理端预览走 ZLM WebRTC。需先 `docker compose up -d zlmediakit`。

| 键 | 含义 | 默认 / 说明 |
|----|------|-------------|
| `enabled` | 是否启用媒体面 | `false` |
| `api_base` | ZLM HTTP API | 宿主机常用 `http://127.0.0.1:18080`；Compose 应用容器内用 `http://zlmediakit:80` |
| `secret` | API 密钥 | **须与** `config/zlm/config.ini` → `[api] secret` **一致** |
| `rtsp_port` / `http_port` | 宿主机回源 RTSP / 播放 HTTP（映射） | **18554** / **18080**（容器内为 554 / 80） |
| `rtc_port` | WebRTC ICE 端口（compose 映射 `18000→8000`） | 宿主机 **18000** |
| `prefer_local_pull` | 优先经代理取流 | `true` |
| `fallback_direct_rtsp` | 代理失败回退直连摄像机 | `true` |
| `public_host` | 浏览器播放 URL / WebRTC `cand_udp` 主机名 | `127.0.0.1` 或局域网 IP |

WebRTC 预览：管理端「预览」→ **ZLM WebRTC**；信令走 `POST /api/zlm/webrtc/play`，媒体走宿主机 ZLM **`:18000`**。改端口或 secret 后需重启 `zlmediakit` 与应用。

**重要**：勿使用 ZLM 出厂默认 secret（`035c73f7-…`）。Docker 端口映射后源 IP 不是 `127.0.0.1`，**必须**带正确 secret。项目模板使用非默认值（如 `jxvisionai-zlm-…`）；改 secret 后须 **`docker compose restart zlmediakit`** 并重启应用。

自检：`curl -s http://127.0.0.1:15000/readyz`（Compose）或 `:5000`（宿主机 `./start.sh`）；登录后 `GET /api/zlm/status`。

---

## 对象存储（可选）

```ini
[minio]
enabled = true
endpoint_url = http://127.0.0.1:9000
access_key_id =
secret_access_key =
bucket = visionai
keep_local = true
```

`keep_local=true`（规范键 `object_storage_keep_local`）时本地仍保留截图副本。历史告警图片可通过 `/api/alert-image/<id>` 从 S3 回源。

人脸库照片也依赖对象存储，详见 [使用指南 - 人脸识别](user-guide.md#人脸识别)。

---

## 邮件（可选）

```ini
[email]
alert_enabled = true
host = smtp.example.com
port = 465
use_ssl = true
use_tls = false
user = you@example.com
password = your_auth_code
from = you@example.com
```

每路收件人与是否发信仍在 Redis 流配置（**检测配置**页）中设置。

国标 SIP / 媒体 / 账号不在 `config.ini`，由管理端写入 Redis，见 [gb28181.md](gb28181.md)。
