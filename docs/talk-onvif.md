# ONVIF 语音对讲（Audio Backchannel）

JXVisionAI 支持通过 **ONVIF RTSP Audio Backchannel** 将浏览器麦克风音频回传到摄像机喇叭。国标喊话见 [gb28181.md](gb28181.md#喊话广播)。

## 能力探测（类似 ODM）

探测路径：

1. ONVIF `GetCapabilities` / `GetAudioOutputs`（参考信息）
2. 对 Profile 的 RTSP URL 发起  
   `DESCRIBE` + `Require: www.onvif.org/ver20/backchannel`  
3. 解析 SDP 是否存在 `m=audio` + `a=sendonly`（G.711 PCMA/PCMU）

入口：

- **ONVIF 发现** →「检测选中设备」结果中会显示是否支持对讲  
- **状态概览 / 视频流配置** →「对讲」或「探测对讲」→「重新探测」  
- API：`POST /api/talk/probe` `{ "stream_id": "...", "persist": true }`

## 对讲流程

1. `POST /api/talk/start` `{ "stream_id" }` → 建立 RTSP SETUP/PLAY（TCP interleaved）  
2. 浏览器采麦 → 重采样 8kHz → 编码 G.711 → `POST /api/talk/audio?session_id=...`（binary）  
3. `POST /api/talk/stop` 结束会话  

## 现场验证（海康等）

1. 摄像机网页确认「双向语音 / 音频输出」已开，喇叭正常  
2. 用 **ONVIF Device Manager** 对同一设备试对讲（对照）  
3. 本系统：状态概览对该流点「探测对讲」  
   - 显示「支持对讲」→ 再点「开始对讲」，允许麦克风，听喇叭是否出声  
   - 显示不支持 → 该机多半未开放标准 Backchannel（海康有时仅 ISAPI 对讲，后续可加）  

注意：

- RTSP URL 须含正确账号密码（加入监控时 ONVIF 会写入）  
- Compose 部署时 API 容器须能访问摄像机局域网 IP  
- 部分设备只接受 Digest；若 Basic 鉴权失败，探测会报 RTSP 401  

## 相关代码

- `visionai/core/onvif_client.py` — probe 附带 talk 字段  
- `visionai/core/rtsp_backchannel.py` — DESCRIBE/SETUP/PLAY + RTP 上行  
- `visionai/core/talk_session.py` — 会话管理  
- `visionai/web/app.py` — `/api/talk/*`  
- `visionai/web/templates/admin/_modals.html` + `static/admin/js/devices.js` — 对讲 UI 与逻辑  
