# 配置说明

**优先级**：环境变量 → `config/config.ini`（`[visionai]` 段，键**小写**）→ `visionai/config/settings.py` 内置默认。

修改 `config.ini` 或环境变量后须 **`./stop.sh && ./start.sh` 重启**。也可用 `VISIONAI_CONFIG` 指定其它 ini 路径。

---

## 常用配置项

| ini 键 / 环境变量 | 含义 | 默认 |
|-------------------|------|------|
| `visionai_secret` / `VISIONAI_SECRET` | 管理端登录密钥 | 见 example |
| `detection_interval` | 检测间隔（秒），越小越频繁 | 15 |
| `conf_threshold` | YOLO 主检测置信度 | 0.5 |
| `save_dir` / `SAVE_DIR` | 截图目录 | `./snapshots` |
| `save_interval` | 两次截图最小间隔（秒） | 10 |
| `yolo_model` | YOLO 主模型路径 | `models/yolov8n.pt` |
| `yolo_device` | 推理设备：空=自动，`cpu`，`0` | 自动 |
| `pose_model` | 姿态模型（打电话/玩手机） | `models/yolov8n-pose.pt` |
| `onnx_provider` | ONNX：`cpu` 或 `cuda_first` | `cpu` |
| `redis_host` / `REDIS_HOST` | Redis 主机 | 见 ini |
| `redis_port` / `REDIS_PORT` | Redis 端口 | 6379 / 16379 |
| `detection_retention_days` | 检测记录 Redis TTL（天） | 1 |
| `face_recognition_threshold` | 人脸相似度阈值 | 0.45 |
| `face_recognition_min_duration_sec` | 人脸持续时长防抖（秒） | 2.0 |
| `face_recog_rotate` | 全局默认画面旋转（0/90/180/270） | 0 |
| `face_recog_genderage_enabled` | 性别年龄**全局总开关**（按流还需在检测类型配置勾选） | true |
| `smtp_*` | 全局邮件告警 SMTP | 默认关 |

完整字段与 Web「系统设置」页同步，模板见 `config/config.example.ini`。

---

## 对象存储（可选）

```ini
object_storage_enabled = true
s3_endpoint_url = http://127.0.0.1:9000
s3_access_key_id = minioadmin
s3_secret_access_key = minioadmin
s3_bucket = visionai
object_storage_keep_local = true
```

`object_storage_keep_local=true` 时本地仍保留截图副本。历史告警图片可通过 `/api/alert-image/<id>` 从 S3 回源。

人脸库照片也依赖对象存储，详见 [使用指南 - 人脸识别](user-guide.md#人脸识别)。
