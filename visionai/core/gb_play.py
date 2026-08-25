"""国标已接入分析的流：检测开启时自动 Invite 并解析真实 RTP 流名。"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional, Tuple

from visionai.config.stream_access import ACCESS_GB28181, normalize_access_method
from visionai.core import gb28181_store as store

logger = logging.getLogger(__name__)


def gb_ids_from_stream(stream_info: Optional[Dict[str, Any]]) -> Tuple[str, str]:
    stream_info = stream_info or {}
    gb = stream_info.get("gb28181") if isinstance(stream_info.get("gb28181"), dict) else {}
    device_id = str(gb.get("device_id") or gb.get("sip_user") or "").strip()
    channel_id = str(gb.get("channel_id") or "").strip()
    return device_id, channel_id


def is_gb_stream(stream_info: Optional[Dict[str, Any]]) -> bool:
    access = normalize_access_method(
        (stream_info or {}).get("access_method"), stream=stream_info
    )
    return access == ACCESS_GB28181


def current_gb_rtp_name(device_id: str, channel_id: str, *, live_only: bool = True) -> str:
    try:
        from visionai.core.zlm_client import get_zlm_client

        zlm = get_zlm_client()
    except Exception:  # noqa: BLE001
        zlm = None
    if not zlm:
        return ""
    names = store.rtp_name_candidates(device_id, channel_id)
    if live_only:
        return zlm.rtp_live_name(*names)
    return zlm.rtp_online_name(*names)


def persist_gb_play(stream_info: Dict[str, Any], url: str, zlm_stream: str) -> None:
    sid = str((stream_info or {}).get("id") or "").strip()
    if not sid or not url:
        return
    try:
        from visionai.core.redis_manager import redis_manager

        if not redis_manager:
            return
        row = None
        for s in redis_manager.get_streams() or []:
            if str(s.get("id") or "") == sid:
                row = dict(s)
                break
        if not row:
            return
        row["url"] = url
        gb = dict(row.get("gb28181") or {}) if isinstance(row.get("gb28181"), dict) else {}
        if zlm_stream:
            gb["zlm_stream"] = zlm_stream
        row["gb28181"] = gb
        redis_manager.save_stream(row)
    except Exception as e:  # noqa: BLE001
        logger.debug("persist gb play url failed: %s", e)


def ensure_gb_play(stream_info: Dict[str, Any], *, force: bool = False) -> Dict[str, Any]:
    """已接入分析的国标流：仅当 RTP 正在推流才复用，否则清僵尸源再 Invite。"""
    device_id, channel_id = gb_ids_from_stream(stream_info)
    if not device_id or not channel_id:
        return {"ok": False, "message": "缺少国标设备或通道"}
    if not force:
        got = current_gb_rtp_name(device_id, channel_id, live_only=True)
        if got:
            url = store.rtp_pull_url(got)
            logger.info("GB play reuse live rtp/%s url=%s", got, url)
            persist_gb_play(stream_info, url, got)
            return {"ok": True, "stream": got, "url": url, "reused": True}
    try:
        from visionai.core.sip import cmd as sip_cmd

        rid = sip_cmd.enqueue_cmd(
            "invite",
            device_id=device_id,
            channel_id=channel_id,
            force=True,
        )
        result = sip_cmd.wait_result(rid, timeout_sec=28.0)
    except Exception as ex:  # noqa: BLE001
        return {"ok": False, "message": str(ex)}
    if not result.get("ok"):
        return result
    play = str(result.get("stream") or "").strip()
    if not play:
        play = current_gb_rtp_name(device_id, channel_id, live_only=True)
    if not play:
        play = store.rtp_stream_id(device_id, channel_id)
    url = store.rtp_pull_url(play)
    live = current_gb_rtp_name(device_id, channel_id, live_only=True)
    if result.get("media_online") is False and not live:
        return {
            "ok": False,
            "message": result.get("message") or "INVITE 已发送，媒体尚未上线",
            "stream": play,
            "url": url,
        }
    if live:
        play = live
        url = store.rtp_pull_url(play)
    persist_gb_play(stream_info, url, play)
    return {
        "ok": True,
        "stream": play,
        "url": url,
        "reused": bool(result.get("reused")),
    }


def prepare_gb_stream(stream_info: Dict[str, Any], *, force: bool = False):
    """返回可拉流的 stream_info 副本；失败返回 (None, err)。"""
    info = dict(stream_info or {})
    if not is_gb_stream(info):
        return info, None
    play = ensure_gb_play(info, force=force)
    if not play.get("ok"):
        return None, str(play.get("message") or "国标点播失败")
    info["url"] = play.get("url") or info.get("url")
    gb = dict(info.get("gb28181") or {}) if isinstance(info.get("gb28181"), dict) else {}
    if play.get("stream"):
        gb["zlm_stream"] = play["stream"]
        info["gb28181"] = gb
    return info, None
