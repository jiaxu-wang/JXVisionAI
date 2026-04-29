"""VisionAI Web管理界面"""
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

# 添加项目根目录到Python路径
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from visionai.config.settings import AUTO_REFRESH_INTERVAL, SECRET
from visionai.utils.rtsp_url import normalize_rtsp_url
from visionai.config.detection_catalog import catalog_items_for_api, normalize_detections
from visionai.core import stream_sync
from visionai.core.preview_cache import get_preview_jpeg

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

app = Flask(__name__, template_folder='templates', static_folder='static')
app.secret_key = SECRET

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
        'auto_refresh_interval': AUTO_REFRESH_INTERVAL
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
                time.sleep(0.12)
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
        
        # 创建重启脚本，先停止所有旧进程再启动新进程
        restart_script = f'''#!/bin/bash
# 停止所有VisionAI进程
pkill -f "python3 -m visionai"
sleep 1

# 启动新服务
cd {project_root}
source env/bin/activate
nohup python3 -m visionai > /dev/null 2>&1 &
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

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=False)