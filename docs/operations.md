# 运维与排障

## 日志

Compose 与宿主机均挂载/写入项目 `logs/`：

| 文件 | 进程 / 容器 |
|------|-------------|
| `logs/visionai.log` | `visionai-api` / `visionai.api`（Web / HTTP） |
| `logs/worker.log` | `visionai-worker` / `visionai.worker`（拉流检测） |
| `logs/alert_worker.log` | `visionai-alert` / 异步告警消费 |
| `logs/sip.log` | `visionai-sip` / `visionai.sip`（国标信令） |
| `logs/inferd.log` | `visionai-inferd`（仅 `[infer] backend=cpp`） |
| `logs/zlm/` | ZLMediaKit |

```bash
tail -f logs/worker.log logs/visionai.log

# 关注关键词（检测在 worker）
grep -E "开始处理|检测到|face_recognition|YOLO模型|ERROR|离线|ZLM" logs/worker.log

# Compose 容器日志
docker compose logs -f --tail 100 visionai-worker visionai-api visionai-sip
```

---

## 正常启动日志示例

worker 侧类似：

```
JXVisionAI stream worker 启动
已启动视频流处理线程: test
[test] 视频流已连接，正在加载检测模型…
YOLO模型加载完成
[test] 开始处理视频流（检测）…
检测到: 人脸识别: jiaxu (0.67)
```

健康检查：

- Compose：`curl -s http://127.0.0.1:15000/healthz` · `curl -s http://127.0.0.1:15000/readyz`
- 宿主机 `./start.sh`：`:5000` 同上路径

`readyz` 正常示例：`{"checks":{"inferd":"python","redis":true,"zlm":true},"ready":true}`。

---

## 性能建议

- 多路与高分辨率线性消耗 CPU/GPU/带宽；可调大 `detection_interval`，或把 `detect_burst_frames` 降为 `1` 退回单帧
- YOLO26 档位：`n` 最轻 → `x` 最重；多路优先 `n`/`s`，精度对比可换 `m`/`l`/`x`（改 `yolo_model` 后重启）
- GPU 推理 ONNX 需 `onnxruntime-gpu` 且 `[basic]` `inference_device = gpu`
- 预览仅 ZLM WebRTC（低延迟）；需 compose 映射宿主机 **18000**（→8000）且 ZLM 鉴权正常
- 注意摄像机 RTSP 并发连接数上限

### ONVIF 发现排障

| 现象 | 处理 |
|------|------|
| 扫描结果为空 | 确认与摄像头同二层网络；Docker 用 host 网络或改用手动 IP |
| 鉴权失败 | 使用摄像机 **ONVIF 用户**（集成协议，可能与 Web 登录不同）；确认密码；**本机 HTTP 代理勿劫持局域网**（`start.sh` 已把 `192.168.0.0/16` 等加入 `NO_PROXY`，ONVIF 客户端也会 `trust_env=False` 直连）。改完后需 **重启服务** 再测 |
| 无 Media / 无 RTSP | 在摄像机端开启 ONVIF / RTSP；确认 Profile S |
| 加入后仍离线 | 用返回的 RTSP 在 VLC 验证；检查密码中的 `@` 是否已编码 |

### 国标 28181 排障

| 现象 | 处理 |
|------|------|
| 列表在线，预览/接入分析报「未在 SIP 注册」 | 列表在线是 Redis 缓存，Invite 要 sip **内存会话**。重启 sip 后等摄像机心跳或重新 REGISTER。详见 [gb28181.md](gb28181.md#在线但点播报未注册) |
| Invite 415 | 海康常拒绝 UDP RTP；平台使用 TCP 被动收流，不要改回 UDP/RTP/AVP |
| 无画面 / 流名是 8 位十六进制 | 媒体 IP 须摄像机可达；端口 10000–10200 TCP+UDP；不要打到 ZLM `rtp_proxy:10000` |
| 信令未运行 | `docker compose ps visionai-sip` 或 `logs/sip.log`；宿主机确认 `./start.sh` 拉起了 sip |

完整步骤见 [gb28181.md](gb28181.md)、[user-guide.md](user-guide.md#国标-28181)。

### 状态概览 / ZLM 排障

| 现象 | 处理 |
|------|------|
| 日志在检测，页面「全部离线」 | 确认 worker 容器/进程已重启；worker 写 Redis `stream_runtime_status`，API 只读；检查 Redis 连通 |
| WebRTC 黑屏 / 「预览失败」 | 1) `config/zlm` 设 `rtsp.directProxy=0` 后 `docker compose up -d --force-recreate zlmediakit`<br>2) 映射 `18000/tcp`+`18000/udp`；WSL2 上 UDP 常不通，已默认 preferred_tcp<br>3) `[zlm] public_host` / `rtc.externIP` 填浏览器可达 IP（本机 `127.0.0.1`） |
| 「ZLM 鉴权失败」/ `readyz` 中 zlm 失败 | `[zlm] secret` 与 `config/zlm/config.ini` 一致；**勿用**出厂默认 secret；改后 `docker compose restart zlmediakit` 再重启应用 |
| 「ZLM 不可达」 | `docker compose ps` 看 zlmediakit；本机 `curl http://127.0.0.1:18080`；端口 `18080`/`18554`/`18000` |
| 检测正常但 ZLM 红 | `fallback_direct_rtsp=true` 时检测可直连源站；修好鉴权后预览才可用 |

---

## 安全

- 生产环境修改 `visionai_secret`
- 修改 ZLM `secret`（勿保留出厂默认）
- `config.ini` 含 SMTP 密码等敏感信息，已在 `.gitignore`
- Redis 设置强密码，勿暴露到公网

---

## 路线图

- [x] 多路流、Web 管理端、Redis 配置、历史告警
- [x] 多进程（api / worker / alert / sip）、整栈 Compose（四应用 + Redis + MinIO + ZLM）、ZLM WebRTC 预览
- [x] 流在线状态 Redis 共享、ZLM 媒体面与直连回退
- [x] 设备接入与接入分析分离（`analyze`）；国标通道级预览/Invite/ZLM 收 PS
- [x] 邮件、Webhook、对象存储、系统设置页；吸烟等场景可通过 **训练专模** 实现
- [x] Web 训练实验室（审核标注、独立测试集、部署门禁、类别契约）
- [x] **人脸识别**（buffalo_l、人脸库、按流触发、画面旋转、可选性别年龄）
- [x] **车牌识别**（plate 专模框 + RapidOCR + 车牌库 known/unknown）
- [x] **疲劳驾驶 DMS**（准入闸、常连/突发密检、PERCLOS/哈欠/低头；不合格机位拒绝）
- [x] 可选 `visionai-inferd`（`[infer] backend=cpp`）
- [ ] 仅开人脸识别时跳过 YOLO 主检测（性能优化）
- [ ] 生产 WebRTC TURN、更多专模开箱权重
- [ ] 训练任务队列隔离（与检测进程分机/分卡）

---

## 相关文档

- [使用指南](user-guide.md)
- [国标 28181](gb28181.md)
- [快速开始](getting-started.md)
- [配置说明](configuration.md)
