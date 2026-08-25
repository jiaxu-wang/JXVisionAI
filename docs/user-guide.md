# 使用指南

## 管理端页面

登录后左侧菜单：

| 页面 | 功能 |
|------|------|
| **状态概览** | 各流在线/离线、今日告警数、运行指标、ZLM 状态 |
| **事件监控** | 添加/编辑 RTSP 流、**ONVIF 发现**、检测类型、邮件/Webhook 告警 |
| **历史告警** | 分页查看检测记录与截图 |
| **系统设置** | 在线编辑 `config.ini` 各分节（basic / redis / minio / email / models / infer / zlm / preview） |
| **人脸库管理** | 录入人员、查看照片 |
| **车牌库管理** | 录入车牌号、名称与备注 |
| **训练实验室** | **自训专模**（标注→训→门禁→部署）与 **导入现成专模**（上传社区 YOLO 权重）；上线后均可在检测类型目录勾选 |

### 流在线状态与 ZLM

- **在线/离线**：由 `visionai.worker` 写入 Redis（`{key_prefix}stream_runtime_status`），管理端 API 读取；约 3 分钟无心跳则显示离线。分析在跑但页面全离线时，确认 worker 已重启且 Redis 可达。
- **ZLM**：`[zlm] enabled=true` 且容器正常、secret 正确时，状态概览显示「ZLM 在线 · 代理 …」。若显示「ZLM 鉴权失败」，检查 `config.ini` 与 `config/zlm/config.ini` 的 secret 是否一致并重启 zlmediakit。`fallback_direct_rtsp=true` 时代理失败仍可直连摄像机继续检测。

---

## 添加视频流（事件监控）

1. 点击 **+ 添加视频**，填写名称与 RTSP URL  
   - 密码含 `@` 时需编码为 `%40`（如 `inrico@123` → `inrico%40123`）
2. 点击 **检测类型配置**，勾选需要的检测项（内置项 + 已部署/导入的 **专模**；如「人脸识别」、「未戴眼镜」等）
3. 配置 **邮件告警** / **Webhook**（可选）
4. 点击 **保存配置**
5. 若修改了 `config.ini`（含 `[basic]` **`inference_device`**）或内置模型路径：Compose 执行 `docker compose restart visionai-api visionai-worker visionai-alert`；宿主机执行 `./stop.sh && ./start.sh`（或管理端「重启服务」）。**专模**（自训部署或导入）一般热加载，无需重启

### ONVIF 发现（推荐局域网摄像头）

1. 在 **事件监控** 点击 **ONVIF 发现**
2. **扫描局域网**（依赖 WS-Discovery 组播 `239.255.255.250:3702`），或 **手动填写 IP:端口** 加入列表  
   - Docker 桥接网络下扫描常为空，请用手动 IP，或使用 `network_mode: host`
3. 填写摄像机 ONVIF 用户名/密码，点 **检测选中设备**
4. 状态为 **正常** 后，选择码流 Profile（主/子），确认监控名称，点 **加入监控**  
   - 会直接写入 Redis（生成 RTSP URL），无需再点「保存配置」
5. 之后预览与检测与手填 RTSP 相同

注意：海康/大华等需在摄像机 Web 端开启 ONVIF；探测「正常」要求鉴权成功、具备 Media 能力且能拿到 `rtsp://` URI。

### 国标 28181

1. 确认 `visionai-sip` 已启动（Compose 服务或 `./start.sh`）
2. **设备接入 → 国标 28181**：分别填写「SIP 信令」与「媒体收流」（两组不要混用 IP）
3. 新建 SIP 账号并配置**视频通道编码 ID**
4. 点「复制参数」，按设备国标页逐项填写（服务器 ID/域/地址/端口、用户名/认证 ID/密码、通道编码）
5. 「刷新在线状态」应为在线后，在设备行点 **接入分析**（多通道则进通道列表逐路接入）
6. 跳到「检测配置」后勾选检测类型并保存。已接入且检测开启时，worker 会自动 Invite 点播并保持拉流（断流会重试）。

SIP 监听变更后需重启 `visionai-sip`。WSL2 桥接网络下摄像机往往访问不到容器，请用宿主机可达 IP，或 host/mirrored 网络。

---

## 检测生效时间

- 仅改 Redis 流配置（检测项、告警邮箱等）：**下一检测周期**生效（约 `detection_interval` 秒）
- 改 `config.ini`、更换模型：**必须重启进程**
- 人脸识别首次告警：通常需 **检测间隔 + 持续时长**（如 6s + 2s ≈ 15~30 秒站在镜头前）

---

## 流预览

事件监控 / 状态概览中点击 **预览**，仅使用 **ZLM WebRTC**（低延迟，源有兼容音轨时可听声）。

前置：`[zlm] enabled=true`、secret 正确、compose 映射 **UDP/TCP 8000**；跨机将 `public_host` / `rtc.externIP` 设为浏览器可达 IP。浏览器需点播放并可能取消静音。

检测分析与预览无关，始终由 worker 拉流。

---

## 专模：自训与导入现成权重

检测能力三层：**COCO 80 主检** + **内置扩展** + **专模**。专模有两条上线路径（详见 [detection.md](detection.md)）：

### A. 导入现成专模（社区 / 平台）

1. 从 Hugging Face、Ultralytics Platform 等下载 **Ultralytics YOLO detect** 的 `.pt`（或 `.onnx`），或准备直链 URL  
2. 打开 **训练实验室** → 左侧 **导入现成专模**  
3. 选文件或填 **权重 URL** →（可选）**读取类别** → 填 `key` / 中文名 / `kind` / 阈值 → **导入并上线**  
4. **事件监控** → **检测类型配置** → 勾选该专模 → **保存配置**

注意：类别顺序须与 `kind` 约定一致（如 violation：`0=违规, 1=合规`）；不要替换主检 `yolo_model`。

### B. 平台自训专模

训练实验室完成标注与训练，测试集过门禁后 **一键部署**（示例：[未戴眼镜指南](training-glasses-guide.md)）。

---

## 人脸识别

基于 InsightFace **buffalo_l**（`onnxruntime-gpu` / `onnxruntime`，由 `[basic]` `inference_device` 控制 CPU/GPU；无需 `insightface` pip 包）。模型放 `models/buffalo_l/`，人脸库元数据在 Redis、照片在 MinIO；在流的检测类型中勾选「人脸识别」后使用。

### 存储结构

| 数据 | Redis 键 / MinIO 路径 | 说明 |
|------|----------------------|------|
| 人员记录 | Hash `visionai/face_library:persons`，field=`person_id` | JSON：姓名、部门、embedding（512 维）、photos |
| 人员照片 | `visionai/face_library/{person_id}/photo.jpg` | JPEG，录入时上传至 MinIO |

**前置条件**：`object_storage_enabled=true` 且 MinIO/S3 可连通；`Redis` 可连通。否则无法录入新人员。

首次启动时，若 Redis 为空且存在旧版本地 `face_library/` 目录，会自动迁移到 Redis + MinIO。

### 使用流程

```
1. 准备 models/buffalo_l/（det_10g.onnx + w600k_r50.onnx；可选 genderage.onnx）
2. 人脸库管理 → 录入人员（上传正面清晰单人照）
3. 事件监控 → 检测类型配置 → 开启「人脸识别」
4. 配置触发类型：
   - 库内人员（known）：匹配人脸库且相似度 ≥ 阈值
   - 陌生人（unknown）：未匹配或低于阈值
5. 需要性别/年龄时勾选「性别与年龄」（需 genderage.onnx）
6. 若摄像头画面倒置，在配置面板选「画面旋转 180°」
7. 保存配置，站在镜头前等待 15~30 秒
8. 历史告警查看结果（绿框=库内人员，红/橙框=陌生人；勾选性别年龄后标签如「张三 男32岁 0.78」）
```

### 按流配置 `face_recognition_config`

| 字段 | 说明 |
|------|------|
| `trigger_types` | `["known"]` / `["unknown"]` / `["known","unknown"]` |
| `genderage_enabled` | 是否性别与年龄（默认 `false`；需 `genderage.onnx`，且全局 `face_recog_genderage_enabled` 未关） |
| `threshold` | 相似度阈值，空则用全局 `face_recognition_threshold`（0.45） |
| `min_duration_sec` | 持续出现秒数才告警，空则用全局默认 2.0 |
| `rotate` | 画面旋转 0/90/180/270，空则用全局 `face_recog_rotate` |
| `watchlist` | 仅匹配指定人员 ID 列表（可选） |

### CLI 测试

```bash
source env/bin/activate

# 列出人脸库
python scripts/test_face_recognition.py --image /path/to/photo.jpg --list

# 录入
python scripts/test_face_recognition.py --image /path/to/photo.jpg --enroll --name jiaxu

# 比对
python scripts/test_face_recognition.py --image /path/to/test.jpg
```

### 常见问题

| 现象 | 原因与处理 |
|------|------------|
| 完全无告警 | 检查 `models/yolo26s.pt` 是否存在；日志是否有「开始处理视频流」 |
| 画面有人但检测不到脸 | 摄像头倒置 → 设 `rotate=180`；人脸过小 → 调低 `face_recog_det_conf` |
| 自己是库内人员却显示陌生人 | 重新录入照片；站近镜头；检查阈值是否过高 |
| 多人画面只标一人 | 已修复：现绘制所有检出人脸；告警仍按持续时长过滤 |
| 有检测但无邮件 | 检查该流是否勾选「启用邮件告警」及全局 `smtp_*` 配置 |

---

## 车牌识别

检测用专模权重 `models/specialists/plate/`，读号用 **RapidOCR**，名单在 Redis 车牌库。与仅颜色三类的专模「车牌检测」(`plate`) 不同：完整读号+比对请勾选内置扩展 **「车牌识别」**（`plate_recognition`）。

### 存储

| 数据 | Redis 键 | 说明 |
|------|----------|------|
| 车牌记录 | Hash `{prefix}plate_library:plates`，field=规范化车牌号 | JSON：`plate_no`、`name`、`note`、时间戳 |

### 使用流程

```
1. 确认 models/specialists/plate/model.onnx（或 .pt）存在
2. 安装 rapidocr_onnxruntime（requirements.txt；Docker 镜像构建时会尝试预热 OCR 模型）
3. 车牌库管理 → 录入车牌号（可填车主名称/备注）
4. 事件监控 → 检测类型配置 → 开启「车牌识别」
5. 勾选触发：库内车牌（known）/ 陌生车牌（unknown）
6. 保存配置；车辆经过后在历史告警查看「车牌识别: 库内/…」或「陌生车牌/…」
```

### 按流配置 `plate_recognition_config`

| 字段 | 说明 |
|------|------|
| `trigger_types` | `["known"]` / `["unknown"]` / `["known","unknown"]` |
| `ocr_min_conf` | OCR 最低置信度，空则用全局 `plate_recognition_ocr_min_conf`（0.35） |
| `min_duration_sec` | 持续秒数才告警，空则用全局默认 1.0 |

夜间、倾斜或脏污车牌会降准；可适当提高持续秒数或 OCR 阈值防抖。

更多排障见 [operations.md](operations.md)。
