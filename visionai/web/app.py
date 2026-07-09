"""JXVisionAI Web管理界面"""
import os
import sys
import json
import subprocess
import functools
import time
from datetime import datetime
from urllib.parse import urlparse

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
    stream_with_context,
    url_for,
)
from flask_sock import Sock

# 添加项目根目录到Python路径
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from visionai.config.settings import (
    AUTO_REFRESH_INTERVAL,
    PREVIEW_ANNOTATED_POLL_SEC,
    PREVIEW_HLS_ENABLED,
    PREVIEW_WEBRTC_ENABLED,
    PREVIEW_WEBRTC_STUN_URLS,
    PREVIEW_WS_MAX_FPS,
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
from visionai.core.face_recognition_config import normalize_face_recognition_config
from visionai.config.ini_manager import (
    config_meta,
    patch_config_updates,
    read_structured_units,
)
from visionai.core import stream_sync
from visionai.core.preview_cache import get_preview_jpeg, get_preview_jpeg_meta
from visionai.core.preview_hls import (
    ffmpeg_available,
    safe_hls_basename,
    session_dir,
    start_session as hls_start_session,
    stop_session as hls_stop_session,
    touch_session as hls_touch_session,
)

# 导入流状态管理
try:
    from visionai.core.state_manager import stream_status, stream_status_lock
except:
    # 如果导入失败，初始化默认状态
    stream_status = {}
    stream_status_lock = None

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

try:
    from visionai.core import preview_webrtc
except ImportError:
    preview_webrtc = None  # type: ignore


def _webrtc_preview_available() -> bool:
    return bool(
        PREVIEW_WEBRTC_ENABLED
        and preview_webrtc is not None
        and preview_webrtc.is_available()
    )


app = Flask(__name__, template_folder='templates', static_folder='static')
app.secret_key = SECRET
sock = Sock(app)

# 登录验证装饰器
def login_required(f):
    @functools.wraps(f)
    def decorated_function(*args, **kwargs):
        if 'logged_in' not in session or not session['logged_in']:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

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
    """COCO 80 类 + 打电话，供前端展示「系统支持」与配置项。"""
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
        # 添加状态信息
        if stream_status_lock:
            with stream_status_lock:
                nm = (stream.get("name") or "").strip()
                stream_copy['status'] = stream_status.get(nm, "离线")
        else:
            stream_copy['status'] = '未知'
        streams_with_status.append(stream_copy)
    return jsonify(streams_with_status)

@app.route('/api/stream-status', methods=['GET'])
@login_required
def get_stream_status():
    """获取视频流状态"""
    if stream_status_lock:
        with stream_status_lock:
            return jsonify(stream_status)
    else:
        # 如果没有状态信息，返回空
        return jsonify({})

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
            return jsonify({'success': False, 'message': '视频流配置不能为空'})
        
        if not redis_manager:
            return jsonify({'success': False, 'message': 'Redis未连接'})
        
        import uuid
        
        # 为每个流生成ID（如果没有的话）
        for stream in streams:
            if not stream.get('id'):
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
        
        # 保存到Redis
        success = redis_manager.save_streams(streams)

        if success:
            if stream_status_lock:
                with stream_status_lock:
                    for stream in streams:
                        n = stream.get("name")
                        if n and n not in stream_status:
                            stream_status[n] = "离线"
            stream_sync.notify_streams_changed()
            return jsonify({'success': True, 'message': '视频流配置保存成功'})
        else:
            return jsonify({'success': False, 'message': '保存视频流配置失败'})
    
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})

@app.route('/api/config', methods=['GET'])
@login_required
def get_config():
    """获取系统配置"""
    return jsonify({
        'auto_refresh_interval': AUTO_REFRESH_INTERVAL,
        'preview': {
            'ffmpeg': ffmpeg_available(),
            'hls_enabled': bool(PREVIEW_HLS_ENABLED and ffmpeg_available()),
            'webrtc_enabled': _webrtc_preview_available(),
        },
        'smtp': {
            'alert_enabled': bool(SMTP_ALERT_ENABLED),
            'host_configured': bool(SMTP_HOST.strip()),
            'from_configured': bool(SMTP_FROM.strip()),
            'ready': smtp_is_configured(),
        },
    })


def _stream_url_by_id(stream_id: str):
    if not stream_id or not redis_manager:
        return None
    for s in redis_manager.get_streams():
        if s.get("id") == stream_id:
            return s.get("url")
    return None


def _mjpeg_frames(rtsp_url: str):
    """从 RTSP/HTTP 拉取视频帧，输出 multipart MJPEG（供浏览器 <img> 显示）。"""
    rtsp_url = normalize_rtsp_url(rtsp_url)
    parsed = urlparse(rtsp_url)
    if parsed.scheme not in ("rtsp", "rtsps", "http", "https"):
        return
    cap = cv2.VideoCapture(rtsp_url)
    try:
        try:
            cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        except Exception:
            pass
        if not cap.isOpened():
            return
        consecutive_fail = 0
        while True:
            ok, frame = cap.read()
            if not ok or frame is None:
                consecutive_fail += 1
                if consecutive_fail > 45:
                    break
                time.sleep(0.05)
                continue
            consecutive_fail = 0
            enc_ok, jpg = cv2.imencode(
                ".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), 72]
            )
            if not enc_ok:
                continue
            yield (
                b"--frame\r\nContent-Type: image/jpeg\r\n\r\n"
                + jpg.tobytes()
                + b"\r\n"
            )
    finally:
        cap.release()


def _mjpeg_frames_annotated(stream_id: str, rtsp_url: str):
    """优先推送检测线程缓存的带框画面；无缓存时回退为原流（与 _mjpeg_frames 行为一致）。"""
    rtsp_url = normalize_rtsp_url(rtsp_url)
    parsed = urlparse(rtsp_url)
    if parsed.scheme not in ("rtsp", "rtsps", "http", "https"):
        return
    cap = None

    def ensure_cap():
        nonlocal cap
        if cap is not None and cap.isOpened():
            return cap
        c = cv2.VideoCapture(rtsp_url)
        try:
            c.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        except Exception:
            pass
        cap = c
        return cap

    consecutive_fail = 0
    try:
        while True:
            blob = get_preview_jpeg(stream_id)
            if blob:
                yield (
                    b"--frame\r\nContent-Type: image/jpeg\r\n\r\n"
                    + blob
                    + b"\r\n"
                )
                time.sleep(PREVIEW_ANNOTATED_POLL_SEC)
                continue
            c = ensure_cap()
            if not c.isOpened():
                time.sleep(0.05)
                continue
            ok, frame = c.read()
            if not ok or frame is None:
                consecutive_fail += 1
                if consecutive_fail > 45:
                    break
                time.sleep(0.05)
                continue
            consecutive_fail = 0
            enc_ok, jpg = cv2.imencode(
                ".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), 72]
            )
            if not enc_ok:
                continue
            yield (
                b"--frame\r\nContent-Type: image/jpeg\r\n\r\n"
                + jpg.tobytes()
                + b"\r\n"
            )
    finally:
        if cap is not None:
            cap.release()


@app.route("/api/preview")
@login_required
def stream_preview_mjpeg():
    """浏览器无法直接播放 RTSP，由本机 OpenCV 拉流并转为 MJPEG 供网页预览。

    默认：实时原画（与检测无关，流畅）。
    annotated=1：推送检测线程缓存的带框 JPEG（与告警截图一致，按检测间隔更新，观感会像「幻灯片」）。
    """
    stream_id = request.args.get("stream_id")
    if not stream_id:
        abort(400)
    url = _stream_url_by_id(stream_id)
    if not url:
        abort(404)
    use_annotated = request.args.get("annotated", "0").lower() in (
        "1",
        "true",
        "yes",
        "on",
    )
    gen = _mjpeg_frames_annotated(stream_id, url) if use_annotated else _mjpeg_frames(url)
    return Response(
        stream_with_context(gen),
        mimetype="multipart/x-mixed-replace; boundary=frame",
        headers={
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "Pragma": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@app.route("/api/preview-webrtc/offer", methods=["POST"])
@login_required
def preview_webrtc_offer():
    """浏览器 WebRTC offer → SDP answer；服务端用 aiortc MediaPlayer 拉 RTSP 推向浏览器。"""
    if not _webrtc_preview_available():
        return jsonify(
            {
                "success": False,
                "message": "WebRTC 预览未启用（preview_webrtc_enabled）或未安装 aiortc",
            }
        ), 503
    payload = request.get_json(silent=True) or {}
    stream_id = (payload.get("stream_id") or "").strip()
    sdp = payload.get("sdp")
    typ = (payload.get("type") or "").strip()
    if not stream_id or not isinstance(sdp, str) or not sdp.strip():
        return jsonify({"success": False, "message": "缺少 stream_id 或 sdp"}), 400
    if typ != "offer":
        return jsonify({"success": False, "message": "type 须为 offer"}), 400
    url = _stream_url_by_id(stream_id)
    if not url:
        return jsonify({"success": False, "message": "无效或未找到的 stream_id"}), 404
    url = normalize_rtsp_url(url)
    parsed = urlparse(url)
    if parsed.scheme not in ("rtsp", "rtsps", "http", "https"):
        return jsonify({"success": False, "message": "不支持的流地址协议"}), 400
    assert preview_webrtc is not None
    result = preview_webrtc.handle_offer(
        url, sdp.strip(), typ, PREVIEW_WEBRTC_STUN_URLS
    )
    code = 200 if result.get("success") else 500
    return jsonify(result), code


@app.route("/api/preview-webrtc/stop", methods=["POST"])
@login_required
def preview_webrtc_stop_api():
    payload = request.get_json(silent=True) or {}
    session_id = (payload.get("session_id") or "").strip()
    if session_id and preview_webrtc is not None:
        preview_webrtc.stop_session(session_id)
    return jsonify({"success": True})


@app.route("/api/preview-hls/start", methods=["POST"])
@login_required
def preview_hls_start():
    """启动一路 FFmpeg→HLS 会话，返回 m3u8 相对路径（需携带登录 Cookie 拉取）。"""
    if not PREVIEW_HLS_ENABLED:
        return jsonify({"success": False, "message": "HLS 预览已在配置中关闭"}), 400
    if not ffmpeg_available():
        return jsonify({"success": False, "message": "服务器未检测到 ffmpeg"}), 503
    payload = request.get_json(silent=True) or {}
    stream_id = (payload.get("stream_id") or "").strip()
    url = _stream_url_by_id(stream_id)
    if not url:
        return jsonify({"success": False, "message": "无效或未找到的 stream_id"}), 404
    url = normalize_rtsp_url(url)
    parsed = urlparse(url)
    if parsed.scheme not in ("rtsp", "rtsps", "http", "https"):
        return jsonify({"success": False, "message": "不支持的流地址协议"}), 400
    sid, playlist = hls_start_session(stream_id, url)
    if not sid or not playlist:
        return jsonify({"success": False, "message": "启动 HLS 转码失败，请查看服务器日志"}), 500
    return jsonify({"success": True, "session_id": sid, "playlist": playlist})


@app.route("/api/preview-hls/stop", methods=["POST"])
@login_required
def preview_hls_stop():
    payload = request.get_json(silent=True) or {}
    session_id = (payload.get("session_id") or "").strip()
    if session_id:
        hls_stop_session(session_id)
    return jsonify({"success": True})


@app.route("/api/preview-hls/data/<session_id>/<path:filename>")
@login_required
def preview_hls_data(session_id: str, filename: str):
    if not safe_hls_basename(filename):
        abort(404)
    base = session_dir(session_id)
    if base is None:
        abort(404)
    try:
        root = base.resolve()
        full = (base / filename).resolve()
    except OSError:
        abort(404)
    if not full.is_relative_to(root) or not full.is_file():
        abort(404)
    hls_touch_session(session_id)
    mimetype = (
        "application/vnd.apple.mpegurl"
        if filename.endswith(".m3u8")
        else "video/MP2T"
    )
    return send_file(full, mimetype=mimetype)


@sock.route("/ws/preview")
def preview_ws(ws):
    """低延迟二进制 JPEG：首条文本消息 JSON `{\"stream_id\":\"...\",\"annotated\":false}`。"""
    if not session.get("logged_in"):
        return
    first = ws.receive()
    if not first:
        return
    if isinstance(first, (bytes, bytearray)):
        first = first.decode("utf-8", errors="replace")
    try:
        spec = json.loads(first)
    except (json.JSONDecodeError, TypeError):
        return
    stream_id = (spec.get("stream_id") or "").strip()
    annotated = bool(spec.get("annotated"))
    url = _stream_url_by_id(stream_id)
    if not url:
        return
    url = normalize_rtsp_url(url)
    parsed = urlparse(url)
    if parsed.scheme not in ("rtsp", "rtsps", "http", "https"):
        return

    min_frame = 1.0 / float(PREVIEW_WS_MAX_FPS)
    next_t = time.monotonic()
    cap = None
    last_ts = None
    try:
        if annotated:
            while True:
                meta = get_preview_jpeg_meta(stream_id)
                if meta:
                    blob, ts = meta
                    if blob and ts != last_ts:
                        ws.send(blob)
                        last_ts = ts
                time.sleep(PREVIEW_ANNOTATED_POLL_SEC)
        else:
            cap = cv2.VideoCapture(url)
            try:
                cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
            except Exception:
                pass
            if not cap.isOpened():
                return
            consecutive_fail = 0
            while True:
                ok, frame = cap.read()
                if not ok or frame is None:
                    consecutive_fail += 1
                    if consecutive_fail > 80:
                        break
                    time.sleep(0.04)
                    continue
                consecutive_fail = 0
                enc_ok, jpg = cv2.imencode(
                    ".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), 72]
                )
                if enc_ok:
                    ws.send(jpg.tobytes())
                now = time.monotonic()
                next_t = max(next_t + min_frame, now)
                sleep_for = next_t - now
                if sleep_for > 0:
                    time.sleep(sleep_for)
    except Exception:
        pass
    finally:
        if cap is not None:
            cap.release()


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
        if not st:
            abort(503)
        try:
            body = st.get_object_bytes(doc["object_key"])
            return Response(body, mimetype="image/jpeg")
        except Exception:
            abort(404)
    ip = doc.get("image_path") or ""
    if ip and os.path.isfile(ip):
        return send_file(ip, mimetype="image/jpeg")
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


from visionai.web.training_routes import init_training_lab  # noqa: E402

init_training_lab(app)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=False)