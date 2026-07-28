# 配置说明

**优先级**：环境变量 → `config/config.ini`（**多分节**）→ `visionai/config/settings.py` 内置默认。

修改 `config.ini` 或环境变量后须 **`./stop.sh && ./start.sh` 重启**。也可用 `VISIONAI_CONFIG` 指定其它 ini 路径。

---

## 分节结构

模板见 `config/config.example.ini`。推荐按职责分节（节内可用短键）：

| 节 | 说明 | 示例键 |
|----|------|--------|
| `[basic]` | 登录密钥、检测间隔、截图/日志目录、设备选择 | `visionai_secret`、`detection_interval`、`save_dir` |
| `[redis]` | Redis 连接 | `host`、`port`、`password`、`db`、`key_prefix` |
| `[minio]` | MinIO / S3 兼容对象存储 | `enabled`、`endpoint_url`、`access_key_id`、… |
| `[email]` | 全局 SMTP 告警邮件 | `alert_enabled`、`host`、`port`、`user`、… |
| `[models]` | YOLO 主模型、姿态、打电话（make_call）、人脸识别等；**训练专模不在 ini 中** | `yolo_model`、`pose_model`、`make_call_model_path`、`face_recog_det_model_path`、… |
| `[preview]` | 流预览（可选） | `preview_hls_enabled`、… |

**兼容**：旧版单节 `[visionai]`（键为规范全名，如 `redis_host`、`smtp_host`）仍可读取。

环境变量仍用规范全名大写，例如 `REDIS_HOST`、`S3_ENDPOINT_URL`、`SMTP_HOST`。

---

## 常用配置项

| 规范键 / 环境变量 | ini 位置（推荐） | 含义 | 默认 |
|-------------------|------------------|------|------|
| `visionai_secret` / `VISIONAI_SECRET` | `[basic]` | 管理端登录密钥 | 见 example |
| `detection_interval` | `[basic]` | 检测间隔（秒）；代码默认 **15**，`config.example.ini` 示例可能为 `1` | 15 |
| `conf_threshold` | `[basic]` | YOLO 主检测置信度 | 0.5 |
| `save_dir` / `SAVE_DIR` | `[basic]` | 截图目录 | `./snapshots` |
| `yolo_model` | `[models]` | YOLO 主模型路径（YOLO26） | `models/yolo26s.pt` |
| `inference_device` | `[basic]` | **总开关** `cpu` / `gpu`（YOLO+ONNX，改完重启） | `gpu` |
| `yolo_device` | `[basic]` | 总开关留空时：空=自动，`cpu`，`0` | 自动 |
| `pose_model` | `[models]` | 姿态模型（YOLO26-pose） | `models/yolo26s-pose.pt` |
| `onnx_provider` | `[basic]` | 总开关留空时：`cpu` 或 `cuda_first`/`gpu` | `cpu` |
| `redis_host` / `REDIS_HOST` | `[redis]` → `host` | Redis 主机 | 见 ini |
| `redis_port` / `REDIS_PORT` | `[redis]` → `port` | Redis 端口 | 6379 / 16379 |
| `detection_retention_days` | `[basic]` | 检测记录 Redis TTL（天） | 1 |
| `face_recog_det_model_path` | `[models]` | buffalo_l 检测 | `models/buffalo_l/det_10g.onnx` |
| `face_recognition_threshold` | `[models]` | 人脸相似度阈值 | 0.45 |
| `smtp_*` | `[email]` 短键 | 全局邮件告警 SMTP | 默认关 |

完整字段与 Web「系统设置」页同步。

---

## 推理设备：`inference_device` 与分项配置

`[basic]` 中 **`inference_device = cpu | gpu`** 为 **总开关**，同时影响 YOLO（Ultralytics）与 ONNX（人脸、专模等）。修改后须 **重启**。

| 场景 | 行为 |
|------|------|
| 已设置 `inference_device` | YOLO 走 CPU 或 GPU（`0`）；ONNX 走 `CPUExecutionProvider` 或 `CUDAExecutionProvider` |
| 未设置 `inference_device` | 可分别用 `yolo_device`（空/`cpu`/`0`）与 `onnx_provider`（`cpu` / `cuda_first`）细调 |

**依赖**：GPU 推理 ONNX 须安装 **`onnxruntime-gpu`**（见 `requirements.txt`）；纯 CPU 环境可改为 `onnxruntime`。人脸识别与专模 ONNX 共用同一 provider 策略。

**训练专模**：部署到 `models/specialists/<key>/` 的权重与阈值在 **`specialist.json`** 中维护，**不在** `[models]` 分节为每项单独写路径（`make_call` 除外）。

---

## 对象存储（可选）

```ini
[minio]
enabled = true
endpoint_url = http://127.0.0.1:9000
access_key_id = minioadmin
secret_access_key = minioadmin
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

每路收件人与是否发信仍在 Redis 流配置（事件监控）中设置。
