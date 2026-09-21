"""从当前在线分析流截取一帧 BGR，供人脸库手动比对等。"""

from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Optional, Tuple

import cv2
import numpy as np

from visionai.utils.rtsp_url import normalize_rtsp_url

logger = logging.getLogger(__name__)


def _allowed_rtsp(url: str) -> bool:
    u = (url or "").strip().lower()
    return u.startswith("rtsp://") or u.startswith("rtsps://")


def read_rtsp_frame_bgr(url: str, timeout_sec: float = 10.0) -> Optional[np.ndarray]:
    """读取单帧 BGR；失败返回 None。"""
    u = normalize_rtsp_url((url or "").strip())
    if not _allowed_rtsp(u):
        return None
    cap = cv2.VideoCapture(u, cv2.CAP_FFMPEG)
    if not cap.isOpened():
        return None
    if hasattr(cv2, "CAP_PROP_OPEN_TIMEOUT_MSEC"):
        cap.set(cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, int(timeout_sec * 1000))
    t0 = time.monotonic()
    frame = None
    while time.monotonic() - t0 < timeout_sec:
        ok, fr = cap.read()
        if ok and fr is not None and getattr(fr, "size", 0) > 0:
            frame = fr
            break
        time.sleep(0.05)
    cap.release()
    return frame


def _decode_jpeg(data: bytes) -> Optional[np.ndarray]:
    if not data:
        return None
    arr = np.frombuffer(data, dtype=np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if img is None or getattr(img, "size", 0) == 0:
        return None
    return img


def candidate_rtsp_urls(stream: Dict[str, Any]) -> List[str]:
    """按优先序收集可截帧的 RTSP：ZLM 本地回源 → 播放口 → 源地址。"""
    urls: List[str] = []
    seen = set()

    def add(u: str) -> None:
        u = normalize_rtsp_url((u or "").strip())
        if not _allowed_rtsp(u) or u in seen:
            return
        seen.add(u)
        urls.append(u)

    from visionai.config.stream_access import ACCESS_GB28181, normalize_access_method
    from visionai.core.zlm_client import get_zlm_client, stream_key_for_id

    access = normalize_access_method(stream.get("access_method"), stream=stream)
    zlm = get_zlm_client()
    sid = str(stream.get("id") or "").strip()

    if access == ACCESS_GB28181:
        from visionai.core import gb28181_store
        from visionai.core.gb_play import current_gb_rtp_name, gb_ids_from_stream

        did, cid = gb_ids_from_stream(stream)
        gb = stream.get("gb28181") if isinstance(stream.get("gb28181"), dict) else {}
        live = current_gb_rtp_name(did, cid) if did and cid else ""
        stored = str(gb.get("zlm_stream") or "").strip()
        name = live or stored
        if name:
            add(gb28181_store.rtp_pull_url(name))
            if zlm:
                play = zlm.play_urls(name, host="127.0.0.1", app="rtp")
                add(str(play.get("rtsp") or ""))
    elif zlm and sid:
        sk = stream_key_for_id(sid)
        add(zlm.local_rtsp_url(sk))
        play = zlm.play_urls(sk, host="127.0.0.1")
        add(str(play.get("rtsp") or ""))

    add(str(stream.get("url") or ""))
    return urls


def find_stream(stream_id: str) -> Optional[Dict[str, Any]]:
    from visionai.core.redis_manager import redis_manager

    sid = str(stream_id or "").strip()
    if not sid or not redis_manager:
        return None
    for s in redis_manager.get_streams() or []:
        if str(s.get("id") or "").strip() == sid:
            return s
    return None


def stream_is_online(stream: Dict[str, Any]) -> bool:
    try:
        from visionai.core.state_manager import get_stream_status, is_stream_online
    except Exception:  # noqa: BLE001
        return False
    name = str((stream or {}).get("name") or "").strip()
    return is_stream_online(get_stream_status(name, "offline"))


def read_frame_bgr_prefer_snap(url: str, timeout_sec: float = 10.0) -> Optional[np.ndarray]:
    """优先 ZLM getSnap，失败再直连 RTSP 读一帧。"""
    u = normalize_rtsp_url((url or "").strip())
    if not _allowed_rtsp(u):
        return None
    wait = max(3.0, float(timeout_sec))
    try:
        from visionai.core.zlm_client import get_zlm_client

        zlm = get_zlm_client()
    except Exception:  # noqa: BLE001
        zlm = None
    if zlm:
        try:
            snap = zlm.get_snap(u, timeout_sec=min(wait, 8.0))
        except Exception:  # noqa: BLE001
            snap = None
        if snap:
            img = _decode_jpeg(snap)
            if img is not None:
                return img
    return read_rtsp_frame_bgr(u, timeout_sec=wait)


def grab_online_stream_frame(
    stream_id: str, *, timeout_sec: float = 10.0
) -> Tuple[np.ndarray, Dict[str, Any]]:
    """截取指定在线流的一帧。离线或不存在时抛 ValueError。"""
    stream = find_stream(stream_id)
    if not stream:
        raise ValueError("未找到该路视频")
    if not stream_is_online(stream):
        raise ValueError("该路视频当前不在线")

    urls = candidate_rtsp_urls(stream)
    if not urls:
        raise RuntimeError("该路视频没有可用的拉流地址")

    from visionai.core.zlm_client import get_zlm_client

    zlm = get_zlm_client()
    last_err = "无法从该路视频截取画面"
    wait = max(3.0, float(timeout_sec))
    for u in urls:
        if zlm:
            try:
                snap = zlm.get_snap(u, timeout_sec=min(wait, 8.0))
            except Exception as ex:  # noqa: BLE001
                snap = None
                last_err = str(ex)
            if snap:
                img = _decode_jpeg(snap)
                if img is not None:
                    return img, stream
        frame = read_rtsp_frame_bgr(u, timeout_sec=wait)
        if frame is not None:
            return frame, stream
        last_err = "截帧失败"
    logger.warning("stream snap failed id=%s urls=%s", stream_id, urls)
    raise RuntimeError(last_err)
