# 使用指南

## 管理端页面

登录后左侧菜单：

| 页面 | 功能 |
|------|------|
| **状态概览** | 各流在线/离线、今日告警数 |
| **事件监控** | 添加/编辑 RTSP 流、检测类型、邮件/Webhook 告警 |
| **历史告警** | 分页查看检测记录与截图 |
| **系统设置** | 在线编辑 `config.ini` 各配置单元 |
| **人脸库管理** | 录入人员、查看照片 |
| **训练实验室** | RTSP 截帧标注与 YOLO 训练 MVP |

---

## 添加视频流（事件监控）

1. 点击 **+ 添加视频流**，填写名称与 RTSP URL  
   - 密码含 `@` 时需编码为 `%40`（如 `inrico@123` → `inrico%40123`）
2. 点击 **检测类型配置**，勾选需要的检测项（如「人脸识别」）
3. 配置 **邮件告警** / **Webhook**（可选）
4. 点击 **保存配置**
5. 若修改了 `config.ini` 或模型文件，点击 **重启服务** 或执行 `./stop.sh && ./start.sh`

---

## 检测生效时间

- 仅改 Redis 流配置（检测项、告警邮箱等）：**下一检测周期**生效（约 `detection_interval` 秒）
- 改 `config.ini`、更换模型：**必须重启进程**
- 人脸识别首次告警：通常需 **检测间隔 + 持续时长**（如 6s + 2s ≈ 15~30 秒站在镜头前）

---

## 流预览

状态概览或事件监控中可打开预览，支持：

- **WebRTC**（低延迟，推荐）
- **WebSocket / MJPEG**（可叠加检测框）
- **HLS**（延迟较高，需 `ffmpeg`）

---

## 人脸识别

基于 InsightFace **buffalo_l**（纯 `onnxruntime` 推理，无需安装 `insightface` pip 包）。详细设计见 [face_recognition_design.md](face_recognition_design.md)。

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
| 完全无告警 | 检查 `models/yolov8n.pt` 是否存在；日志是否有「开始处理视频流」 |
| 画面有人但检测不到脸 | 摄像头倒置 → 设 `rotate=180`；人脸过小 → 调低 `face_recog_det_conf` |
| 自己是库内人员却显示陌生人 | 重新录入照片；站近镜头；检查阈值是否过高 |
| 多人画面只标一人 | 已修复：现绘制所有检出人脸；告警仍按持续时长过滤 |
| 有检测但无邮件 | 检查该流是否勾选「启用邮件告警」及全局 `smtp_*` 配置 |

更多排障见 [operations.md](operations.md)。
