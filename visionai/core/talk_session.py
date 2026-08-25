"""浏览器对讲会话管理：按 stream_id 维护 RTSP backchannel 上行。"""

from __future__ import annotations

import logging
import threading
import time
import uuid
from typing import Any, Dict, Optional
from urllib.parse import unquote, urlparse

from visionai.core.rtsp_backchannel import TalkSession, open_backchannel_session, probe_rtsp_backchannel

logger = logging.getLogger(__name__)

_lock = threading.Lock()
_sessions: Dict[str, TalkSession] = {}  # session_id -> session
_by_stream: Dict[str, str] = {}  # stream_id -> session_id
SESSION_TTL_SEC = 300.0


def _rtsp_from_stream(stream: Dict[str, Any]) -> str:
    return (stream.get("url") or "").strip()


def probe_stream_talk(stream: Dict[str, Any]) -> Dict[str, Any]:
    """对已保存流的 RTSP URL 做 backchannel 探测。"""
    url = _rtsp_from_stream(stream)
    if not url.lower().startswith(("rtsp://", "rtsps://")):
        return {
            "ok": False,
            "talk_supported": False,
            "error": "流无有效 RTSP URL",
        }
    result = probe_rtsp_backchannel(url)
    out = result.as_dict()
    # 附带脱敏 host 便于 UI
    try:
        u = urlparse(url)
        out["rtsp_host"] = u.hostname or ""
        out["rtsp_has_auth"] = bool(u.username)
    except Exception:  # noqa: BLE001
        pass
    return out


def start_talk(stream: Dict[str, Any]) -> Dict[str, Any]:
    stream_id = str(stream.get("id") or "").strip()
    if not stream_id:
        return {"success": False, "message": "缺少 stream_id"}
    url = _rtsp_from_stream(stream)
    if not url.lower().startswith(("rtsp://", "rtsps://")):
        return {"success": False, "message": "流无有效 RTSP URL"}

    # 先探测
    probe = probe_rtsp_backchannel(url)
    if not probe.talk_supported:
        return {
            "success": False,
            "message": probe.detail or probe.error or "设备不支持 ONVIF RTSP Audio Backchannel",
            "probe": probe.as_dict(),
        }

    with _lock:
        old = _by_stream.get(stream_id)
        if old and old in _sessions:
            try:
                _sessions[old].close()
            except Exception:  # noqa: BLE001
                pass
            _sessions.pop(old, None)
            _by_stream.pop(stream_id, None)

    sid = uuid.uuid4().hex[:16]
    try:
        sess = open_backchannel_session(url, session_id=sid, stream_id=stream_id)
    except Exception as e:  # noqa: BLE001
        logger.warning("open talk session failed stream=%s: %s", stream_id, e)
        return {
            "success": False,
            "message": f"建立对讲会话失败: {e}",
            "probe": probe.as_dict(),
        }

    with _lock:
        _sessions[sid] = sess
        _by_stream[stream_id] = sid

    return {
        "success": True,
        "session_id": sid,
        "stream_id": stream_id,
        "codec": sess.codec,
        "payload_type": sess.payload_type,
        "sample_rate": sess.sample_rate,
        "detail": sess.detail,
        "probe": probe.as_dict(),
        "message": "对讲已开始，请对着麦克风说话",
    }


def stop_talk(*, session_id: str = "", stream_id: str = "") -> Dict[str, Any]:
    with _lock:
        sid = (session_id or "").strip()
        if not sid and stream_id:
            sid = _by_stream.get(str(stream_id).strip(), "")
        sess = _sessions.pop(sid, None) if sid else None
        if sess:
            _by_stream.pop(sess.stream_id, None)
    if not sess:
        return {"success": True, "message": "无活动对讲会话"}
    try:
        sess.close()
    except Exception as e:  # noqa: BLE001
        return {"success": False, "message": str(e)}
    return {"success": True, "message": "对讲已结束", "session_id": sid}


def push_audio(session_id: str, payload: bytes) -> Dict[str, Any]:
    sid = (session_id or "").strip()
    with _lock:
        sess = _sessions.get(sid)
    if not sess:
        return {"success": False, "message": "会话不存在或已结束"}
    if time.time() - sess.created_at > SESSION_TTL_SEC:
        stop_talk(session_id=sid)
        return {"success": False, "message": "会话超时，请重新开始对讲"}
    try:
        n = sess.send_g711(payload)
        return {"success": True, "bytes": n}
    except Exception as e:  # noqa: BLE001
        logger.warning("talk push failed: %s", e)
        return {"success": False, "message": str(e)}


def cleanup_stale() -> int:
    now = time.time()
    stale: list[str] = []
    with _lock:
        for sid, sess in _sessions.items():
            if now - sess.created_at > SESSION_TTL_SEC:
                stale.append(sid)
    n = 0
    for sid in stale:
        stop_talk(session_id=sid)
        n += 1
    return n


def credentials_hint_from_url(url: str) -> str:
    try:
        u = urlparse(url or "")
        if u.username:
            return f"{unquote(u.username)}@{(u.hostname or '')}"
    except Exception:  # noqa: BLE001
        pass
    return ""
