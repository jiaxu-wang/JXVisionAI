# 使用指南

## 管理端页面

登录后左侧菜单：

| 页面 | 功能 |
|------|------|
| **状态概览** | 各流在线/离线、今日告警数、运行指标、ZLM 状态（预览请到设备接入或视频预览） |
| **设备接入** | RTSP 直连 / ONVIF / 国标 28181；预览、对讲、复制 HLS；点「接入AI分析」后才进入检测 |
| **视频预览** | 进入后左侧设备树按接入类型展开，双击视频/通道加入右侧预览墙；最多 25 路（5×5） |
| **检测配置** | 仅已接入分析的流：勾选检测类型、告警邮箱/Webhook |
| **历史告警** | 分页查看检测记录与截图 |
| **系统设置** | 在线编辑 `config.ini` 各分节（含 `[integration]`） |
| **平台接入** | 菜单始终可见。配置了 `[integration] platform_embed_url` 则嵌入该页，未配置则显示「未接入」 |
| **人脸库管理** | 录入人员、查看照片 |
| **车牌库管理** | 录入车牌号、名称与备注 |
| **训练实验室** | **自训专模**（标注→训→门禁→部署）与 **导入现成专模**（上传社区 YOLO 权重）；上线后均可在检测类型目录勾选 |

### 接入平台 vs 接入分析

设备先出现在 **设备接入**，表示平台已拿到这路视频（可探测在线、可预览）。**检测配置**只列出已点「接入AI分析」（国标为通道上的「接入分析」）的流。

| 接入方式 | 接入平台 | 接入分析 |
|----------|----------|----------|
| RTSP 直连 | 填写地址并保存 | 行内「接入AI分析」（`analyze: true`） |
| ONVIF | 发现/探测后「加入监控」 | 同上 |
| 国标 28181 | SIP 注册在线 | **通道配置**里按通道「接入分析」 |

新接入的 RTSP/ONVIF 默认不分析。旧数据没有 `analyze` 字段时视为已分析（兼容）。从检测配置删除：RTSP/ONVIF 只退出分析、设备仍在接入列表；国标删除该路流，SIP 账号保留。

离线设备不可预览。

### 流在线状态与 ZLM

- **在线/离线**：由 `visionai.worker` 写入 Redis（`{key_prefix}stream_runtime_status`），管理端 API 读取；约 3 分钟无心跳则显示离线。分析在跑但页面全离线时，确认 worker 已重启且 Redis 可达。
- **ZLM**：`[zlm] enabled=true` 且容器正常、secret 正确时，状态概览显示「ZLM 在线 · 代理 …」。若显示「ZLM 鉴权失败」，检查 `config.ini` 与 `config/zlm/config.ini` 的 secret 是否一致并重启 zlmediakit。`fallback_direct_rtsp=true` 时代理失败仍可直连摄像机继续检测。

---

## 添加视频流（设备接入）

### RTSP 直连

1. **设备接入 → RTSP直连**，点击 **添加 RTSP 流**，填写名称与 RTSP URL  
   - 密码含 `@` 时需编码为 `%40`（如 `pass@word` → `pass%40word`）
2. 点击 **保存接入配置**（改地址后需保存并重启服务才对 worker 生效）
3. 在线后可 **预览**；点 **接入AI分析** 后到 **检测配置** 勾选检测项、配置邮件/Webhook 并保存
4. 若修改了 `config.ini`（含 `[basic]` **`inference_device`**）或内置模型路径：Compose 执行 `docker compose restart visionai-api visionai-worker visionai-alert`；宿主机执行 `./stop.sh && ./start.sh`（或管理端「重启服务」）。**专模**（自训部署或导入）一般热加载，无需重启

### ONVIF 发现（推荐局域网摄像头）

1. 在 **设备接入 → ONVIF 接入** 点击 **ONVIF 发现 / 手动探测**
2. **扫描局域网**（依赖 WS-Discovery 组播 `239.255.255.250:3702`），或 **手动填写 IP:端口** 加入列表  
   - Docker 桥接网络下扫描常为空，请用手动 IP，或使用 `network_mode: host`
3. 填写摄像机 ONVIF 用户名/密码，点 **检测选中设备**
4. 状态为 **正常** 后，选择码流 Profile（主/子），确认监控名称，点 **加入监控**  
   - 会直接写入 Redis（生成 RTSP URL），无需再点「保存配置」
5. 在线后可预览、对讲、复制 HLS；点 **接入AI分析** 后再到检测配置勾选类型

注意：海康/大华等需在摄像机 Web 端开启 ONVIF；探测「正常」要求鉴权成功、具备 Media 能力且能拿到 `rtsp://` URI。

### 国标 28181

1. 确认 `visionai-sip` 已启动（Compose 服务或 `./start.sh`，日志 `logs/sip.log`）
2. **设备接入 → 国标 28181**：分别填写并保存「SIP 信令」与「媒体收流」（两组 IP 不要混用）
3. **新建** SIP 账号，点 **复制** 把参数填到摄像机上级平台页
4. 点 **通道**，配置视频通道编码（20 位，类型码 131/132）
5. 「刷新在线状态」显示 SIP **在线** 后，在**通道**里点 **预览**（仅点播，画面旁可云台、麦克风喊话）或 **接入分析**（写入检测配置）
6. 跳到「检测配置」后勾选检测类型并保存。已接入且检测开启时，worker 会自动 Invite 并保持拉流

设备列表状态**只表示 SIP 注册在线**。预览和接入分析都是通道级操作。详细说明、海康 415、以及「显示在线却报未注册」见 [gb28181.md](gb28181.md)。

SIP 监听变更后需重启 `visionai-sip`。WSL2 桥接网络下摄像机往往访问不到容器，请用宿主机可达 IP，或 host/mirrored 网络。

---

## 检测生效时间

- 仅改 Redis 流配置（检测项、告警邮箱等）：**下一检测周期**生效（约 `detection_interval` 秒；开启短窗抽帧时含采样窗）
- 改 `config.ini`、更换模型：**必须重启进程**
- 人脸识别首次告警：通常需 **检测间隔 + 持续时长**（如 6s + 2s ≈ 15~30 秒站在镜头前）
- 疲劳驾驶：勾选后约数秒评估机位；不合格显示「本路不支持」。改拉流/密检预设后下一周期生效，一般不用重启

---

## 流预览

在 **设备接入** 对应连接上点击 **预览**（国标在通道配置内），或打开 **视频预览**：页面左侧设备树按类型展开，双击视频/通道加入右侧宫格（最多 25 路，5×5）。仅使用 **ZLM WebRTC**（低延迟，源有兼容音轨时可听声）；RTSP/ONVIF 走 ZLM 代理，国标先 Invite 再收 RTP，关闭格子时未接入分析的通道会 BYE。状态概览只看在线，不提供预览。弹窗标题栏 **截图保存** 会把当前画面下载到本机（JPEG，文件名含通道名与时间）。国标弹窗预览还可点 **麦克风** 向摄像机喇叭喊话（关麦克风或关预览即停）。

前置：`[zlm] enabled=true`、secret 正确、compose 映射 **UDP/TCP 8000**（宿主机 **18000**）；跨机将 `public_host` / `rtc.externIP` 设为浏览器可达 IP。浏览器需点播放并可能取消静音。等画面出来后再截图。

检测分析与预览无关：只有已接入分析的流才由 worker 拉流。

---

## 专模：自训与导入现成权重

检测能力三层：**COCO 80 主检** + **内置扩展** + **专模**。专模有两条上线路径（详见 [detection.md](detection.md)）：

### A. 导入现成专模（社区 / 平台）

1. 从 Hugging Face、Ultralytics Platform 等下载 **Ultralytics YOLO detect** 的 `.pt`（或 `.onnx`），或准备直链 URL  
2. 打开 **训练实验室** → 左侧 **导入现成专模**  
3. 选文件或填 **权重 URL** →（可选）**读取类别** → 填 `key` / 中文名 / `kind` / 阈值 → **导入并上线**  
4. **检测配置** → **算法配置** → 勾选该专模 → **保存检测配置**

注意：类别顺序须与 `kind` 约定一致（如 violation：`0=违规, 1=合规`）；不要替换主检 `yolo_model`。

### B. 平台自训专模

训练实验室完成标注与训练，测试集过门禁后 **一键部署**（示例：[未戴眼镜指南](training-glasses-guide.md)）。

### C. 枪支 / 刀具（预置导入脚本）

```bash
./env/bin/python scripts/download_weapon_specialists.py
```

然后在该路流 **检测配置** 勾选 **枪支检测**（必开）和/或 **刀具检测**（试效果）并保存。说明见 [detection.md](detection.md#枪支--刀具检测)。

---

## 疲劳驾驶（DMS）

只在 **驾驶室正脸**（建议红外）上卖闭眼占比 / 哈欠 / 低头。路侧球机、停车场大场景勾选后会显示不合格，**不会乱告警**。辅助告警，非司法鉴定。安装与算法说明见 [detection.md](detection.md#疲劳驾驶dms)。

### 使用流程

```
1. 确认 models/buffalo_l/（至少 det_10g.onnx；与人脸识别共用）
2. 检测配置 → 算法配置 → 勾选「疲劳驾驶」
3. 选预设：
   - 不计流量：常连，30s 窗 × 8fps（局域网）
   - 车台省流：突发拉 6s 后断开，隔 45s 再拉（SIM；建议子码流）
4. 按现场调 ear_close / PERCLOS / 哈欠次数 / 最小脸宽；夜视机勾选红外
5. 保存当前操作 → 保存检测配置
6. 看本流摘要「疲劳驾驶准入」：合格才告警；脸太小 / 无脸 / 帧率不足则不支持
```

同路可再勾选「玩手机」作分心，不要和疲劳共用一个专模。墨镜、强侧脸、强逆光会降级为无法测眼，而不是瞎报疲劳。

### 按流配置 `fatigue_driving_config`

| 字段 | 说明 |
|------|------|
| `pull_mode` | `always` 常连 / `burst` 窗后断开（国标发 BYE） |
| `pull_interval_sec` | 从上次窗结束起算的间隔 |
| `window_mode` | `duration` 或 `frames` |
| `window_duration_sec` / `window_frames` | 二选一为主，另一个按 `sample_fps` 推算 |
| `sample_fps` | 窗内密检帧率，建议 5–8，不要 25 |
| `ear_close` / `perclos_pct` / `yawn_count` / `nod_deg` | 算法阈，默认偏严 |
| `observe_sec` / `min_face_px` / `alert_hold_sec` / `cooldown_sec` | 观察、脸宽、持续、冷却 |
| `night_mode` | 红外机略放宽眼区 |

面板会按码率估算 MB/小时：常连约等于码流本身；burst 只算窗内传输。

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
3. 检测配置 → 算法配置 → 开启「人脸识别」
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
4. 检测配置 → 算法配置 → 开启「车牌识别」
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
