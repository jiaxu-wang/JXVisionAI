# 第三方平台接入

JXVisionAI 通过 **告警 Webhook** 和 **开放 HTTP API** 对接任意业务系统，不绑定特定厂商。本仓库不包含第三方网关或调度台代码。

```
摄像机 → JXVisionAI（分析 / 预览）
              ↓  Webhook JSON
         你的业务系统（告警、工单、大屏…）
              ↓  开放 API（可选）
         拉流列表、播放地址、告警截图
```

改 `[integration]` 后须重启 API（以及会推告警的 alert / worker）。

---

## 1. 告警 Webhook

在 `config.ini`：

```ini
[integration]
# 告警 JSON 里 image_url 的对外根（无尾斜杠），须是对接方能访问的地址
public_base_url = http://JX_HOST:15000
# 全局推送 URL；与每路视频的 alert_webhook_urls 合并去重
outbound_webhook_url = http://YOUR_HOST:8080/hooks/visionai-alert
```

也可只在管理端「检测配置」里给单路填 Webhook。

请求体事件名为 `visionai.alert`。`detection_types` 为中文协议值（稳定契约）；`detection_type_labels` 为当前 `[ui] language` 下的展示名。含绝对 `image_url`（带短期 HMAC `token`）。

对接方实现一个 HTTPS/HTTP POST 接口接收该 JSON 即可。

---

## 2. 开放 API（机对机）

鉴权：请求头 `X-Api-Key` = `[integration] open_api_key`。未配置或错误时返回 **401 JSON**，不跳转登录页。

| 方法 | 路径 | 用途 |
|------|------|------|
| `GET` | `/api/open/v1/streams` | 已接入分析的流：`id` / `name` / `status` / `play_rtsp` / `play_hls` 等 |
| `POST` | `/api/open/v1/zlm/ensure-proxy` | body `{stream_id}`：确保拉流代理并返回播放地址 |
| `GET` | `/api/open/v1/alerts/<id>/image` | 告警截图（`X-Api-Key` 或 `image_url` 上的 `token`） |

播放：RTSP/ONVIF 走 ZLM app `jvai`；国标收流为 `rtp`。对接方从自己的媒体服务再拉 `play_rtsp`，不要写死 `/live/`。

接口细节见 [api.md](api.md#开放集成机对机无需-session)。

---

## 3. 把管理页嵌进对接方页面（可选）

若第三方控制台需要 iframe / 新窗口打开本管理端：

1. 用开放 API 密钥调用 `POST /api/open/v1/embed-token`，得到一次性 `embed_url`（默认 60 秒、用一次即作废）。
2. 浏览器打开 `/embed?token=`，写入与普通登录相同的 Session。
3. `[integration] embed_frame_ancestors` 填**对接方页面的源**（空格或逗号分隔），进程会下发 `Content-Security-Policy: frame-ancestors`。空则不写 CSP。

HTTP 局域网下浏览器可能拦截 iframe 第三方 Cookie，可用新窗口打开同一 `embed_url`。

---

## 4. 侧栏「平台接入」（把对接方页面嵌进本管理端）

与上一节相反：在本管理端侧栏打开第三方控制台。

- 菜单 **始终显示**。
- `[integration] platform_embed_url` 有值：点击后 iframe 加载该 URL。
- 该项为空：点击后显示 **未接入**，不加载 iframe。

```ini
[integration]
platform_embed_url = http://YOUR_HOST:8080/#/path
```

也可在管理端「系统设置 → 开放集成」填写。保存后再次点击「平台接入」即可（不必为该项单独重启）。对接方页面须允许被本站 iframe（不要设 `X-Frame-Options: DENY`）。
