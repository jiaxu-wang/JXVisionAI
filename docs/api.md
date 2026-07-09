# HTTP API

以下接口均需登录（管理端 Session）。

---

## 流与检测

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/api/streams` | 流列表（含 `detections`、`face_recognition_config`） |
| `POST` | `/api/streams` | 保存流配置到 Redis |
| `GET` | `/api/stream-status` | 各流在线状态 |
| `GET` | `/api/detection-catalog` | 可配置的检测类型目录 |
| `GET` | `/api/detections` | 历史记录（支持时间/流/类型/分页） |
| `DELETE` | `/api/detections/<id>` | 删除单条记录 |

---

## 人脸库

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/face-library` | 人脸库管理页面 |
| `GET/POST` | `/api/face-library` | 列表 / 录入 |
| `GET/PUT/DELETE` | `/api/face-library/<person_id>` | 查询 / 更新 / 删除 |
| `GET` | `/api/face-library/<person_id>/photo` | 人员照片 |
| `POST` | `/api/face-library/reload` | 重新加载索引 |

---

## 系统与预览

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET/PUT` | `/api/system/config` | 读取/保存 `config.ini` |
| `GET` | `/api/config` | 运行时配置摘要（含预览能力） |
| `POST` | `/api/restart` | 重启服务（依赖 `start.sh` 布局） |
| `GET` | `/api/preview` | MJPEG 预览 |
| `WS` | `/ws/preview` | WebSocket 预览 |
| `POST` | `/api/preview-webrtc/*` | WebRTC 信令 |
| `GET` | `/api/alert-image/<id>` | 告警截图（S3 回源） |

训练实验室 API 见 `/training` 页面与 `jxvisionai/web/training_routes.py`。
