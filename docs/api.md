# HTTP API

以下接口均需登录（管理端 Session）。

---

## 流与检测

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/api/streams` | 流列表（含 `detections`、`face_recognition_config`） |
| `POST` | `/api/streams` | 保存流配置到 Redis |
| `GET` | `/api/stream-status` | 各流在线状态 |
| `POST` | `/api/onvif/discover` | 局域网 WS-Discovery（body: `timeout_sec?`） |
| `POST` | `/api/onvif/probe` | 探测设备（`host/port/username/password`） |
| `POST` | `/api/onvif/profiles` | 列举 Profile 与 RTSP URI |
| `POST` | `/api/onvif/add-stream` | 追加一路流到 Redis（`name` + `rtsp_url` + 可选 `onvif` 元数据） |
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
| `GET` | `/api/preview` | MJPEG 预览（仅画面） |
| `WS` | `/ws/preview` | WebSocket JPEG 预览（仅画面） |
| `POST` | `/api/preview-hls/start` | 启动 HLS（可含音频）；返回 `playlist`、`audio` |
| `POST` | `/api/preview-hls/stop` | 停止 HLS 会话 |
| `GET` | `/api/preview-hls/data/<session>/<file>` | HLS 分片 / m3u8 |
| `POST` | `/api/preview-webrtc/*` | WebRTC 信令（可选） |
| `GET` | `/api/alert-image/<id>` | 告警截图（S3 回源） |

---

## 训练实验室 / 专模

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/api/training/specialists` | 已部署专模列表（key、名称、kind、路径等） |
| `DELETE` | `/api/training/specialists/<key>` | 删除专模目录并从流配置中移除该检测键 |
| `POST` | `/api/training/projects/<pid>/deploy` | 训练项目 **一键部署**（专模 → `models/specialists/<key>/`；`make_call` 走内置路径） |

完整训练实验室接口（项目、采图、标注、训练任务、验证、快照回流等）见 `/training` 页面与 `visionai/web/training_routes.py`。
