# 运维与排障

## 日志

```bash
tail -f logs/visionai.log

# 关注关键词
grep -E "开始处理|检测到|face_recognition|YOLO模型|ERROR|离线" logs/visionai.log
```

---

## 正常启动日志示例

```
JXVisionAI 启动
已启动视频流处理线程: test
[test] 视频流连接成功
[test] 视频流已连接，正在加载检测模型…
YOLO模型加载完成
[test] 开始处理视频流（检测）…
人脸 ONNX 已加载: .../models/buffalo_l/det_10g.onnx
检测到: 人脸识别: jiaxu (0.67)
```

---

## 性能建议

- 多路与高分辨率线性消耗 CPU/GPU/带宽；可调大 `detection_interval`
- 预览 WebRTC 延迟最低；HLS 需 `ffmpeg` 且 CPU 占用更高
- 注意摄像机 RTSP 并发连接数上限

### ONVIF 发现排障

| 现象 | 处理 |
|------|------|
| 扫描结果为空 | 确认与摄像头同二层网络；Docker 用 host 网络或改用手动 IP |
| 鉴权失败 | 使用摄像机 **ONVIF 用户**（集成协议，可能与 Web 登录不同）；确认密码；**本机 HTTP 代理勿劫持局域网**（`start.sh` 已把 `192.168.0.0/16` 等加入 `NO_PROXY`，ONVIF 客户端也会 `trust_env=False` 直连）。改完后需 **重启服务** 再测 |
| 无 Media / 无 RTSP | 在摄像机端开启 ONVIF / RTSP；确认 Profile S |
| 加入后仍离线 | 用返回的 RTSP 在 VLC 验证；检查密码中的 `@` 是否已编码 |

---

## 安全

- 生产环境修改 `visionai_secret`
- `config.ini` 含 SMTP 密码等敏感信息，已在 `.gitignore`
- Redis 设置强密码，勿暴露到公网

---

## 路线图

- [x] 多路流、Web 管理端、Redis 配置、历史告警
- [x] COCO 按流开关、Compose（Redis + MinIO）、预览多模式
- [x] 吸烟、邮件、Webhook、对象存储、系统设置页
- [x] Web 训练实验室（行业级：审核标注、独立测试集、部署门禁、yolov8s、类别契约）
- [x] **人脸识别**（buffalo_l、人脸库、按流触发、画面旋转、可选性别年龄）
- [ ] 仅开人脸识别时跳过 YOLO 主检测（性能优化）
- [ ] 生产 WebRTC TURN、更多专模开箱权重
- [ ] 训练任务队列隔离（与检测进程分机/分卡）

---

## 相关文档

- [使用指南 - 常见问题](user-guide.md#常见问题)
- [快速开始](getting-started.md)
- [配置说明](configuration.md)
