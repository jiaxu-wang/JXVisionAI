"""
Flask 管理端：登录、流配置、历史告警、系统设置、人脸库、预览与训练实验室。

与检测线程同进程；静态资源与模板位于本包 ``web/static``、``web/templates``。
登录密钥取自配置 ``visionai_secret`` / 环境变量 ``VISIONAI_SECRET``。
"""
import os
import sys
import json
import subprocess
import functools
import time
from datetime import datetime

import cv2
from flask import (
    Flask,
    abort,
    render_template,
    jsonify,
    request,
    Response,
    send_file,
    send_from_directory,
    session,
    redirect,
    url_for,
)

# 保证以 ``python -m visionai`` 启动时也能解析项目根下的相对导入
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from visionai.config.settings import (
    AUTO_REFRESH_INTERVAL,
    SECRET,
    SMTP_ALERT_ENABLED,
    SMTP_FROM,
    SMTP_HOST,
)
from visionai.utils.alert_email import (
    normalize_stream_alert_emails,
    normalize_stream_alert_email_enabled,
    smtp_is_configured,
)
from visionai.utils.alert_webhook import (
    normalize_stream_alert_webhook_enabled,
    normalize_stream_webhook_urls,
)
from visionai.utils.rtsp_url import normalize_rtsp_url
from visionai.config.detection_catalog import catalog_items_for_api, normalize_detections
from visionai.config.stream_access import (
    ACCESS_GB28181,
    ACCESS_ONVIF,
    apply_access_fields,
    apply_analyze_field,
    normalize_access_method,
)
from visionai.core.face_recognition_config import (
    default_face_recognition_config,
    normalize_face_recognition_config,
)
from visionai.core.plate_recognition_config import (
    default_plate_recognition_config,
    normalize_plate_recognition_config,
)
from visionai.core import gb28181_store, onvif_client
from visionai.config.ini_manager import (
    config_meta,
    patch_config_updates,
    read_structured_units,
)
from visionai.core import stream_sync

# 导入流状态管理
try:
    from visionai.core.state_manager import (
        get_all_stream_statuses,
        get_stream_status,
        set_stream_status,
        stream_status,
        stream_status_lock,
    )
except Exception:  # noqa: BLE001
    stream_status = {}
    stream_status_lock = None

    def get_stream_status(name, default="离线"):
        return default

    def get_all_stream_statuses():
        return {}

    def set_stream_status(name, status):
        pass

# 导入Redis管理器
try:
    from visionai.core.redis_manager import redis_manager
except ImportError:
    redis_manager = None

try:
    from visionai.core.object_storage import get_object_storage
except ImportError:
    def get_object_storage():  # type: ignore
        return None


app = Flask(__name__, template_folder='templates', static_folder='static')
# 挂载源码改模板后免重建镜像；进程内仍须重启一次才能丢掉已编译的旧模板缓存
app.config["TEMPLATES_AUTO_RELOAD"] = True
app.jinja_env.auto_reload = True
app.config["SEND_FILE_MAX_AGE_DEFAULT"] = 0
app.secret_key = SECRET

# 登录验证装饰器
def login_required(f):
    @functools.wraps(f)
    def decorated_function(*args, **kwargs):
        if 'logged_in' not in session or not session['logged_in']:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function


@app.route("/healthz")
def healthz():
    return jsonify({"ok": True}), 200


@app.route("/readyz")
def readyz():
    checks = {}
    ok = True
    redis_ok = bool(redis_manager and redis_manager.is_connected())
    checks["redis"] = redis_ok
    if not redis_ok:
        ok = False
    try:
        from visionai.config.settings import ZLM_ENABLED
        from visionai.core.zlm_client import get_zlm_client

        if ZLM_ENABLED:
            zlm = get_zlm_client()
            zlm_ok = bool(zlm and zlm.alive())
            checks["zlm"] = zlm_ok
            if not zlm_ok:
                ok = False
        else:
            checks["zlm"] = "disabled"
    except Exception as e:  # noqa: BLE001
        checks["zlm"] = f"error:{e}"
    try:
        from visionai.config.settings import INFER_BACKEND

        if INFER_BACKEND == "cpp":
            try:
                from visionai.core.infer_client import InferClient

                cli = InferClient()
                live = bool(cli.live())
            except Exception:  # noqa: BLE001
                live = False
            checks["inferd"] = live
            if not live:
                ok = False
        else:
            checks["inferd"] = "python"
    except Exception as e:  # noqa: BLE001
        checks["inferd"] = f"error:{e}"
    try:
        plat = gb28181_store.get_platform(redis_manager)
        if plat.get("enabled"):
            sip_ok = gb28181_store.is_sip_alive(redis_manager)
            checks["sip"] = sip_ok
            if not sip_ok:
                ok = False
        else:
            checks["sip"] = "disabled"
    except Exception as e:  # noqa: BLE001
        checks["sip"] = f"error:{e}"
    return jsonify({"ready": ok, "checks": checks}), (200 if ok else 503)


@app.route("/api/metrics")
@login_required
def api_metrics():
    from visionai.core.runtime_metrics import snapshot_metrics

    return jsonify(snapshot_metrics())


@app.route("/api/zlm/status")
@login_required
def api_zlm_status():
    from visionai.config.settings import ZLM_ENABLED, ZLM_PUBLIC_HOST
    from visionai.core.zlm_client import get_zlm_client, stream_key_for_id

    if not ZLM_ENABLED:
        return jsonify({"enabled": False})
    zlm = get_zlm_client()
    probe = zlm.probe() if zlm else {"alive": False, "auth_ok": False, "message": "client unavailable"}
    alive = bool(probe.get("alive") and probe.get("auth_ok"))
    streams = []
    if redis_manager and alive and zlm:
        from visionai.config.stream_access import ACCESS_GB28181, normalize_access_method
        from visionai.core.gb_play import current_gb_rtp_name, gb_ids_from_stream

        for s in redis_manager.get_streams() or []:
            sid = (s.get("id") or "").strip()
            if not sid:
                continue
            access = normalize_access_method(s.get("access_method"), stream=s)
            if access == ACCESS_GB28181:
                did, cid = gb_ids_from_stream(s)
                gb = s.get("gb28181") if isinstance(s.get("gb28181"), dict) else {}
                stored = str(gb.get("zlm_stream") or "").strip()
                got = current_gb_rtp_name(did, cid) if did and cid else ""
                streams.append(
                    {
                        "id": sid,
                        "name": s.get("name"),
                        "zlm_stream": got or stored,
                        "online": bool(got),
                        "play": zlm.play_urls(got, host=ZLM_PUBLIC_HOST, app="rtp") if got else {},
                    }
                )
                continue
            sk = stream_key_for_id(sid)
            streams.append(
                {
                    "id": sid,
                    "name": s.get("name"),
                    "zlm_stream": sk,
                    "online": zlm.is_online(sk),
                    "play": zlm.play_urls(sk, host=ZLM_PUBLIC_HOST),
                }
            )
    return jsonify(
        {
            "enabled": True,
            "alive": alive,
            "reachable": bool(probe.get("alive")),
            "auth_ok": bool(probe.get("auth_ok")),
            "message": probe.get("message") or "",
            "streams": streams,
        }
    )


@app.route("/api/zlm/ensure-proxy", methods=["POST"])
@login_required
def api_zlm_ensure_proxy():
    """为指定流建立/复用 ZLM 拉流代理，返回播放地址。"""
    from visionai.config.settings import ZLM_ENABLED, ZLM_PUBLIC_HOST
    from visionai.core.zlm_client import get_zlm_client

    if not ZLM_ENABLED:
        return jsonify({"success": False, "message": "ZLM 未启用"}), 400
    body = request.get_json(silent=True) or {}
    stream_id = str(body.get("stream_id") or "").strip()
    if not stream_id:
        return jsonify({"success": False, "message": "缺少 stream_id"}), 400
    zlm = get_zlm_client()
    if not zlm or not zlm.alive():
        return jsonify({"success": False, "message": "ZLM 不可用或鉴权失败"}), 503
    source_url = _stream_url_by_id(stream_id)
    if not source_url:
        return jsonify({"success": False, "message": "未找到流或 RTSP URL"}), 404
    proxied = zlm.ensure_proxy(stream_id, source_url)
    if not proxied.get("success"):
        return jsonify(
            {"success": False, "message": proxied.get("message") or "代理失败"}
        ), 502
    play = proxied.get("play") or zlm.play_urls(
        proxied.get("stream") or stream_id, host=ZLM_PUBLIC_HOST
    )
    return jsonify(
        {
            "success": True,
            "online": bool(proxied.get("online")),
            "stream": proxied.get("stream"),
            "local_rtsp": proxied.get("local_rtsp"),
            "play": play,
        }
    )


@app.route("/api/zlm/webrtc/play", methods=["POST"])
@login_required
def api_zlm_webrtc_play():
    """ZLM WebRTC play：确保拉流代理后，转发浏览器 offer SDP，返回 answer。"""
    from visionai.config.settings import (
        ZLM_ENABLED,
        ZLM_PUBLIC_HOST,
        ZLM_RTC_PORT,
    )
    from visionai.core.zlm_client import get_zlm_client, stream_key_for_id

    if not ZLM_ENABLED:
        return jsonify({"success": False, "message": "ZLM 未启用"}), 400
    body = request.get_json(silent=True) or {}
    stream_id = str(body.get("stream_id") or "").strip()
    offer_sdp = str(body.get("sdp") or "").strip()
    if not stream_id or not offer_sdp:
        return jsonify({"success": False, "message": "缺少 stream_id 或 sdp"}), 400

    zlm = get_zlm_client()
    if not zlm or not zlm.alive():
        return jsonify({"success": False, "message": "ZLM 不可用或鉴权失败"}), 503

    play_app = str(body.get("app") or "").strip().lower()
    zlm_stream = str(body.get("stream") or stream_id).strip()
    if play_app == "rtp":
        if not zlm.is_rtp_online(zlm_stream):
            return jsonify({"success": False, "message": "国标媒体未上线，请稍后重试"}), 503
        result = zlm.webrtc_play(
            zlm_stream,
            offer_sdp,
            public_host=ZLM_PUBLIC_HOST,
            rtc_port=ZLM_RTC_PORT,
            app="rtp",
        )
        if not result.get("success"):
            return jsonify(result), 502
        return jsonify(result)

    source_url = _stream_url_by_id(stream_id)
    if not source_url:
        return jsonify({"success": False, "message": "未找到流或 RTSP URL"}), 404

    proxied = zlm.ensure_proxy(stream_id, source_url)
    sk = stream_key_for_id(stream_id)
    online = bool(proxied.get("online")) or zlm.is_online(sk)
    if not proxied.get("success") and not online:
        return jsonify(
            {
                "success": False,
                "message": proxied.get("message") or "ZLM 拉流代理失败",
            }
        ), 502
    if not online:
        return jsonify(
            {
                "success": False,
                "message": "ZLM 代理未上线，请稍后重试或检查摄像机 RTSP",
            }
        ), 503

    result = zlm.webrtc_play(
        stream_id,
        offer_sdp,
        public_host=ZLM_PUBLIC_HOST,
        rtc_port=ZLM_RTC_PORT,
    )
    if not result.get("success"):
        return jsonify(result), 502
    return jsonify(result)


@app.route('/')
@login_required
def index():
    """管理界面首页"""
    return render_template('admin.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    """登录页面"""
    if request.method == 'POST':
        secret_key = request.form.get('secret_key')
        if secret_key == SECRET:
            session['logged_in'] = True
            return redirect(url_for('index'))
        else:
            return render_template('login.html', error='秘钥错误')
    return render_template('login.html')

@app.route('/api/detection-catalog', methods=['GET'])
@login_required
def get_detection_catalog():
    """COCO 80 类 + 内置扩展 + 已部署专模，供前端展示「系统支持」与配置项。"""
    return jsonify(catalog_items_for_api())


@app.route('/api/system/config', methods=['GET'])
@login_required
def get_system_config():
    """结构化配置单元（可编辑字段 + 只读说明/当前生效值）。"""
    try:
        return jsonify(
            {
                "success": True,
                "meta": config_meta(),
                "units": read_structured_units(),
            }
        )
    except Exception as ex:  # noqa: BLE001
        return jsonify({"success": False, "message": str(ex)}), 500


@app.route('/api/system/config', methods=['PUT'])
@login_required
def put_system_config():
    """按字段更新 config.ini（保留注释与其余内容，全配置重启后生效）。"""
    try:
        data = request.get_json(silent=True) or {}
        updates = data.get("updates")
        if not isinstance(updates, dict):
            return jsonify({"success": False, "message": "缺少 updates 对象"}), 400
        path = patch_config_updates(updates)
        return jsonify(
            {
                "success": True,
                "message": "已保存到 config.ini，请重启服务后全配置生效",
                "path": path,
                "restart_required": True,
            }
        )
    except ValueError as ex:
        return jsonify({"success": False, "message": str(ex)}), 400
    except Exception as ex:  # noqa: BLE001
        return jsonify({"success": False, "message": str(ex)}), 500


@app.route('/api/streams', methods=['GET'])
@login_required
def get_streams():
    """获取视频流配置"""
    if not redis_manager:
        return jsonify([])
    
    # 从Redis获取流配置
    try:
        for d in gb28181_store.list_devices(redis_manager) or []:
            gb28181_store.sync_analysis_stream_names(redis_manager, d)
    except Exception:  # noqa: BLE001
        pass
    streams = redis_manager.get_streams()
    
    # 获取流配置并添加状态信息
    streams_with_status = []
    for stream in streams:
        stream_copy = stream.copy()
        raw_det = stream_copy.get('detections')
        stream_copy['detections'] = normalize_detections(raw_det if isinstance(raw_det, dict) else None)
        stream_copy['alert_email_enabled'] = normalize_stream_alert_email_enabled(
            stream_copy.get('alert_email_enabled')
        )
        stream_copy['alert_webhook_urls'] = normalize_stream_webhook_urls(
            stream_copy.get('alert_webhook_urls')
        )
        stream_copy['alert_webhook_enabled'] = normalize_stream_alert_webhook_enabled(
            stream_copy.get('alert_webhook_enabled')
        )
        stream_copy['face_recognition_config'] = normalize_face_recognition_config(
            stream_copy.get('face_recognition_config')
        )
        stream_copy['plate_recognition_config'] = normalize_plate_recognition_config(
            stream_copy.get('plate_recognition_config')
        )
        apply_access_fields(stream_copy)
        apply_analyze_field(stream_copy)
        # 添加状态信息（Redis 跨进程；worker 写入，API 读取）
        nm = (stream.get("name") or "").strip()
        stream_copy['status'] = get_stream_status(nm, "离线")
        streams_with_status.append(stream_copy)
    return jsonify(streams_with_status)

@app.route('/api/stream-status', methods=['GET'])
@login_required
def get_stream_status_api():
    """获取视频流状态"""
    return jsonify(get_all_stream_statuses())

@app.route('/api/streams', methods=['POST'])
@login_required
def save_streams():
    """保存视频流配置到Redis"""
    try:
        streams = request.get_json()
        
        # 验证配置数据
        if not isinstance(streams, list):
            return jsonify({'success': False, 'message': '无效的配置格式'})
        
        # 检查是否为空数组
        if len(streams) == 0:
            return jsonify({'success': False, 'message': '视频配置不能为空'})
        
        if not redis_manager:
            return jsonify({'success': False, 'message': 'Redis未连接'})
        
        import uuid
        
        # 为每个流生成ID（如果没有的话）
        for stream in streams:
            was_new = not stream.get('id')
            if was_new:
                stream['id'] = f"stream_{uuid.uuid4().hex[:8]}"
            d = stream.get('detections')
            stream['detections'] = normalize_detections(d if isinstance(d, dict) else None)
            stream['alert_emails'] = normalize_stream_alert_emails(stream.get('alert_emails'))
            stream['alert_email_enabled'] = normalize_stream_alert_email_enabled(
                stream.get('alert_email_enabled')
            )
            stream['alert_webhook_urls'] = normalize_stream_webhook_urls(
                stream.get('alert_webhook_urls')
            )
            stream['alert_webhook_enabled'] = normalize_stream_alert_webhook_enabled(
                stream.get('alert_webhook_enabled')
            )
            stream['face_recognition_config'] = normalize_face_recognition_config(
                stream.get('face_recognition_config')
            )
            stream['plate_recognition_config'] = normalize_plate_recognition_config(
                stream.get('plate_recognition_config')
            )
            apply_access_fields(stream)
            apply_analyze_field(stream, default=False if was_new else None)
        
        # 保存到Redis
        success = redis_manager.save_streams(streams)

        if success:
            known = get_all_stream_statuses()
            for stream in streams:
                n = (stream.get("name") or "").strip()
                if n and n not in known:
                    set_stream_status(n, "离线")
            stream_sync.notify_streams_changed()
            return jsonify({'success': True, 'message': '视频配置保存成功'})
        else:
            return jsonify({'success': False, 'message': '保存视频配置失败'})
    
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})


@app.route("/api/onvif/discover", methods=["POST"])
@login_required
def onvif_discover():
    """局域网 WS-Discovery 扫描 ONVIF 设备。"""
    limited = onvif_client.check_discover_rate_limit()
    if limited:
        return jsonify({"success": False, "message": limited}), 429
    data = request.get_json(silent=True) or {}
    timeout_sec = data.get("timeout_sec", 5)
    try:
        devices = onvif_client.discover_devices(timeout_sec=float(timeout_sec))
        return jsonify({"success": True, "devices": devices, "count": len(devices)})
    except Exception as ex:  # noqa: BLE001
        return jsonify({"success": False, "message": str(ex)}), 500


@app.route("/api/onvif/probe", methods=["POST"])
@login_required
def onvif_probe():
    """探测设备鉴权、信息与 Media/RTSP 可用性。"""
    limited = onvif_client.check_probe_rate_limit()
    if limited:
        return jsonify({"success": False, "message": limited}), 429
    data = request.get_json(silent=True) or {}
    host = (data.get("host") or "").strip()
    if not host:
        return jsonify({"success": False, "message": "缺少 host"}), 400
    try:
        port = int(data.get("port") or 80)
    except (TypeError, ValueError):
        port = 80
    username = data.get("username") or ""
    password = data.get("password") or ""
    result = onvif_client.probe_device(host, port, username, password)
    code = 200 if result.get("ok") else 400
    return jsonify({"success": bool(result.get("ok")), **result}), code


@app.route("/api/onvif/profiles", methods=["POST"])
@login_required
def onvif_profiles():
    """列举 Media Profile 及 RTSP URI。"""
    data = request.get_json(silent=True) or {}
    host = (data.get("host") or "").strip()
    if not host:
        return jsonify({"success": False, "message": "缺少 host"}), 400
    try:
        port = int(data.get("port") or 80)
    except (TypeError, ValueError):
        port = 80
    username = data.get("username") or ""
    password = data.get("password") or ""
    try:
        profiles = onvif_client.list_profiles(host, port, username, password)
        usable = [
            p
            for p in profiles
            if (p.get("rtsp_url") or "").lower().startswith(("rtsp://", "rtsps://"))
        ]
        if not usable:
            return jsonify(
                {
                    "success": False,
                    "message": "未获取到有效 RTSP 地址",
                    "profiles": profiles,
                }
            ), 400
        return jsonify({"success": True, "profiles": usable})
    except Exception as ex:  # noqa: BLE001
        return jsonify({"success": False, "message": str(ex)}), 500


@app.route("/api/onvif/add-stream", methods=["POST"])
@login_required
def onvif_add_stream():
    """将 ONVIF 解析出的 RTSP 追加到 Redis streamlist。"""
    if not redis_manager:
        return jsonify({"success": False, "message": "Redis未连接"}), 500
    data = request.get_json(silent=True) or {}
    name = (data.get("name") or "").strip()
    rtsp_url = normalize_rtsp_url((data.get("rtsp_url") or "").strip())
    if not name:
        return jsonify({"success": False, "message": "缺少流名称"}), 400
    if not rtsp_url.lower().startswith(("rtsp://", "rtsps://")):
        return jsonify({"success": False, "message": "无效的 RTSP 地址"}), 400

    import uuid

    onvif_meta = data.get("onvif") if isinstance(data.get("onvif"), dict) else {}
    # 元数据不存密码
    safe_meta = {
        "host": str(onvif_meta.get("host") or "").strip(),
        "port": int(onvif_meta.get("port") or 80) if onvif_meta.get("port") not in (None, "") else 80,
        "profile_token": str(onvif_meta.get("profile_token") or "").strip(),
        "manufacturer": str(onvif_meta.get("manufacturer") or "").strip(),
        "model": str(onvif_meta.get("model") or "").strip(),
    }
    talk_supported = bool(data.get("talk_supported"))
    talk_protocol = str(data.get("talk_protocol") or "").strip()
    talk_codec = str(data.get("talk_codec") or "").strip()
    talk_detail = str(data.get("talk_detail") or "").strip()[:400]

    stream = {
        "id": f"stream_{uuid.uuid4().hex[:8]}",
        "name": name,
        "url": rtsp_url,
        "access_method": ACCESS_ONVIF,
        "enabled": True,
        "analyze": False,
        "detections": normalize_detections(None),
        "alert_emails": [],
        "alert_email_enabled": True,
        "alert_webhook_urls": [],
        "alert_webhook_enabled": False,
        "face_recognition_config": default_face_recognition_config(),
        "plate_recognition_config": default_plate_recognition_config(),
        "onvif": safe_meta,
        "talk_supported": talk_supported,
        "talk_protocol": talk_protocol,
        "talk_codec": talk_codec,
        "talk_detail": talk_detail,
    }
    apply_access_fields(stream)
    apply_analyze_field(stream, default=False)

    existing = redis_manager.get_streams() or []
    # 同名提示仍允许加入（子码流场景由前端弱提示）
    if not redis_manager.save_stream(stream):
        return jsonify({"success": False, "message": "写入 Redis 失败"}), 500

    if name not in get_all_stream_statuses():
        set_stream_status(name, "离线")
    stream_sync.notify_streams_changed()

    streams = redis_manager.get_streams() or []
    return jsonify(
        {
            "success": True,
            "message": "已接入平台，请点「接入AI分析」后再配置检测",
            "stream": stream,
            "streams": streams,
            "count": len(streams),
            "existing_count_before": len(existing),
        }
    )


def _stream_by_id(stream_id: str):
    if not redis_manager or not stream_id:
        return None
    for s in redis_manager.get_streams() or []:
        if str(s.get("id") or "") == str(stream_id):
            return s
    return None


def _try_remove_zlm_proxy(stream_id: str) -> None:
    try:
        from visionai.core.zlm_client import get_zlm_client

        zlm = get_zlm_client()
        if zlm is not None:
            zlm.remove_proxy(stream_id)
    except Exception:  # noqa: BLE001
        pass


@app.route("/api/streams/<stream_id>", methods=["PATCH"])
@login_required
def patch_stream(stream_id: str):
    """更新单路流（名称、URL、接入元数据等），保留策略字段。"""
    if not redis_manager:
        return jsonify({"success": False, "message": "Redis未连接"}), 500
    stream = _stream_by_id(stream_id)
    if not stream:
        return jsonify({"success": False, "message": "未找到视频流"}), 404
    data = request.get_json(silent=True) or {}
    if "name" in data:
        name = str(data.get("name") or "").strip()
        if not name:
            return jsonify({"success": False, "message": "名称不能为空"}), 400
        stream["name"] = name
    if "url" in data:
        url = normalize_rtsp_url(str(data.get("url") or "").strip())
        if not url:
            return jsonify({"success": False, "message": "URL 不能为空"}), 400
        low = url.lower()
        if not low.startswith(("rtsp://", "rtsps://")):
            return jsonify({"success": False, "message": "仅支持 rtsp/rtsps"}), 400
        stream["url"] = url
    if "enabled" in data:
        stream["enabled"] = bool(data.get("enabled"))
    if "analyze" in data:
        stream["analyze"] = bool(data.get("analyze"))
    if "onvif" in data and isinstance(data.get("onvif"), dict):
        prev = stream.get("onvif") if isinstance(stream.get("onvif"), dict) else {}
        merged = dict(prev)
        for k in ("host", "port", "profile_token", "manufacturer", "model"):
            if k in data["onvif"]:
                merged[k] = data["onvif"][k]
        stream["onvif"] = merged
    if "gb28181" in data and isinstance(data.get("gb28181"), dict):
        stream["gb28181"] = data["gb28181"]
    if "access_method" in data:
        stream["access_method"] = normalize_access_method(
            data.get("access_method"), stream=stream
        )
    apply_access_fields(stream)
    apply_analyze_field(stream)
    if not redis_manager.save_stream(stream):
        return jsonify({"success": False, "message": "保存失败"}), 500
    stream_sync.notify_streams_changed()
    return jsonify({"success": True, "stream": apply_analyze_field(apply_access_fields(dict(stream)))})


@app.route("/api/streams/<stream_id>", methods=["DELETE"])
@login_required
def delete_stream_api(stream_id: str):
    """删除单路流。"""
    if not redis_manager:
        return jsonify({"success": False, "message": "Redis未连接"}), 500
    stream = _stream_by_id(stream_id)
    if not stream:
        return jsonify({"success": False, "message": "未找到视频流"}), 404
    name = (stream.get("name") or "").strip()
    gb = stream.get("gb28181") if isinstance(stream.get("gb28181"), dict) else {}
    if stream.get("access_method") == ACCESS_GB28181 or gb:
        try:
            from visionai.core.sip import cmd as sip_cmd

            sip_cmd.enqueue_cmd(
                "bye",
                device_id=str(gb.get("device_id") or ""),
                channel_id=str(gb.get("channel_id") or ""),
            )
        except Exception:  # noqa: BLE001
            pass
    if not redis_manager.delete_stream(stream_id):
        return jsonify({"success": False, "message": "删除失败"}), 500
    _try_remove_zlm_proxy(stream_id)
    if name:
        try:
            set_stream_status(name, "离线")
        except Exception:  # noqa: BLE001
            pass
    stream_sync.notify_streams_changed()
    return jsonify({"success": True, "message": "已删除", "stream_id": stream_id})


@app.route("/api/onvif/refresh-stream", methods=["POST"])
@login_required
def onvif_refresh_stream():
    """用账号密码重新拉取 Profile RTSP，更新已有 ONVIF 流的 url。"""
    if not redis_manager:
        return jsonify({"success": False, "message": "Redis未连接"}), 500
    data = request.get_json(silent=True) or {}
    stream_id = (data.get("stream_id") or "").strip()
    stream = _stream_by_id(stream_id)
    if not stream:
        return jsonify({"success": False, "message": "未找到视频流"}), 404
    ov = stream.get("onvif") if isinstance(stream.get("onvif"), dict) else {}
    host = str(data.get("host") or ov.get("host") or "").strip()
    if not host:
        return jsonify({"success": False, "message": "缺少 ONVIF host"}), 400
    try:
        port = int(data.get("port") or ov.get("port") or 80)
    except (TypeError, ValueError):
        port = 80
    username = data.get("username") or ""
    password = data.get("password") or ""
    try:
        profiles = onvif_client.list_profiles(host, port, username, password)
    except Exception as ex:  # noqa: BLE001
        return jsonify({"success": False, "message": f"拉取 Profile 失败: {ex}"}), 400
    token = str(data.get("profile_token") or ov.get("profile_token") or "").strip()
    chosen = None
    for p in profiles:
        if token and str(p.get("token") or "") == token:
            chosen = p
            break
    if chosen is None:
        usable = [
            p
            for p in profiles
            if (p.get("rtsp_url") or "").lower().startswith(("rtsp://", "rtsps://"))
        ]
        chosen = usable[0] if usable else None
    if not chosen:
        return jsonify({"success": False, "message": "未获取到有效 RTSP"}), 400
    rtsp_url = normalize_rtsp_url((chosen.get("rtsp_url") or "").strip())
    stream["url"] = rtsp_url
    stream["access_method"] = ACCESS_ONVIF
    stream["onvif"] = {
        "host": host,
        "port": port,
        "profile_token": str(chosen.get("token") or token),
        "manufacturer": str(ov.get("manufacturer") or ""),
        "model": str(ov.get("model") or ""),
    }
    # 可选刷新对讲能力
    if data.get("probe_talk"):
        from visionai.core import talk_session as talk_mod

        result = talk_mod.probe_stream_talk(stream)
        stream["talk_supported"] = bool(result.get("talk_supported"))
        stream["talk_protocol"] = str(result.get("talk_protocol") or "")
        stream["talk_codec"] = str(result.get("codec") or "")
        stream["talk_detail"] = str(result.get("detail") or result.get("error") or "")[:400]
    apply_access_fields(stream)
    if not redis_manager.save_stream(stream):
        return jsonify({"success": False, "message": "写入失败"}), 500
    stream_sync.notify_streams_changed()
    return jsonify(
        {
            "success": True,
            "message": "已更新 RTSP",
            "stream": stream,
            "profiles": profiles,
        }
    )


@app.route("/api/gb28181/platform", methods=["GET"])
@login_required
def gb28181_get_platform():
    plat = gb28181_store.get_platform(redis_manager)
    return jsonify(
        {
            "success": True,
            "platform": plat,
            "sip_ready": gb28181_store.is_sip_alive(redis_manager),
        }
    )


@app.route("/api/gb28181/platform", methods=["PUT"])
@login_required
def gb28181_put_platform():
    data = request.get_json(silent=True) or {}
    try:
        plat = gb28181_store.save_platform(redis_manager, data)
        return jsonify({"success": True, "platform": plat, "message": "平台参数已保存"})
    except Exception as ex:  # noqa: BLE001
        return jsonify({"success": False, "message": str(ex)}), 500


@app.route("/api/gb28181/devices", methods=["GET"])
@login_required
def gb28181_list_devices():
    plat = gb28181_store.get_platform(redis_manager)
    devices = gb28181_store.list_devices_live(redis_manager)
    for d in devices:
        try:
            gb28181_store.sync_analysis_stream_names(redis_manager, d)
        except Exception:  # noqa: BLE001
            pass
    streams = redis_manager.get_streams() or []
    items = []
    for d in devices:
        row = gb28181_store.attach_monitor_status(d, streams)
        row["camera_config"] = gb28181_store.device_camera_hint(plat, d)
        items.append(row)
    next_ids = {}
    try:
        next_ids = gb28181_store.allocate_sip_ids(redis_manager)
    except Exception as ex:  # noqa: BLE001
        next_ids = {"error": str(ex)}
    return jsonify(
        {
            "success": True,
            "devices": items,
            "platform": plat,
            "next_allocation": next_ids,
            "sip_ready": gb28181_store.is_sip_alive(redis_manager),
            "hint": "复制参数含上级平台与本机 SIP 用户/认证ID/通道编码；设备按清单填写后由 visionai-sip 接收注册。",
        }
    )


@app.route("/api/gb28181/preview-ids", methods=["GET"])
@login_required
def gb28181_preview_ids():
    """预览下一次自动分配的 SIP 用户名 / 认证 ID（不落库）。

    注意：路径勿挂在 ``/devices/<id>`` 下，否则会被动态路由吞掉并返回 405 HTML。
    """
    try:
        ids = gb28181_store.allocate_sip_ids(redis_manager)
        plat = gb28181_store.get_platform(redis_manager)
        return jsonify(
            {
                "success": True,
                "allocation": ids,
                "platform": {
                    "server_id": plat.get("server_id"),
                    "domain": plat.get("domain"),
                    "sip_port": plat.get("sip_port"),
                    "sip_host": plat.get("sip_host"),
                    "media_ip": plat.get("media_ip"),
                    "transport": plat.get("transport"),
                },
            }
        )
    except Exception as ex:  # noqa: BLE001
        return jsonify({"success": False, "message": str(ex)}), 400


@app.route("/api/gb28181/preview-channel-id", methods=["GET"])
@login_required
def gb28181_preview_channel_id():
    """预览下一个自动分配的通道 ID（不落库）。"""
    try:
        cid = gb28181_store.allocate_channel_id(redis_manager)
        return jsonify({"success": True, "channel_id": cid})
    except Exception as ex:  # noqa: BLE001
        return jsonify({"success": False, "message": str(ex)}), 400


@app.route("/api/gb28181/devices", methods=["POST"])
@login_required
def gb28181_upsert_device():
    """新建或更新设备端 SIP 接入账号。"""
    data = request.get_json(silent=True) or {}
    try:
        # 新建默认空通道；通道在「通道配置」中维护
        if "channels" not in data and not str(data.get("channel_id") or "").strip():
            data = {**data, "channels": []}
        row = gb28181_store.upsert_device(redis_manager, data)
        plat = gb28181_store.get_platform(redis_manager)
        return jsonify(
            {
                "success": True,
                "device": row,
                "camera_config": gb28181_store.device_camera_hint(plat, row),
                "message": "SIP 接入账号已保存",
            }
        )
    except ValueError as ex:
        return jsonify({"success": False, "message": str(ex)}), 400
    except Exception as ex:  # noqa: BLE001
        return jsonify({"success": False, "message": str(ex)}), 500


@app.route("/api/gb28181/refresh-status", methods=["POST"])
@login_required
def gb28181_refresh_device_status():
    """刷新设备注册在线状态（合并 SIP 运行时；无信令时标记离线）。"""
    try:
        devices, meta = gb28181_store.refresh_device_statuses(redis_manager)
        plat = gb28181_store.get_platform(redis_manager)
        streams = redis_manager.get_streams() or []
        items = []
        for d in devices:
            row = gb28181_store.attach_monitor_status(d, streams)
            row["camera_config"] = gb28181_store.device_camera_hint(plat, d)
            items.append(row)
        return jsonify(
            {
                "success": True,
                "devices": items,
                "sip_ready": bool(meta.get("sip_ready")),
                "message": meta.get("message") or "已刷新",
                "refreshed_at": meta.get("refreshed_at") or "",
            }
        )
    except Exception as ex:  # noqa: BLE001
        return jsonify({"success": False, "message": str(ex)}), 500


@app.route("/api/gb28181/devices/<device_id>", methods=["PATCH"])
@login_required
def gb28181_patch_device(device_id: str):
    """更新已有账号的名称 / 密码（不可改 SIP 用户名与认证 ID；通道走通道接口）。"""
    if device_id in ("preview-ids", "refresh-status", "preview-channel-id"):
        return jsonify({"success": False, "message": "无效的设备 ID"}), 400
    prev = gb28181_store.get_device(redis_manager, device_id)
    if not prev:
        return jsonify({"success": False, "message": "账号不存在"}), 404
    data = request.get_json(silent=True) or {}
    payload = {
        "sip_user": prev.get("sip_user") or device_id,
        "device_id": prev.get("sip_user") or device_id,
        "auth_id": prev.get("auth_id") or device_id,
        "auto_allocate": False,
        "name": data["name"] if "name" in data else prev.get("name"),
        "password": data["password"] if "password" in data else prev.get("password"),
        "remark": data["remark"] if "remark" in data else prev.get("remark"),
        "channels": prev.get("channels") or [],
        "status": prev.get("status"),
        "source": "provisioned",
    }
    try:
        row = gb28181_store.upsert_device(redis_manager, payload)
        plat = gb28181_store.get_platform(redis_manager)
        return jsonify(
            {
                "success": True,
                "device": row,
                "camera_config": gb28181_store.device_camera_hint(plat, row),
                "message": "已更新",
            }
        )
    except Exception as ex:  # noqa: BLE001
        return jsonify({"success": False, "message": str(ex)}), 500


@app.route("/api/gb28181/devices/<device_id>/channels", methods=["GET"])
@login_required
def gb28181_list_channels(device_id: str):
    prev = gb28181_store.get_device(redis_manager, device_id)
    if not prev:
        return jsonify({"success": False, "message": "账号不存在"}), 404
    try:
        gb28181_store.sync_analysis_stream_names(redis_manager, prev)
        prev = gb28181_store.get_device(redis_manager, device_id) or prev
    except Exception:  # noqa: BLE001
        pass
    row = gb28181_store.attach_monitor_status(prev, redis_manager.get_streams() or [])
    return jsonify(
        {
            "success": True,
            "device_id": row.get("sip_user") or device_id,
            "name": row.get("name") or "",
            "channels": row.get("channels") or [],
            "monitored_count": row.get("monitored_count") or 0,
        }
    )


@app.route("/api/gb28181/devices/<device_id>/channels", methods=["POST"])
@login_required
def gb28181_add_channel(device_id: str):
    data = request.get_json(silent=True) or {}
    try:
        row = gb28181_store.add_channel(
            redis_manager,
            device_id,
            channel_id=str(data.get("channel_id") or "").strip(),
            alias=str(data.get("alias") or data.get("name") or "").strip(),
            auto_allocate=bool(data.get("auto_allocate", True)),
        )
        return jsonify(
            {
                "success": True,
                "device": row,
                "channels": row.get("channels") or [],
                "message": "通道已添加",
            }
        )
    except ValueError as ex:
        return jsonify({"success": False, "message": str(ex)}), 400
    except Exception as ex:  # noqa: BLE001
        return jsonify({"success": False, "message": str(ex)}), 500


@app.route("/api/gb28181/devices/<device_id>/channels/<channel_id>", methods=["PATCH"])
@login_required
def gb28181_patch_channel(device_id: str, channel_id: str):
    data = request.get_json(silent=True) or {}
    try:
        row = gb28181_store.update_channel(
            redis_manager,
            device_id,
            channel_id,
            new_channel_id=data.get("channel_id") if "channel_id" in data else None,
            alias=data.get("alias") if "alias" in data else (data.get("name") if "name" in data else None),
            index=data.get("index") if "index" in data else None,
        )
        return jsonify(
            {
                "success": True,
                "device": row,
                "channels": row.get("channels") or [],
                "message": "通道已更新",
            }
        )
    except ValueError as ex:
        return jsonify({"success": False, "message": str(ex)}), 400
    except Exception as ex:  # noqa: BLE001
        return jsonify({"success": False, "message": str(ex)}), 500


@app.route("/api/gb28181/devices/<device_id>/channels/<channel_id>", methods=["DELETE"])
@login_required
def gb28181_delete_channel(device_id: str, channel_id: str):
    try:
        row = gb28181_store.delete_channel(redis_manager, device_id, channel_id)
        return jsonify(
            {
                "success": True,
                "device": row,
                "channels": row.get("channels") or [],
                "message": "通道已删除",
            }
        )
    except ValueError as ex:
        return jsonify({"success": False, "message": str(ex)}), 400
    except Exception as ex:  # noqa: BLE001
        return jsonify({"success": False, "message": str(ex)}), 500


def _gb_require_channel(device_id: str, channel_id: str):
    if not redis_manager:
        return None, None, (jsonify({"success": False, "message": "Redis未连接"}), 500)
    plat = gb28181_store.get_platform(redis_manager)
    if not plat.get("media_ip") or not plat.get("media_port"):
        return None, None, (
            jsonify({"success": False, "message": "请先在「媒体收流」填写 media_ip 与端口范围"}),
            400,
        )
    if not gb28181_store.is_sip_alive(redis_manager):
        return None, None, (jsonify({"success": False, "message": "信令进程未运行"}), 503)
    device = gb28181_store.get_device(redis_manager, device_id)
    if not device:
        return None, None, (jsonify({"success": False, "message": "账号不存在"}), 404)
    channel_id = (channel_id or "").strip()
    channels = gb28181_store.normalize_channels(device.get("channels") or [])
    if not channel_id:
        return None, None, (jsonify({"success": False, "message": "缺少通道 ID"}), 400)
    if not any(c.get("channel_id") == channel_id for c in channels):
        return None, None, (jsonify({"success": False, "message": "通道不存在"}), 404)
    return device, channel_id, None


def _gb_invite_channel(device_id: str, channel_id: str):
    from visionai.core.sip import cmd as sip_cmd

    rid = sip_cmd.enqueue_cmd("invite", device_id=device_id, channel_id=channel_id)
    return sip_cmd.wait_result(rid, timeout_sec=28.0)


@app.route("/api/gb28181/devices/<device_id>/channels/<channel_id>/preview", methods=["POST"])
@login_required
def gb28181_preview_play(device_id: str, channel_id: str):
    """点播预览：Invite 收流，不写入监控列表。已在监控中则直接复用。"""
    device, channel_id, err = _gb_require_channel(device_id, channel_id)
    if err:
        return err
    existing = gb28181_store.find_stream_for_channel(
        redis_manager.get_streams() or [], device_id, channel_id
    )
    if existing:
        return jsonify(
            {
                "success": True,
                "already_monitored": True,
                "stream_id": existing.get("id") or "",
                "name": existing.get("name") or "",
                "device_id": device_id,
                "channel_id": channel_id,
            }
        )
    try:
        result = _gb_invite_channel(device_id, channel_id)
    except Exception as ex:  # noqa: BLE001
        return jsonify({"success": False, "message": str(ex)}), 500
    if not result.get("ok"):
        return jsonify({"success": False, "message": result.get("message") or "Invite 失败"}), 502
    alias = ""
    for c in gb28181_store.normalize_channels(device.get("channels") or []):
        if c.get("channel_id") == channel_id:
            alias = str(c.get("alias") or "")
            break
    name = alias or f"{device.get('name') or device_id}-{channel_id[-4:]}"
    return jsonify(
        {
            "success": True,
            "already_monitored": False,
            "zlm_app": "rtp",
            "zlm_stream": result.get("stream")
            or gb28181_store.rtp_stream_id(device_id, channel_id),
            "url": result.get("url") or gb28181_store.rtp_pull_url(
                result.get("stream") or gb28181_store.rtp_stream_id(device_id, channel_id)
            ),
            "media_online": result.get("media_online", True),
            "message": result.get("message") or "",
            "name": name,
            "device_id": device_id,
            "channel_id": channel_id,
        }
    )


@app.route("/api/gb28181/devices/<device_id>/channels/<channel_id>/bye", methods=["POST"])
@login_required
def gb28181_preview_bye(device_id: str, channel_id: str):
    """结束点播（未加入监控时关预览用）。已在监控中则不拆流。"""
    device, channel_id, err = _gb_require_channel(device_id, channel_id)
    if err:
        return err
    if gb28181_store.find_stream_for_channel(
        redis_manager.get_streams() or [], device_id, channel_id
    ):
        return jsonify({"success": True, "skipped": True, "message": "通道已在监控中，未发送 BYE"})
    from visionai.core.sip import cmd as sip_cmd

    try:
        rid = sip_cmd.enqueue_cmd("bye", device_id=device_id, channel_id=channel_id)
        result = sip_cmd.wait_result(rid, timeout_sec=8.0)
    except Exception as ex:  # noqa: BLE001
        return jsonify({"success": False, "message": str(ex)}), 500
    return jsonify({"success": bool(result.get("ok")), "message": result.get("message") or "已结束点播"})


@app.route("/api/gb28181/devices/<device_id>/channels/<channel_id>/ptz", methods=["POST"])
@login_required
def gb28181_ptz(device_id: str, channel_id: str):
    """国标云台：SIP MESSAGE DeviceControl / PTZCmd。"""
    device, channel_id, err = _gb_require_channel(device_id, channel_id)
    if err:
        return err
    data = request.get_json(silent=True) or {}
    action = str(data.get("action") or "").strip().lower()
    if not action:
        return jsonify({"success": False, "message": "缺少 action"}), 400
    from visionai.core.sip import cmd as sip_cmd
    from visionai.core.sip.ptz import encode_action

    spec = {
        "action": action,
        "speed": data.get("speed"),
        "address": data.get("address"),
    }
    _, enc_err = encode_action(spec)
    if enc_err:
        return jsonify({"success": False, "message": enc_err}), 400
    try:
        rid = sip_cmd.enqueue_cmd(
            "ptz",
            device_id=device_id,
            channel_id=channel_id,
            **spec,
        )
        result = sip_cmd.wait_result(rid, timeout_sec=3.0)
    except Exception as ex:  # noqa: BLE001
        return jsonify({"success": False, "message": str(ex)}), 500
    if not result.get("ok"):
        return jsonify({"success": False, "message": result.get("message") or "PTZ 失败"}), 502
    return jsonify(
        {
            "success": True,
            "ptz_cmd": result.get("ptz_cmd") or "",
            "channel_id": channel_id,
            "sip_user": device.get("sip_user") or device_id,
        }
    )


@app.route("/api/gb28181/devices/<device_id>/channels/<channel_id>/monitor", methods=["POST"])
@login_required
def gb28181_join_monitor(device_id: str, channel_id: str):
    """Invite 收流并写入 streamlist（接入 AI 分析 / 检测配置）。"""
    device, channel_id, err = _gb_require_channel(device_id, channel_id)
    if err:
        return err
    existing = redis_manager.get_streams() or []
    already = gb28181_store.find_stream_for_channel(existing, device_id, channel_id)
    if already:
        return jsonify(
            {
                "success": True,
                "already_monitored": True,
                "message": "该通道已接入分析",
                "stream": already,
            }
        )

    try:
        result = _gb_invite_channel(device_id, channel_id)
    except Exception as ex:  # noqa: BLE001
        return jsonify({"success": False, "message": str(ex)}), 500
    if not result.get("ok"):
        return jsonify({"success": False, "message": result.get("message") or "Invite 失败"}), 502

    import uuid

    alias = ""
    for c in gb28181_store.normalize_channels(device.get("channels") or []):
        if c.get("channel_id") == channel_id:
            alias = str(c.get("alias") or "")
            break
    name = alias or f"{device.get('name') or device_id}-{channel_id[-4:]}"
    play_stream = str(result.get("stream") or gb28181_store.rtp_stream_id(device_id, channel_id))
    url = result.get("url") or gb28181_store.rtp_pull_url(play_stream)
    stream = {
        "id": f"stream_{uuid.uuid4().hex[:8]}",
        "name": name,
        "url": url,
        "access_method": ACCESS_GB28181,
        "enabled": True,
        "analyze": True,
        "detections": normalize_detections(None),
        "alert_emails": [],
        "alert_email_enabled": True,
        "alert_webhook_urls": [],
        "alert_webhook_enabled": False,
        "face_recognition_config": default_face_recognition_config(),
        "plate_recognition_config": default_plate_recognition_config(),
        "gb28181": {
            "device_id": device_id,
            "channel_id": channel_id,
            "sip_user": device.get("sip_user") or device_id,
            "zlm_stream": play_stream,
        },
    }
    apply_access_fields(stream)
    apply_analyze_field(stream, default=True)
    if not redis_manager.save_stream(stream):
        return jsonify({"success": False, "message": "写入 Redis 失败"}), 500
    if name not in get_all_stream_statuses():
        set_stream_status(name, "离线")
    stream_sync.notify_streams_changed()
    return jsonify(
        {
            "success": True,
            "message": result.get("message") or "已接入分析，请在检测配置中开启检测类型",
            "stream": stream,
            "media_online": result.get("media_online", True),
        }
    )


@app.route("/api/gb28181/devices/<device_id>", methods=["DELETE"])
@login_required
def gb28181_delete_device(device_id: str):
    # 避免把保留字当成设备 ID
    if device_id in ("preview-ids", "refresh-status", "preview-channel-id"):
        return jsonify({"success": False, "message": "无效的设备 ID"}), 400
    ok = gb28181_store.delete_device(redis_manager, device_id)
    if not ok:
        return jsonify({"success": False, "message": "账号不存在或删除失败"}), 404
    return jsonify({"success": True, "message": "已删除 SIP 接入账号"})


@app.route("/api/talk/probe", methods=["POST"])
@login_required
def talk_probe():
    """对已接入流做 ONVIF RTSP Audio Backchannel 探测（可刷新能力标记）。"""
    from visionai.core import talk_session as talk_mod

    data = request.get_json(silent=True) or {}
    stream_id = (data.get("stream_id") or "").strip()
    stream = _stream_by_id(stream_id)
    if not stream:
        return jsonify({"success": False, "message": "未找到视频流"}), 404
    result = talk_mod.probe_stream_talk(stream)
    # 可选写回 Redis
    if data.get("persist") and redis_manager:
        stream["talk_supported"] = bool(result.get("talk_supported"))
        stream["talk_protocol"] = str(result.get("talk_protocol") or "")
        stream["talk_codec"] = str(result.get("codec") or "")
        stream["talk_detail"] = str(result.get("detail") or result.get("error") or "")[:400]
        apply_access_fields(stream)
        redis_manager.save_stream(stream)
    return jsonify({"success": True, **result, "stream_id": stream_id})


@app.route("/api/talk/start", methods=["POST"])
@login_required
def talk_start():
    """开始对讲：建立 RTSP backchannel，浏览器随后 POST G.711 上行。"""
    from visionai.core import talk_session as talk_mod

    data = request.get_json(silent=True) or {}
    stream_id = (data.get("stream_id") or "").strip()
    stream = _stream_by_id(stream_id)
    if not stream:
        return jsonify({"success": False, "message": "未找到视频流"}), 404
    talk_mod.cleanup_stale()
    result = talk_mod.start_talk(stream)
    code = 200 if result.get("success") else 400
    return jsonify(result), code


@app.route("/api/talk/stop", methods=["POST"])
@login_required
def talk_stop():
    from visionai.core import talk_session as talk_mod

    data = request.get_json(silent=True) or {}
    result = talk_mod.stop_talk(
        session_id=str(data.get("session_id") or ""),
        stream_id=str(data.get("stream_id") or ""),
    )
    return jsonify(result)


@app.route("/api/talk/audio", methods=["POST"])
@login_required
def talk_audio():
    """上行 G.711 负载：``application/octet-stream``，Query/Header 带 session_id。"""
    from visionai.core import talk_session as talk_mod

    sid = (
        request.args.get("session_id")
        or request.headers.get("X-Talk-Session")
        or ""
    ).strip()
    if not sid and request.content_type and "json" in (request.content_type or ""):
        data = request.get_json(silent=True) or {}
        sid = str(data.get("session_id") or "").strip()
    if not sid:
        return jsonify({"success": False, "message": "缺少 session_id"}), 400
    payload = request.get_data(cache=False) or b""
    if not payload:
        return jsonify({"success": False, "message": "空音频"}), 400
    if len(payload) > 64 * 1024:
        return jsonify({"success": False, "message": "单包过大"}), 400
    result = talk_mod.push_audio(sid, payload)
    code = 200 if result.get("success") else 400
    return jsonify(result), code


@app.route('/api/config', methods=['GET'])
@login_required
def get_config():
    """获取系统配置"""
    from visionai.config.settings import (
        APP_TIMEZONE,
        ZLM_ENABLED,
        ZLM_PUBLIC_HOST,
        ZLM_RTC_PORT,
    )

    return jsonify({
        'auto_refresh_interval': AUTO_REFRESH_INTERVAL,
        'timezone': APP_TIMEZONE,
        'preview': {
            'zlm_webrtc_enabled': bool(ZLM_ENABLED),
        },
        'smtp': {
            'alert_enabled': bool(SMTP_ALERT_ENABLED),
            'host_configured': bool(SMTP_HOST.strip()),
            'from_configured': bool(SMTP_FROM.strip()),
            'ready': smtp_is_configured(),
        },
        'zlm': {
            'enabled': bool(ZLM_ENABLED),
            'public_host': ZLM_PUBLIC_HOST,
            'rtc_port': ZLM_RTC_PORT,
        },
    })


def _stream_url_by_id(stream_id: str):
    if not stream_id or not redis_manager:
        return None
    for s in redis_manager.get_streams():
        if s.get("id") == stream_id:
            return s.get("url")
    return None


@app.route('/api/stats/alerts-today', methods=['GET'])
@login_required
def alerts_today_count():
    """今日（服务器本地日期）触发的检测/告警记录总数。"""
    if not redis_manager:
        return jsonify({'success': False, 'count': 0})
    try:
        count = redis_manager.count_detections_today()
        return jsonify({'success': True, 'count': count})
    except Exception as e:
        return jsonify({'success': False, 'count': 0, 'message': str(e)})

def _parse_query_datetime(key: str):
    """解析查询参数中的 ISO 日期时间（datetime-local 格式），返回 naive datetime 或 None。"""
    raw = request.args.get(key)
    if not raw or not str(raw).strip():
        return None
    s = str(raw).strip()
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        if dt.tzinfo is not None:
            dt = dt.astimezone().replace(tzinfo=None)
        return dt
    except ValueError:
        return None


@app.route('/api/detections', methods=['GET'])
@login_required
def get_detections():
    """获取检测记录（支持 start/end、stream_id、detection_type 筛选）"""
    if not redis_manager:
        return jsonify({'success': False, 'message': 'Redis未连接'})
    
    try:
        stream_id = request.args.get('stream_id')
        if stream_id is not None and str(stream_id).strip() == "":
            stream_id = None
        limit = int(request.args.get('limit', 50))
        offset = int(request.args.get('offset', 0))
        time_start = _parse_query_datetime("start")
        time_end = _parse_query_datetime("end")
        detection_type = request.args.get("detection_type")
        if detection_type is not None and str(detection_type).strip() == "":
            detection_type = None

        detections, total = redis_manager.get_detections(
            stream_id=stream_id,
            limit=limit,
            offset=offset,
            time_start=time_start,
            time_end=time_end,
            detection_type=detection_type,
        )
        
        return jsonify({
            'success': True,
            'data': detections,
            'total': total
        })
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})

@app.route('/api/detections/<detection_id>', methods=['DELETE'])
@login_required
def delete_detection(detection_id):
    """删除检测记录"""
    if not redis_manager:
        return jsonify({'success': False, 'message': 'Redis未连接'})
    
    try:
        success = redis_manager.delete_detection_by_id(detection_id)
        if success:
            return jsonify({'success': True, 'message': '删除成功'})
        else:
            return jsonify({'success': False, 'message': '删除失败'})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})

@app.route('/api/detections/batch', methods=['DELETE'])
@login_required
def delete_detections_batch():
    """批量删除检测记录"""
    if not redis_manager:
        return jsonify({'success': False, 'message': 'Redis未连接'})
    
    try:
        data = request.get_json()
        detection_ids = data.get('ids', [])
        
        if not detection_ids:
            return jsonify({'success': False, 'message': '请选择要删除的记录'})
        
        count = redis_manager.delete_detections(detection_ids)
        return jsonify({'success': True, 'message': f'已删除{count}条记录', 'count': count})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})

@app.route('/snapshots/<path:filename>')
@login_required
def serve_snapshot(filename):
    """提供截图文件"""
    project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    snapshots_dir = os.path.join(project_root, 'snapshots')
    return send_from_directory(snapshots_dir, filename)


@app.route("/api/alert-image/<detection_id>")
@login_required
def alert_image(detection_id):
    """历史告警缩略图：对象存储或本地路径各选其一。"""
    if not redis_manager:
        abort(503)
    doc = redis_manager.get_detection_by_id(detection_id)
    if not doc:
        abort(404)
    if doc.get("object_key"):
        st = get_object_storage()
        if st:
            try:
                body = st.get_object_bytes(doc["object_key"])
                return Response(body, mimetype="image/jpeg")
            except Exception:
                # 对象存储不可用时回退本地路径（上传失败/仅本地保留场景）
                pass
    ip = doc.get("image_path") or ""
    if ip and os.path.isfile(ip):
        return send_file(ip, mimetype="image/jpeg")
    # 兼容仅存文件名或相对路径的旧数据
    if ip:
        project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        candidates = [
            ip,
            os.path.join(project_root, ip.lstrip("./")),
            os.path.join(project_root, "snapshots", os.path.basename(ip)),
        ]
        for cand in candidates:
            if cand and os.path.isfile(cand):
                return send_file(cand, mimetype="image/jpeg")
    abort(404)

@app.route('/api/restart', methods=['POST'])
@login_required
def restart_service():
    """重启服务"""
    try:
        # 获取项目根目录
        project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        
        # 使用项目脚本重启，保留 start.sh 中的环境变量设置
        restart_script = f'''#!/bin/bash
cd {project_root}
./stop.sh
sleep 2
./start.sh
'''
        
        script_path = '/tmp/restart_visionai.sh'
        with open(script_path, 'w') as f:
            f.write(restart_script)
        
        os.chmod(script_path, 0o755)
        
        # 使用nohup在后台运行重启脚本
        subprocess.Popen(['nohup', '/bin/bash', script_path], 
                        stdout=open('/dev/null', 'w'), 
                        stderr=open('/dev/null', 'w'))
        
        # 返回成功响应
        return jsonify({'success': True, 'message': '服务重启中...'})
        
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})

@app.route('/logout')
@login_required
def logout():
    """退出登录"""
    session.pop('logged_in', None)
    return redirect(url_for('login'))


@app.route('/face-library')
@login_required
def face_library_page():
    """人脸库管理页"""
    return render_template('face_library.html')


@app.route('/api/face-library', methods=['GET'])
@login_required
def api_face_library_list():
    from visionai.core import face_engine, face_library

    return jsonify(
        {
            "persons": face_library.list_persons(),
            "count": face_library.person_count(),
            "engine_ready": face_engine.is_available(),
        }
    )


@app.route('/api/face-library', methods=['POST'])
@login_required
def api_face_library_enroll():
    import cv2
    import numpy as np
    from visionai.core import face_library

    name = (request.form.get("name") or "").strip()
    department = (request.form.get("department") or "").strip()
    remark = (request.form.get("remark") or "").strip()
    if not name:
        return jsonify({"success": False, "message": "请填写姓名"}), 400
    photo = request.files.get("photo")
    if not photo or not photo.filename:
        return jsonify({"success": False, "message": "请上传照片"}), 400

    buf = np.frombuffer(photo.read(), dtype=np.uint8)
    img = cv2.imdecode(buf, cv2.IMREAD_COLOR)
    if img is None:
        return jsonify({"success": False, "message": "图片格式无效"}), 400
    try:
        result = face_library.enroll_person(
            img, name=name, department=department, remark=remark
        )
        return jsonify({"success": True, **result})
    except ValueError as ex:
        return jsonify({"success": False, "message": str(ex)}), 400
    except Exception as ex:  # noqa: BLE001
        return jsonify({"success": False, "message": str(ex)}), 500


@app.route('/api/face-library/<person_id>', methods=['GET'])
@login_required
def api_face_library_get(person_id):
    from visionai.core import face_library

    person = face_library.get_person(person_id)
    if not person:
        return jsonify({"success": False, "message": "人员不存在"}), 404
    return jsonify({"success": True, "person": person})


@app.route('/api/face-library/<person_id>', methods=['PUT'])
@login_required
def api_face_library_update(person_id):
    from visionai.core import face_library

    data = request.get_json(silent=True) or {}
    ok = face_library.update_person(
        person_id,
        name=data.get("name"),
        department=data.get("department"),
        remark=data.get("remark"),
    )
    if not ok:
        return jsonify({"success": False, "message": "人员不存在"}), 404
    return jsonify({"success": True, "message": "更新成功"})


@app.route('/api/face-library/<person_id>', methods=['DELETE'])
@login_required
def api_face_library_delete(person_id):
    from visionai.core import face_library

    if not face_library.delete_person(person_id):
        return jsonify({"success": False, "message": "人员不存在"}), 404
    return jsonify({"success": True, "message": "删除成功"})


@app.route('/api/face-library/<person_id>/photo')
@login_required
def api_face_library_photo(person_id):
    from flask import Response
    from visionai.core import face_library

    data = face_library.get_photo_bytes(person_id)
    if not data:
        abort(404)
    return Response(data, mimetype="image/jpeg")


@app.route('/api/face-library/reload', methods=['POST'])
@login_required
def api_face_library_reload():
    from visionai.core import face_library

    face_library.reload_index()
    return jsonify(
        {
            "success": True,
            "count": face_library.person_count(),
            "embeddings": face_library.embedding_count(),
        }
    )


@app.route('/plate-library')
@login_required
def plate_library_page():
    """车牌库管理页"""
    return render_template('plate_library.html')


@app.route('/api/plate-library', methods=['GET'])
@login_required
def api_plate_library_list():
    from visionai.core import plate_library, plate_ocr

    return jsonify(
        {
            "plates": plate_library.list_plates(),
            "count": plate_library.plate_count(),
            "ocr_ready": plate_ocr.is_available(),
        }
    )


@app.route('/api/plate-library', methods=['POST'])
@login_required
def api_plate_library_add():
    from visionai.core import plate_library

    data = request.get_json(silent=True) or {}
    plate_no = (data.get("plate_no") or request.form.get("plate_no") or "").strip()
    name = (data.get("name") or request.form.get("name") or "").strip()
    note = (data.get("note") or request.form.get("note") or "").strip()
    result = plate_library.add_plate(plate_no, name=name, note=note)
    if not result.get("success"):
        return jsonify(result), 400
    return jsonify(result)


@app.route('/api/plate-library/<plate_no>', methods=['GET'])
@login_required
def api_plate_library_get(plate_no):
    from visionai.core import plate_library

    plate = plate_library.get_plate(plate_no)
    if not plate:
        return jsonify({"success": False, "message": "车牌不存在"}), 404
    return jsonify({"success": True, "plate": plate})


@app.route('/api/plate-library/<plate_no>', methods=['PUT'])
@login_required
def api_plate_library_update(plate_no):
    from visionai.core import plate_library

    data = request.get_json(silent=True) or {}
    ok = plate_library.update_plate(
        plate_no,
        name=data.get("name"),
        note=data.get("note"),
    )
    if not ok:
        return jsonify({"success": False, "message": "车牌不存在"}), 404
    return jsonify({"success": True, "message": "更新成功"})


@app.route('/api/plate-library/<plate_no>', methods=['DELETE'])
@login_required
def api_plate_library_delete(plate_no):
    from visionai.core import plate_library

    if not plate_library.delete_plate(plate_no):
        return jsonify({"success": False, "message": "车牌不存在"}), 404
    return jsonify({"success": True, "message": "删除成功"})


@app.route('/api/plate-library/reload', methods=['POST'])
@login_required
def api_plate_library_reload():
    from visionai.core import plate_library

    plate_library.reload_index()
    return jsonify(
        {
            "success": True,
            "count": plate_library.plate_count(),
        }
    )


from visionai.web.training_routes import init_training_lab  # noqa: E402

init_training_lab(app)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=False)