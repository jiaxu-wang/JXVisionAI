# HTTP API

以下接口均需登录（管理端 Session）。

---

## 流与检测

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/api/streams` | 流列表（含 `detections`、`analyze`、`access_method`、`face_recognition_config`、`plate_recognition_config`、`status`=`online`/`offline`；未登录返回 **401 JSON**） |
| `POST` | `/api/streams` | 保存流配置到 Redis |
| `PATCH` | `/api/streams/<stream_id>` | 更新单路（`name` / `url` / `enabled` / **`analyze`** / ONVIF 元数据） |
| `DELETE` | `/api/streams/<stream_id>` | 删除流；国标会尝试 BYE |
| `GET` | `/api/stream-status` | 各流在线状态（Redis `{prefix}stream_runtime_status`，worker 心跳） |
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
| `GET/POST` | `/api/face-library` | 列表 / 录入（列表含 `threshold`） |
| `POST` | `/api/face-library/compare` | 1:1 手动比对：multipart 探测图 `photo`，必填 `person_id`（已录入人员），可选 `threshold` / `top_k` |
| `POST` | `/api/face-library/compare-stream` | 对当前在线流截帧后与指定人员 1:1 比对（JSON：`stream_id`、`person_id`，可选 `threshold` / `top_k`） |
| `GET/PUT/DELETE` | `/api/face-library/<person_id>` | 查询 / 更新 / 删除 |
| `GET` | `/api/face-library/<person_id>/photo` | 人员照片 |
| `POST` | `/api/face-library/reload` | 重新加载索引 |

---

## 车牌库

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/plate-library` | 车牌库管理页面 |
| `GET/POST` | `/api/plate-library` | 列表 / 录入（JSON：`plate_no`、`name`、`note`） |
| `GET/PUT/DELETE` | `/api/plate-library/<plate_no>` | 查询 / 更新 / 删除 |
| `POST` | `/api/plate-library/reload` | 重新加载索引 |

---

## 系统与预览

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/healthz` | 存活探针（无需登录） |
| `GET` | `/readyz` | 就绪探针：Redis + 可选 ZLM/inferd（无需登录） |
| `GET` | `/api/metrics` | 运行指标：`uptime_sec`、`alert_queue_depth`、`stream_status`（Redis）；每路 `frames`/`detects` 等为 **API 进程本地**计数（拆分进程时可能为空，以 worker 日志为准） |
| `GET` | `/api/zlm/status` | ZLM：`alive` / `reachable` / `auth_ok`、`message`、各流代理与播放地址 |
| `POST` | `/api/zlm/ensure-proxy` | 建立/复用拉流代理，返回 `play`（hls/webrtc/…） |
| `POST` | `/api/zlm/webrtc/play` | **流预览**：ZLM WebRTC play；body `{stream_id,sdp}`，返回 answer `sdp` |
| `POST` | `/api/zlm/webrtc/push` | **喊话推流**：ZLM WebRTC push；body `{app,stream,sdp}` |
| `GET/PUT` | `/api/system/config` | 读取/保存 `config.ini` |
| `GET` | `/api/config` | 运行时配置摘要（含 `preview.zlm_webrtc_enabled`） |
| `POST` | `/api/restart` | 默认 **403**。Compose 请用 `docker compose restart`；宿主机需显式 `VISIONAI_ALLOW_PROCESS_RESTART=1` |
| `GET` | `/api/alert-image/<id>` | 告警截图（S3 回源） |

---

## 训练实验室 / 专模

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/api/training/specialists` | 已部署专模列表（key、名称、kind、origin、路径等） |
| `POST` | `/api/training/specialists/inspect` | **multipart** 上传权重预检类别（字段 `file`；不落盘为专模） |
| `POST` | `/api/training/specialists/import` | **multipart** 导入现成专模（见下表） |
| `DELETE` | `/api/training/specialists/<key>` | 删除专模目录并从流配置中移除该检测键 |
| `POST` | `/api/training/projects/<pid>/deploy` | 训练项目 **一键部署**（专模 → `models/specialists/<key>/`） |

### 导入现成专模 `POST /api/training/specialists/import`

`multipart/form-data`：

| 字段 | 必填 | 说明 |
|------|------|------|
| `file` | 是 | `.pt` / `.onnx`（Ultralytics YOLO detect） |
| `key` | 是 | 专模键名 |
| `kind` | 否 | `person_event`（默认）/ `violation` / `scene` |
| `name_zh` / `name_en` | 否 | 显示名 |
| `classes` | 否 | 逗号分隔类别名；空则从权重读取 |
| `conf` / `score_threshold` / `min_duration_sec` | 否 | 阈值 |
| `positive_class_ids` | 否 | person_event 告警类，默认 `0` |
| `subject_class_ids` / `comply_class_ids` | 否 | violation 违规/合规类，默认 `0` / `1` |
| `class_ids` | 否 | scene 过滤类 |
| `needs_persons` | 否 | `true`/`false`，默认 true |

成功后热加载插件，一般无需重启。操作说明见 [detection.md](detection.md#导入现成专模社区--平台权重)。

完整训练实验室接口（项目、采图、标注、训练任务、验证、快照回流等）见 `/training` 页面与 `visionai/web/training_routes.py`。

---

## 开放集成（机对机，无需 Session）

鉴权：请求头 `X-Api-Key` 对应 `[integration] open_api_key`（或环境变量 `OPEN_API_KEY`）。密钥未配置或错误时返回 **401 JSON** `{"success":false,"message":"..."}`，**不会** 302 到登录页。

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/api/open/v1/streams` | 仅 `analyze=true` 的流：`id/name/status/online/access_method/play_rtsp/play_hls/zlm_app/zlm_stream`。国标 `zlm_app=rtp`，RTSP/ONVIF 为 `jvai` |
| `GET` | `/api/open/v1/alerts/<id>/image` | 告警截图；`X-Api-Key` 或查询参数 `token`（HMAC，见 webhook `image_url`） |
| `POST` | `/api/open/v1/zlm/ensure-proxy` | body `{stream_id}`：RTSP 建/复用拉流代理；国标只返回已有 `rtp` 播放地址 |

告警 Webhook（`event=visionai.alert`）在原有字段上增加绝对 `image_url`。全局 `[integration] outbound_webhook_url` 与每路 `alert_webhook_urls` 合并去重；未开每路开关时仍会投递全局 URL。

对接步骤见 [integration.md](integration.md)。

### 管理页嵌入（可选）

第三方控制台可用 `X-Api-Key` 调用 `POST /api/open/v1/embed-token`，得到一次性 `embed_url`（默认 60 秒、用一次即作废）。浏览器打开 `/embed?token=` 后写入与普通登录相同的 Session。

`[integration] embed_frame_ancestors` 填对接方页面的源（空格或逗号分隔），进程会下发 `Content-Security-Policy: frame-ancestors 'self' …`。空则不写 CSP。HTTP 局域网下 Chrome 可能拦 iframe 第三方 Cookie，这时用新窗口打开同一地址即可。

---

## 国标 GB/T 28181

均需登录。Invite / BYE / Catalog / PTZ 由 API 写入 Redis 命令队列，`visionai-sip` 执行。说明见 [gb28181.md](gb28181.md)。

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` / `PUT` | `/api/gb28181/platform` | 平台参数（SIP 信令 + 媒体收流）；GET 含 `sip_ready` |
| `GET` | `/api/gb28181/devices` | SIP 账号列表（在线状态来自 sip runtime；不含分析徽章） |
| `POST` | `/api/gb28181/devices` | 新建账号（可自动分配 SIP 用户/认证 ID） |
| `PATCH` / `DELETE` | `/api/gb28181/devices/<device_id>` | 改账号 / 删除整行 SIP 账号 |
| `POST` | `/api/gb28181/refresh-status` | 刷新在线状态展示 |
| `GET` | `/api/gb28181/preview-ids` | 预览下一次自动分配的编码（不落库） |
| `GET` / `POST` | `/api/gb28181/devices/<device_id>/channels` | 通道列表 / 新增通道 |
| `PATCH` / `DELETE` | `/api/gb28181/devices/<device_id>/channels/<channel_id>` | 改别名等 / 删通道 |
| `POST` | `…/channels/<channel_id>/preview` | 点播预览（不写入检测配置；已接入分析则复用） |
| `POST` | `…/channels/<channel_id>/ptz` | **云台**：body `{action, speed?}`；`action` 为方向/变倍/聚焦/光圈/`stop`；`visionai-sip` 发 DeviceControl |
| `POST` | `…/channels/<channel_id>/broadcast` | **喊话开始**：body `{app?, stream?}`；先 WebRTC push 再 Broadcast Notify |
| `POST` | `…/channels/<channel_id>/broadcast/stop` | **喊话停止**：BYE + stopSendRtp |
| `POST` | `…/channels/<channel_id>/bye` | 结束点播（已接入分析的通道通常不 BYE） |
| `POST` | `…/channels/<channel_id>/monitor` | **接入分析**：Invite + 写入 streamlist（`analyze: true`） |
