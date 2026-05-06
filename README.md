# VisionAI

**源码仓库**：<https://github.com/jiaxu-wang/visionai>

```bash
git clone https://github.com/jiaxu-wang/visionai.git
cd visionai
```

## 项目简介

VisionAI 是基于 **Ultralytics YOLOv8**（COCO 预训练）的多路 **RTSP** 视频分析系统：并行拉流、目标检测、对「打电话 / 玩手机」的人机框重叠 + **YOLOv8-pose** 行为区分、截图与告警写入 **Redis**，并通过 **Flask** Web 管理平台配置视频流与每路检测项。默认模型为 **YOLOv8n**，类别与 COCO 80 类及扩展项对齐（见 `visionai/config/detection_catalog.py`）。

## 功能特性

- ✅ 多路视频流并行处理，断线自动重连  
- ✅ **COCO 80 类**检测项可按视频流单独开关（Web 弹窗配置）；新增流默认全部检测关闭  
- ✅ **打电话**：人物与手机（COCO `cell phone`）框重叠后，用 **姿态模型**（默认 `yolov8n-pose.pt`）看手机中心与肩颈/耳根远近，判为贴耳通话，画面 `CALLING`
- ✅ **玩手机**：同样先重叠，姿态上更靠近双手/身前则判为把玩，画面 `PLAY_PHONE`；无姿态或未加载时按手机在人物框内的**竖直占比**粗分（可关 `pose_for_phone_enabled` 仅用后者）
- ✅ 每路流可 **启用/暂停** 检测；截图按流分子目录保存  
- ✅ **告警外发邮箱**：「检测配置」每路流可填多个收件人（`alert_emails`），并可单独关闭该路 **邮件告警**（`alert_email_enabled`）；全局 **SMTP** 在 `config.ini` / 环境变量中配置（`SMTP_*`），与成功写入 Redis 的告警同频次发信（受 `SAVE_INTERVAL` 约束），可附本地截图（大小上限可配）。  
- ✅ Web：**状态概览**（检测能力计数含打电话/玩手机等扩展项、在线/总流、今日告警统计）、**检测配置**（原视频流管理）、**历史告警**（时间范围/视频流/检测类型筛选、分页条数 5～50）、**流预览**（WebSocket / HLS / MJPEG，见下文「性能与注意」）  
- ✅ 登录鉴权（密钥）  
- ✅ 日志含流名称标识  

## 技术栈

- Python 3.12  
- OpenCV、`opencv-python-headless`（Docker 推荐）  
- Ultralytics YOLOv8、NumPy  
- Flask  
- Redis  

依赖列表见 **`requirements.txt`**。权重（`*.pt` / `*.onnx`）、`models/hf_smoking/`、训练数据与 `training_system/runs/` 等**未纳入 Git**，请本地按需准备（见 `scripts/`、`training_system/README.md`）。

## 项目结构

```
VisionAI/
├── visionai/                      # 主程序包
│   ├── __main__.py                # 入口：视频线程 + Flask
│   ├── config/
│   │   ├── settings.py            # 配置（环境变量 / config/config.ini，见下文）
│   │   └── detection_catalog.py   # COCO 80 类 +「打电话」目录与归一化
│   ├── core/
│   │   ├── detector.py            # YOLO 推理与人机重叠 → 打电话/玩手机分流
│   │   ├── pose_phone.py          # YOLOv8-pose 关键点：手机与肩头/手腕比距
│   │   ├── preview_cache.py       # 预览 JPEG 缓存（检测框）
│   │   ├── preview_hls.py         # FFmpeg 低延迟 HLS 会话
│   │   ├── object_storage.py      # S3/MinIO 截图上传
│   │   ├── behaviors/             # 吸烟 ONNX、香烟门控 YOLO、注册表
│   │   ├── stream_handler.py      # 单路流读取
│   │   ├── redis_manager.py       # 流配置与检测记录
│   │   └── state_manager.py       # 流在线状态
│   ├── utils/logger.py
│   ├── utils/rtsp_url.py
│   ├── utils/alert_email.py     # 告警 SMTP（每路收件人 + 全局配置）
│   └── web/
│       ├── app.py                 # Flask 路由与 MJPEG 预览等
│       ├── templates/             # admin.html、login.html
│       └── static/
├── scripts/                       # 如 export_smoking_onnx.py（ViT → ONNX）
├── training_system/               # 可选：自定义数据训练 / 导出模型
├── requirements.txt
├── Dockerfile
├── config/                        # 可选：config.example.ini 复制为 config.ini
├── docker-compose.yaml            # VisionAI + Redis 编排示例
├── snapshots/                     # 截图根目录（按流名分子目录）
├── logs/                          # 日志（如使用 start.sh 则含 visionai.log）
├── start.sh / stop.sh             # 本机虚拟环境启动/停止
└── README.md
```

视频流配置存放在 **Redis** 中，由 Web「检测配置」页维护，**不再**使用 `settings.py` 内硬编码的 `STREAMS` 列表。

## 快速开始

### 方式一：本机虚拟环境

```bash
git clone https://github.com/jiaxu-wang/visionai.git
cd visionai
python3 -m venv env
source env/bin/activate   # Windows: env\Scripts\activate
pip install -r requirements.txt
# 先保证本机可连 Redis：通常用 docker compose 只起 redis（或本机已装 Redis，端口与下面一致）
# ./start.sh 默认 export REDIS_HOST=127.0.0.1、REDIS_PORT=16379，并设置 SAVE_DIR/LOG_DIR 为相对路径，
# 以覆盖 config/config.ini 里常见的「Docker 专用」项（redis 主机名、/app/... 路径）。
# 若 Redis 在其它地址/端口：启动前 export REDIS_HOST / REDIS_PORT
./start.sh
```

管理界面：<http://服务器IP:5000>  

默认登录密钥见 `config/config.example.ini` 中 `visionai_secret` 示例；**生产环境请务必修改**，或通过环境变量 `VISIONAI_SECRET` / `SECRET` 覆盖。

停止：`./stop.sh`

### 方式二：Docker Compose

```bash
docker compose up -d --build
```

- 应用：<http://localhost:5000>  
- Compose 内 Redis 对外 **16379**；MinIO 控制台 **9001**、S3 兼容 API **9000**（与 `minioadmin` 凭据，仅示例请修改）  
- 数据卷：快照、日志、Redis 数据、可选的 `config/`、MinIO 数据 `minio-data`  

容器内访问宿主机 RTSP 时，请勿使用 `127.0.0.1`（指向容器自身）；应使用宿主机局域网 IP，或配置 `extra_hosts`（如 `host.docker.internal`）按环境而定。

## 配置说明

### 优先级与生效方式

1. **环境变量**（最高）  
2. **配置文件**：项目根下 `config/config.ini`（UTF-8，节 `[visionai]`，键名与下表**小写**一致，如 `redis_host=redis`）  
3. **`visionai/config/settings.py` 中代码默认值**（一般不必改此文件，除非扩展开关）

修改 `config.ini` 或环境变量后，需 **重启应用进程/容器** 才会重新加载（进程内不会热重载配置）。

`VISIONAI_CONFIG` 可指向任意路径的 ini 文件，覆盖默认的 `config/config.ini`。

**不建议**把 `settings.py` 整文件挂进容器作为「配置」：它是可执行代码，改坏语法会导致启动失败，且与代码版本解耦困难。需要文件化时优先 `config.ini`。

### 主要项（与 env / `config.ini` 键名对应）

| 配置项 | 说明 | 默认 |
|--------|------|------|
| `DETECTION_INTERVAL` | 检测间隔（秒） | 15 |
| `CONF_THRESHOLD` | 推理置信度阈值 | 0.5 |
| `SAVE_DIR` | 截图根目录 | `./snapshots` |
| `SAVE_INTERVAL` | 截图最小间隔（秒） | 10 |
| `YOLO_MODEL` | 模型路径或 Ultralytics 模型名 | `yolov8n.pt` |
| `YOLO_DEVICE` | 主检测与姿态：`auto`/空、`cpu`、`0`、`cuda`、`cuda:0`（不写则 Ultralytics 自动选显卡） | （空） |
| `POSE_MODEL` | 打电话/玩手机所用姿态 `.pt` | `yolov8n-pose.pt` |
| `POSE_FOR_PHONE_ENABLED` | 人机重叠后是否用姿态区分打电话/玩手机 | `true` |
| `ONNX_PROVIDER` | 吸烟 ONNX：`cpu`；`cuda_first`=优先 CUDA EP（须安装带 GPU 的 onnxruntime） | `cpu` |
| `REDIS_*` | Redis 连接与键前缀 | 见 `config/config.example.ini` |

ini 中为**小写**键：`yolo_device`、`onnx_provider`；等价环境变量为表中大写枚举名。
| `LOG_*` | 日志级别、保留天数、目录 | 见示例 |
| `DETECTION_RETENTION_DAYS` | 检测记录在 Redis 中的过期（天） | 1 |
| `SMTP_*` | 告警邮件：全局 SMTP（`smtp_alert_enabled`、`smtp_host`、`smtp_from`、`smtp_port`、`smtp_use_tls`/`smtp_use_ssl`、`smtp_user`、`smtp_password`、`smtp_alert_attach_max_bytes`） | 默认关闭 |

模板文件：`config/config.example.ini` → 复制为 `config/config.ini` 再改（`config/config.ini` 已默认加入 `.gitignore` 以免把密钥推上仓库）。

### 对象存储（截图，可扩展为视频等）

- 开启后，在本地保存/上传逻辑见 `visionai/core/object_storage.py`（S3 兼容，默认 MinIO/自建桶）。
- 环境变量/ini：`OBJECT_STORAGE_ENABLED`、`S3_ENDPOINT_URL`、`S3_ACCESS_KEY_ID`、`S3_SECRET_ACCESS_KEY`、`S3_BUCKET`、`S3_USE_SSL`（MinIO 内网 HTTP 一般为 `false`）、`S3_PATH_PREFIX`（键前缀，如 `visionai/snapshots/…` 与未来的 `…/videos/…`）。
- `OBJECT_STORAGE_KEEP_LOCAL`：为 `true` 时本机仍留一份，便于排障；为 `true` 且已上传 S3 时，历史告警小图可经 `/api/alert-image/<id>` 从对象存储回源。
- **截图在 MinIO/S3 中的保留**：与 **`detection_retention_days`（即 `DETECTION_RETENTION_DAYS`）** 一致。服务启动时若 `S3_LIFECYCLE_ENABLED` 为真（默认），会为前缀 `S3_PATH_PREFIX` + `snapshots/` 写入/合并 **桶生命周期**（满 N 天删除该前缀下对象，N=上述配置）。说明：S3/MinIO 按**每个对象自上传日**起算 N 天；Redis 里对检测 Hash 的 `EXPIRE` 会在**每次新告警**时整键续期，二者在「持续有告警」的流上时间线可能略有差异，但 N 为同一配置。
- Docker Compose 已带 **MinIO**（`9000` API，`9001` 控制台，数据 `./minio-data`）。若云端桶策略禁止 API 写生命周期，可在控制台手动为同一前缀设相同天数，或设 `S3_LIFECYCLE_ENABLED=false`。
- 改用公有云 S3 时，删除或停掉 `minio` 服务，并把 `S3_ENDPOINT_URL` 等改为云厂商提供的值（应用仍通过同一套环境变量/ini 配置）。

### 环境变量（可选）

与上表同名大写，便于 Docker/K8s/Compose 注入，例如 `docker-compose.yaml` 中的 `REDIS_HOST`、`VISIONAI_SECRET` 等会覆盖同键的 ini 与默认值。

### Web 与 Redis

- 在 **「检测配置」** 中添加/编辑视频流、每路 **检测类型**（弹窗内开关）、**告警外发邮箱**（可多个，逗号/换行分隔；须配置全局 `SMTP_*` 后生效）、**是否启用该路邮件告警**（独立开关）。保存后写入 Redis；拉流线程在后续检测轮次中会同步更新检测项、**alert_emails** 与 **alert_email_enabled**（一般无需重启）。若大幅变更流列表或长期异常，可重启进程。  
- **「打电话」/「玩手机」** 任一开时：采集人物与手机框；对重叠对先跑 **pose**（可选）再归类；仅对参与对应类别配对的人/手机画框（详见 `visionai/core/detector.py`、`pose_phone.py`）。

## 主要 HTTP API（需登录）

| 路径 | 说明 |
|------|------|
| `GET /api/streams` | 流列表（含归一化后的 `detections`） |
| `POST /api/streams` | 保存全部流配置 |
| `GET /api/detection-catalog` | COCO 80 + 扩展项（打电话、玩手机、人员聚集、吸烟等） |
| `GET /api/detections` | 检测记录分页；支持 `start`、`end`、`stream_id`、`detection_type`、`limit`、`offset` |
| `GET /api/stats/alerts-today` | 今日告警条数（服务器本地日） |
| `GET /api/config` | 含 `preview.*`、`smtp.ready`（告警邮件全局 SMTP 是否可用） |
| `GET /api/preview?stream_id=` | RTSP→MJPEG（`annotated=1` 为带框缓存） |
| `WS /ws/preview` | WebSocket：首条消息 JSON `{"stream_id":"","annotated":false}`，后续二进制 JPEG |
| `POST /api/preview-webrtc/offer` | JSON `{"stream_id":"","sdp":"","type":"offer"}` → `{sdp,type,session_id}`（SDP Answer） |
| `POST /api/preview-webrtc/stop` | JSON `{"session_id":""}` 释放 aiortc / MediaPlayer |
| `POST /api/preview-hls/start` | JSON `{"stream_id":""}` → `{ playlist, session_id }` |
| `POST /api/preview-hls/stop` | JSON `{"session_id":""}` 停止转码并删除临时切片 |
| `GET /api/preview-hls/data/<session_id>/index.m3u8` 等 | HLS 播放列表与分片（需登录 Cookie） |

## 检测与模型说明

- **人物 / 手机 / 车辆等**：对应 COCO 类别索引，名称见 `detection_catalog.py`。  
- **打电话**：`detection_types` 为「打电话」；画面上 `CALLING`。  
- **玩手机**：`detection_types` 为「玩手机」；画面上 `PLAY_PHONE`。  
- **吸烟**：主流程为人物框裁剪 → ViT 二分类（`smoking_model_path`，见导出脚本）；易将「手贴脸」判正。若配置 **`smoking_cigarette_detector_path`** 指向另行训练的香烟小目标 YOLO（`.pt`），则本帧会先跑香烟检测，**仅当某人体与香烟候选框关联**（相交或烟头中心在人体框邻近）时再跑 ViT，用于压制误报。（香烟权重需自备，例如用公开「cigarette/cigar」数据在 Ultralytics 上训一类再导出 `best.pt`。）
- 更换自定义 `.pt` 时，需与 `detection_catalog` 或自研类别表一致，并更新 Web 与 `YOLO_MODEL`。  

训练与导出可参考 **`training_system/README.md`**。

## 依赖安装（摘要）

```bash
pip install -r requirements.txt
```

（若在本机使用 GUI 版 OpenCV，可将 `opencv-python-headless` 换为 `opencv-python`。）

## 性能与注意

- 推理耗时与硬件、模型、分辨率有关；YOLOv8n 适合实时场景。  
- 每路流独立线程；多路会线性增加 CPU/GPU 与带宽。  
- 首次运行若无权重文件，Ultralytics 可能自动下载模型。  
- 管理端 **流预览** 可选四种方式（弹窗内「预览方式」）：**WebRTC**（`aiortc` 拉 RTSP，SRTP 推浏览器，延迟通常最低；**需** `pip install aiortc`）、**WebSocket**（JPEG 帧）、**MJPEG**（兼容）、**HLS**（`ffmpeg` 转码，延迟最高）。勾选「检测框」仅 **WebSocket / MJPEG** 与检测缓存同步；**WebRTC / HLS 为原画**。关闭预览会结束 WebRTC / WS、停止 HLS 会话。配置见 `preview_*`、`preview_webrtc_*`、`preview_hls_*`。复杂 NAT 下 WebRTC 可能需自建 **TURN** 或改用 WebSocket。
- **RTSP 密码中含 `@`**（如海康部分密码）时，标准写法 `rtsp://user:pass@host` 会与密码里的 `@` 冲突，导致拉流解析错主机、状态长期「离线」而预览偶发正常。程序已自动将密码中的 `@` 编码为 `%40`（`visionai/utils/rtsp_url.py`）；也可在「检测配置」中手改 URL。多路拉流时请注意摄像机**最大并发连接数**。

## 开发计划（节选）

- [x] 多路流、Web 配置、Redis、登录、历史告警  
- [x] COCO 全类按流配置、「打电话」重叠规则、状态概览与筛选、Docker  
- [x] 管理端流预览（WebRTC / WebSocket / HLS / MJPEG）  
- [ ] 更多业务类（吸烟、安全帽等）需自定义训练与类别表  
- [ ] WebHook 等其它外发告警  
- [ ] 生产级 **TURN**（WebRTC 跨复杂 NAT）
