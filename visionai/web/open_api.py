"""机对机开放 API：X-Api-Key，失败返回 401 JSON，不 redirect 登录页。"""

from __future__ import annotations

import functools
from typing import Any, Dict, Optional

from flask import Blueprint, Flask, jsonify, request

from visionai.config.stream_access import (
    ACCESS_GB28181,
    normalize_access_method,
    stream_should_analyze,
)
from visionai.utils.embed_token import (
    EMBED_TOKEN_TTL_SEC,
    build_embed_url,
    issue_embed_token,
)
from visionai.utils.open_api_auth import (
    api_key_matches,
    configured_open_api_key,
    request_api_key,
    verify_alert_image_token,
)
from visionai.web.alert_media import detection_image_response

open_api_bp = Blueprint("open_api", __name__, url_prefix="/api/open/v1")


def _unauthorized(message: str = "unauthorized"):
    return jsonify({"success": False, "message": message}), 401


def open_api_key_required(f):
    @functools.wraps(f)
    def decorated(*args, **kwargs):
        if not configured_open_api_key():
            return _unauthorized("open api not configured")
        if not api_key_matches(request_api_key()):
            return _unauthorized("invalid api key")
        return f(*args, **kwargs)

    return decorated


def _stream_by_id(stream_id: str) -> Optional[Dict[str, Any]]:
    from visionai.core.redis_manager import redis_manager

    sid = (stream_id or "").strip()
    if not sid or not redis_manager:
        return None
    for s in redis_manager.get_streams() or []:
        if str(s.get("id") or "").strip() == sid:
            return s
    return None


def _status_label(stream: Dict[str, Any]) -> str:
    try:
        from visionai.core.state_manager import STATUS_OFFLINE, get_stream_status
    except Exception:  # noqa: BLE001
        return "offline"
    name = str(stream.get("name") or "").strip()
    if not name:
        return "offline"
    return get_stream_status(name, default=STATUS_OFFLINE) or STATUS_OFFLINE


def _play_for_stream(stream: Dict[str, Any]) -> Dict[str, Any]:
    from visionai.config.settings import ZLM_ENABLED, ZLM_PUBLIC_HOST
    from visionai.core.zlm_client import get_zlm_client, stream_key_for_id

    sid = str(stream.get("id") or "").strip()
    access = normalize_access_method(stream.get("access_method"), stream=stream)
    empty = {
        "zlm_app": "",
        "zlm_stream": "",
        "play_rtsp": "",
        "play_hls": "",
        "online": False,
    }
    if not sid or not ZLM_ENABLED:
        return empty
    zlm = get_zlm_client()
    if not zlm:
        return empty
    if access == ACCESS_GB28181:
        from visionai.core.gb_play import current_gb_rtp_name, gb_ids_from_stream

        did, cid = gb_ids_from_stream(stream)
        gb = stream.get("gb28181") if isinstance(stream.get("gb28181"), dict) else {}
        stored = str(gb.get("zlm_stream") or "").strip()
        got = current_gb_rtp_name(did, cid) if did and cid else ""
        zlm_stream = got or stored
        play = (
            zlm.play_urls(zlm_stream, host=ZLM_PUBLIC_HOST, app="rtp")
            if zlm_stream
            else {}
        )
        return {
            "zlm_app": "rtp",
            "zlm_stream": zlm_stream,
            "play_rtsp": str(play.get("rtsp") or ""),
            "play_hls": str(play.get("hls") or ""),
            "online": bool(got),
        }
    sk = stream_key_for_id(sid)
    play = zlm.play_urls(sk, host=ZLM_PUBLIC_HOST)
    online = False
    try:
        online = bool(zlm.is_online(sk))
    except Exception:  # noqa: BLE001
        online = False
    return {
        "zlm_app": str(getattr(zlm, "app", "") or "jvai"),
        "zlm_stream": sk,
        "play_rtsp": str(play.get("rtsp") or ""),
        "play_hls": str(play.get("hls") or ""),
        "online": online,
    }


def open_stream_payload(stream: Dict[str, Any]) -> Dict[str, Any]:
    from visionai.core.state_manager import STATUS_OFFLINE, STATUS_ONLINE, is_stream_online

    play = _play_for_stream(stream)
    label = _status_label(stream)
    online = bool(play.get("online")) or is_stream_online(label)
    return {
        "id": str(stream.get("id") or "").strip(),
        "name": stream.get("name") or "",
        "status": STATUS_ONLINE if online else STATUS_OFFLINE,
        "status_zh": "在线" if online else "离线",
        "online": online,
        "access_method": normalize_access_method(
            stream.get("access_method"), stream=stream
        ),
        "play_rtsp": play.get("play_rtsp") or "",
        "play_hls": play.get("play_hls") or "",
        "zlm_stream": play.get("zlm_stream") or "",
        "zlm_app": play.get("zlm_app") or "",
    }


@open_api_bp.route("/streams", methods=["GET"])
@open_api_key_required
def open_list_streams():
    from visionai.core.redis_manager import redis_manager

    if not redis_manager:
        return jsonify({"success": False, "message": "Redis未连接", "data": []}), 503
    rows = []
    for s in redis_manager.get_streams() or []:
        if not stream_should_analyze(s):
            continue
        sid = str(s.get("id") or "").strip()
        if not sid:
            continue
        rows.append(open_stream_payload(s))
    return jsonify({"success": True, "data": rows})


@open_api_bp.route("/alerts/<detection_id>/image", methods=["GET"])
def open_alert_image(detection_id):
    if not configured_open_api_key():
        return _unauthorized("open api not configured")
    token = (request.args.get("token") or "").strip()
    key_ok = api_key_matches(request_api_key())
    token_ok = verify_alert_image_token(detection_id, token)
    if not key_ok and not token_ok:
        return _unauthorized("invalid api key")
    resp, status = detection_image_response(detection_id)
    if resp is not None:
        return resp, status
    return jsonify({"success": False, "message": "not found"}), status


@open_api_bp.route("/zlm/ensure-proxy", methods=["POST"])
@open_api_key_required
def open_zlm_ensure_proxy():
    from visionai.config.settings import ZLM_ENABLED, ZLM_PUBLIC_HOST
    from visionai.core.zlm_client import get_zlm_client, stream_key_for_id

    if not ZLM_ENABLED:
        return jsonify({"success": False, "message": "ZLM 未启用"}), 400
    body = request.get_json(silent=True) or {}
    stream_id = str(body.get("stream_id") or "").strip()
    if not stream_id:
        return jsonify({"success": False, "message": "缺少 stream_id"}), 400
    stream = _stream_by_id(stream_id)
    if not stream:
        return jsonify({"success": False, "message": "未找到流"}), 404
    zlm = get_zlm_client()
    if not zlm or not zlm.alive():
        return jsonify({"success": False, "message": "ZLM 不可用或鉴权失败"}), 503

    access = normalize_access_method(stream.get("access_method"), stream=stream)
    if access == ACCESS_GB28181:
        play_meta = _play_for_stream(stream)
        play = {}
        if play_meta.get("zlm_stream"):
            play = zlm.play_urls(
                play_meta["zlm_stream"], host=ZLM_PUBLIC_HOST, app="rtp"
            )
        return jsonify(
            {
                "success": True,
                "online": bool(play_meta.get("online")),
                "stream": play_meta.get("zlm_stream") or "",
                "app": "rtp",
                "play": play,
                "play_rtsp": str(play.get("rtsp") or play_meta.get("play_rtsp") or ""),
                "play_hls": str(play.get("hls") or play_meta.get("play_hls") or ""),
            }
        )

    source_url = str(stream.get("url") or "").strip()
    if not source_url:
        return jsonify({"success": False, "message": "未找到流或 RTSP URL"}), 404
    proxied = zlm.ensure_proxy(stream_id, source_url)
    if not proxied.get("success"):
        return jsonify(
            {"success": False, "message": proxied.get("message") or "代理失败"}
        ), 502
    sk = str(proxied.get("stream") or stream_key_for_id(stream_id))
    play = zlm.play_urls(sk, host=ZLM_PUBLIC_HOST)
    return jsonify(
        {
            "success": True,
            "online": bool(proxied.get("online")),
            "stream": sk,
            "app": str(getattr(zlm, "app", "") or "jvai"),
            "local_rtsp": proxied.get("local_rtsp"),
            "play": play,
            "play_rtsp": str(play.get("rtsp") or ""),
            "play_hls": str(play.get("hls") or ""),
        }
    )


@open_api_bp.route("/embed-token", methods=["POST"])
@open_api_key_required
def open_embed_token():
    token = issue_embed_token()
    if not token:
        return jsonify({"success": False, "message": "cannot issue token"}), 503
    embed_url = build_embed_url(token, request.host_url)
    if not embed_url:
        return jsonify({"success": False, "message": "public_base_url 未配置"}), 400
    return jsonify(
        {
            "success": True,
            "token": token,
            "embed_url": embed_url,
            "expires_in": EMBED_TOKEN_TTL_SEC,
        }
    )


def init_open_api(app: Flask) -> None:
    app.register_blueprint(open_api_bp)
