"""RTSP → WebRTC（aiortc MediaPlayer），管理端低延迟预览。

独立 asyncio 事件循环跑在 daemon 线程中，与 Flask 同步路由通过 run_coroutine_threadsafe 交互。
"""

from __future__ import annotations

import asyncio
import logging
import threading
import uuid
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

_loop: Optional[asyncio.AbstractEventLoop] = None
_loop_lock = threading.Lock()
_loop_started = threading.Event()

# session_id -> (RTCPeerConnection, MediaPlayer)
_sessions: Dict[str, Tuple[Any, Any]] = {}


def _lazy_imports():
    from aiortc import (
        RTCConfiguration,
        RTCIceServer,
        RTCPeerConnection,
        RTCSessionDescription,
    )
    from aiortc.contrib.media import MediaPlayer

    return RTCConfiguration, RTCIceServer, RTCPeerConnection, RTCSessionDescription, MediaPlayer


def is_available() -> bool:
    try:
        _lazy_imports()
        return True
    except ImportError as e:
        logger.debug("WebRTC 预览不可用（未安装 aiortc 等依赖）: %s", e)
        return False


def _ensure_loop() -> asyncio.AbstractEventLoop:
    global _loop
    with _loop_lock:
        if _loop is not None:
            return _loop

        def _run() -> None:
            global _loop
            _loop = asyncio.new_event_loop()
            asyncio.set_event_loop(_loop)
            _loop_started.set()
            _loop.run_forever()

        th = threading.Thread(target=_run, daemon=True, name="visionai-webrtc")
        th.start()
        if not _loop_started.wait(timeout=15.0):
            raise RuntimeError("WebRTC 事件循环启动超时")
        assert _loop is not None
        return _loop


def _ice_servers_from_csv(urls_csv: str, RTCIceServer: Any) -> List[Any]:
    out: list = []
    for part in (urls_csv or "").split(","):
        u = part.strip()
        if u:
            out.append(RTCIceServer(urls=u))
    if not out:
        out.append(RTCIceServer(urls="stun:stun.l.google.com:19302"))
    return out


async def _close_session(session_id: str) -> None:
    ent = _sessions.pop(session_id, None)
    if not ent:
        return
    pc, player = ent
    try:
        await pc.close()
    except Exception as ex:
        logger.debug("WebRTC pc.close: %s", ex)
    try:
        if player is not None:
            v = getattr(player, "video", None)
            if v is not None:
                v.stop()
            a = getattr(player, "audio", None)
            if a is not None:
                a.stop()
    except Exception as ex:
        logger.debug("WebRTC player stop: %s", ex)


async def _negotiate_async(
    rtsp_url: str,
    offer_sdp: str,
    offer_type: str,
    stun_urls_csv: str,
) -> Tuple[str, str, str]:
    (
        RTCConfiguration,
        RTCIceServer,
        RTCPeerConnection,
        RTCSessionDescription,
        MediaPlayer,
    ) = _lazy_imports()

    offer = RTCSessionDescription(sdp=offer_sdp, type=offer_type)
    ice_servers = _ice_servers_from_csv(stun_urls_csv, RTCIceServer)
    pc = RTCPeerConnection(RTCConfiguration(iceServers=ice_servers))
    player: Any = None
    loop_ref = asyncio.get_event_loop()
    try:
        player = MediaPlayer(
            rtsp_url,
            options={
                "rtsp_transport": "tcp",
                "fflags": "nobuffer",
                "flags": "low_delay",
            },
        )
        if player.video is None:
            raise RuntimeError("无法打开 RTSP 视频轨（请确认地址可播）")
        pc.addTrack(player.video)
        await pc.setRemoteDescription(offer)
        answer = await pc.createAnswer()
        await pc.setLocalDescription(answer)

        deadline = loop_ref.time() + 3.0
        while pc.iceGatheringState != "complete" and loop_ref.time() < deadline:
            await asyncio.sleep(0.05)

        sid = uuid.uuid4().hex[:12]
        _sessions[sid] = (pc, player)
        player = None

        @pc.on("connectionstatechange")
        def _on_cs() -> None:
            try:
                st = pc.connectionState
                if st in ("failed", "closed"):
                    logger.info("WebRTC connectionState=%s session=%s", st, sid)
                    asyncio.run_coroutine_threadsafe(_close_session(sid), loop_ref)
            except Exception as ex:
                logger.warning("WebRTC connectionstatechange: %s", ex)

        assert pc.localDescription is not None
        return sid, pc.localDescription.sdp, pc.localDescription.type
    except Exception:
        try:
            if player is not None:
                v = getattr(player, "video", None)
                if v is not None:
                    v.stop()
                a = getattr(player, "audio", None)
                if a is not None:
                    a.stop()
        except Exception:
            pass
        try:
            await pc.close()
        except Exception:
            pass
        raise


def handle_offer(
    rtsp_url: str,
    offer_sdp: str,
    offer_type: str,
    stun_urls_csv: str,
) -> Dict[str, Any]:
    if not is_available():
        return {"success": False, "message": "未安装 aiortc，请 pip install aiortc"}
    loop = _ensure_loop()

    async def _run() -> Tuple[str, str, str]:
        return await _negotiate_async(rtsp_url, offer_sdp, offer_type, stun_urls_csv)

    fut = asyncio.run_coroutine_threadsafe(_run(), loop)
    try:
        sid, sdp, typ = fut.result(timeout=60.0)
        return {"success": True, "session_id": sid, "sdp": sdp, "type": typ}
    except Exception as e:
        logger.exception("WebRTC offer 失败")
        return {"success": False, "message": str(e)}


def stop_session(session_id: str) -> None:
    if not session_id:
        return
    if _loop is None:
        _sessions.pop(session_id, None)
        return
    fut = asyncio.run_coroutine_threadsafe(_close_session(session_id), _loop)
    try:
        fut.result(timeout=15.0)
    except Exception as ex:
        logger.warning("WebRTC stop_session: %s", ex)
