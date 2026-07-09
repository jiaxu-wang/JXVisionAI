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
- [x] Web 训练实验室 MVP
- [x] **人脸识别**（buffalo_l、人脸库、按流触发、画面旋转）
- [ ] 仅开人脸识别时跳过 YOLO 主检测（性能优化）
- [ ] 生产 WebRTC TURN、更多专模开箱权重

---

## 相关文档

- [使用指南 - 常见问题](user-guide.md#常见问题)
- [快速开始](getting-started.md)
- [配置说明](configuration.md)
