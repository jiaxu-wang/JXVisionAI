"""ONVIF 发现与探测：WS-Discovery + Device/Media → RTSP URI。

检测拉流仍走 RTSP；本模块只负责发现设备、鉴权探测、列举 Profile 与 StreamUri。
"""

from __future__ import annotations

import logging
import re
import time
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import quote, urlparse, urlunparse

logger = logging.getLogger(__name__)

# 简单进程内限流：discover / probe
_last_discover_ts = 0.0
_last_probe_ts = 0.0
DISCOVER_MIN_INTERVAL_SEC = 10.0
PROBE_MIN_INTERVAL_SEC = 1.0


def _wsdl_dir() -> str:
    try:
        import onvif

        # onvif-zeep 将 wsdl 装到 site-packages/wsdl
        import os

        base = os.path.dirname(os.path.dirname(onvif.__file__))
        path = os.path.join(base, "wsdl")
        if os.path.isdir(path):
            return path
    except Exception:  # noqa: BLE001
        pass
    return ""


def check_discover_rate_limit() -> Optional[str]:
    global _last_discover_ts
    now = time.monotonic()
    wait = DISCOVER_MIN_INTERVAL_SEC - (now - _last_discover_ts)
    if wait > 0:
        return f"扫描过于频繁，请 {int(wait) + 1} 秒后再试"
    _last_discover_ts = now
    return None


def check_probe_rate_limit() -> Optional[str]:
    global _last_probe_ts
    now = time.monotonic()
    wait = PROBE_MIN_INTERVAL_SEC - (now - _last_probe_ts)
    if wait > 0:
        return f"探测过于频繁，请稍后再试"
    _last_probe_ts = now
    return None


def _parse_xaddr(xaddr: str) -> Tuple[str, int, str]:
    """从 ONVIF XAddrs 解析 host, port, path。"""
    u = (xaddr or "").strip()
    if not u:
        return "", 80, ""
    # 部分设备返回多个空格分隔的地址，取第一个
    u = u.split()[0]
    p = urlparse(u)
    host = p.hostname or ""
    port = p.port or (443 if p.scheme == "https" else 80)
    path = p.path or ""
    return host, int(port), path


def _scope_name(scopes: List[Any]) -> str:
    for s in scopes or []:
        try:
            val = getattr(s, "getValue", None)
            text = val() if callable(val) else str(s)
        except Exception:  # noqa: BLE001
            text = str(s)
        text = text.strip()
        # onvif://www.onvif.org/name/CameraName
        m = re.search(r"/name/([^/\s]+)", text, re.I)
        if m:
            from urllib.parse import unquote

            return unquote(m.group(1).replace("%20", " "))
    return ""


def discover_devices(timeout_sec: float = 5.0) -> List[Dict[str, Any]]:
    """局域网 WS-Discovery Probe，返回去重后的设备列表。"""
    timeout_sec = max(1.0, min(float(timeout_sec or 5.0), 20.0))
    try:
        from wsdiscovery.discovery import ThreadedWSDiscovery
    except ImportError as e:
        raise RuntimeError("未安装 WSDiscovery，请 pip install WSDiscovery") from e

    wsd = ThreadedWSDiscovery()
    devices: List[Dict[str, Any]] = []
    seen: set = set()
    try:
        wsd.start()
        services = wsd.searchServices(timeout=timeout_sec)
        for svc in services:
            try:
                xaddrs = list(svc.getXAddrs() or [])
            except Exception:  # noqa: BLE001
                xaddrs = []
            if not xaddrs:
                continue
            scopes = []
            try:
                scopes = list(svc.getScopes() or [])
            except Exception:  # noqa: BLE001
                scopes = []
            name = _scope_name(scopes)
            for xa in xaddrs:
                host, port, path = _parse_xaddr(str(xa))
                if not host:
                    continue
                key = f"{host}:{port}"
                if key in seen:
                    continue
                seen.add(key)
                scopes_out = []
                for s in scopes:
                    try:
                        gv = getattr(s, "getValue", None)
                        scopes_out.append(str(gv() if callable(gv) else s))
                    except Exception:  # noqa: BLE001
                        scopes_out.append(str(s))
                devices.append(
                    {
                        "endpoint": str(xa).split()[0],
                        "host": host,
                        "port": port,
                        "path": path,
                        "name": name or host,
                        "scopes": scopes_out,
                    }
                )
    finally:
        try:
            wsd.stop()
        except Exception:  # noqa: BLE001
            pass

    devices.sort(key=lambda d: (d.get("host") or "", d.get("port") or 0))
    return devices


def _make_camera(
    host: str,
    port: int,
    username: str,
    password: str,
    *,
    encrypt: bool = True,
    adjust_time: bool = True,
    use_digest: bool = False,
):
    try:
        from onvif import ONVIFCamera
        from requests import Session
        from requests.auth import HTTPDigestAuth
        from zeep.transports import Transport
    except ImportError as e:
        raise RuntimeError(
            "未安装 onvif-zeep / requests / zeep，请 pip install onvif-zeep WSDiscovery"
        ) from e

    wsdl = _wsdl_dir()
    # 关键：勿走 HTTP(S)_PROXY。局域网摄像机被代理劫持时，常表现为「鉴权失败」。
    session = Session()
    session.trust_env = False
    if use_digest and username:
        session.auth = HTTPDigestAuth(username or "", password or "")
    transport = Transport(session=session, operation_timeout=12, timeout=12)

    kwargs: Dict[str, Any] = {
        "encrypt": bool(encrypt),
        "adjust_time": bool(adjust_time),
        "transport": transport,
    }
    if wsdl:
        kwargs["wsdl_dir"] = wsdl
    return ONVIFCamera(host, int(port), username or "", password or "", **kwargs)


def _connect_camera(host: str, port: int, username: str, password: str):
    """按多种鉴权策略连接（海康 digest/WSSE + 校时优先）。"""
    strategies = [
        # 海康「集成协议」认证多为 digest/WSSE
        {"use_digest": True, "encrypt": False, "adjust_time": True, "label": "digest"},
        {"use_digest": True, "encrypt": True, "adjust_time": True, "label": "digest+wsse"},
        {"use_digest": False, "encrypt": True, "adjust_time": True, "label": "wsse+time"},
        {"use_digest": False, "encrypt": True, "adjust_time": False, "label": "wsse"},
        {"use_digest": False, "encrypt": False, "adjust_time": True, "label": "plain+time"},
    ]
    errors: List[str] = []
    for st in strategies:
        label = st["label"]
        kwargs = {k: v for k, v in st.items() if k != "label"}
        try:
            cam = _make_camera(host, int(port or 80), username, password, **kwargs)
            # 构造时已 GetCapabilities；再读一次信息确认
            _ = cam.devicemgmt.GetDeviceInformation()
            logger.info("ONVIF connected %s:%s via %s", host, port, label)
            return cam, label
        except Exception as e:  # noqa: BLE001
            msg = str(e) or e.__class__.__name__
            errors.append(f"{label}: {msg}")
            logger.debug("ONVIF strategy %s failed for %s:%s: %s", label, host, port, msg)
    raise RuntimeError(" | ".join(errors[:3]) if errors else "连接失败")


def probe_device(
    host: str,
    port: int = 80,
    username: str = "",
    password: str = "",
) -> Dict[str, Any]:
    """鉴权 + DeviceInformation + Media 能力探测。"""
    host = (host or "").strip()
    if not host:
        return {"ok": False, "status": "failed", "error": "缺少 host"}

    try:
        cam, auth_mode = _connect_camera(host, int(port or 80), username, password)
        dev = cam.devicemgmt
        info = dev.GetDeviceInformation()
        caps = dev.GetCapabilities({"Category": "All"})
        media_xaddr = ""
        try:
            media_xaddr = str(getattr(getattr(caps, "Media", None), "XAddr", "") or "")
        except Exception:  # noqa: BLE001
            media_xaddr = ""

        if not media_xaddr:
            return {
                "ok": False,
                "status": "failed",
                "error": "设备无 Media 能力（非 Profile S 或未开启）",
                "manufacturer": str(getattr(info, "Manufacturer", "") or ""),
                "model": str(getattr(info, "Model", "") or ""),
                "firmware": str(getattr(info, "FirmwareVersion", "") or ""),
            }

        # 至少能拉到一个 RTSP
        profiles = list_profiles(host, int(port or 80), username, password, cam=cam)
        rtsp_ok = any(
            (p.get("rtsp_url") or "").lower().startswith(("rtsp://", "rtsps://"))
            for p in profiles
        )
        if not rtsp_ok:
            return {
                "ok": False,
                "status": "failed",
                "error": "无法获取 RTSP StreamUri",
                "manufacturer": str(getattr(info, "Manufacturer", "") or ""),
                "model": str(getattr(info, "Model", "") or ""),
                "firmware": str(getattr(info, "FirmwareVersion", "") or ""),
                "profile_count": len(profiles),
            }

        talk = _probe_talk_from_onvif(cam, caps, profiles)

        return {
            "ok": True,
            "status": "normal",
            "manufacturer": str(getattr(info, "Manufacturer", "") or ""),
            "model": str(getattr(info, "Model", "") or ""),
            "firmware": str(getattr(info, "FirmwareVersion", "") or ""),
            "serial": str(getattr(info, "SerialNumber", "") or ""),
            "profile_count": len(profiles),
            "host": host,
            "port": int(port or 80),
            "auth_mode": auth_mode,
            **talk,
        }
    except Exception as e:  # noqa: BLE001
        msg = str(e) or e.__class__.__name__
        low = msg.lower()
        if "auth" in low or "not authorized" in low or "401" in low or "unauthorized" in low:
            err = (
                "鉴权失败。请确认：①用集成协议里的 ONVIF 用户；②密码无误；"
                "③若本机开了 HTTP 代理，已自动绕过（请重启服务后再试）；"
                f"④原始错误: {msg[:180]}"
            )
        elif "timed out" in low or "timeout" in low or "connect" in low:
            err = f"连接失败，请检查 IP/端口与网络: {msg[:120]}"
        else:
            err = f"探测失败: {msg[:240]}"
        logger.warning("ONVIF probe %s:%s failed: %s", host, port, msg)
        return {"ok": False, "status": "failed", "error": err, "host": host, "port": int(port or 80)}


def _attr(obj: Any, *names: str, default: Any = None) -> Any:
    for n in names:
        if obj is None:
            break
        if hasattr(obj, n):
            v = getattr(obj, n)
            if v is not None:
                return v
    return default


def _probe_talk_from_onvif(cam: Any, caps: Any, profiles: List[Dict[str, Any]]) -> Dict[str, Any]:
    """探测 ONVIF 对讲：DeviceIO/AudioOutputs + RTSP backchannel DESCRIBE（ODM 同款）。"""
    onvif_audio_outputs = 0
    onvif_hints: List[str] = []
    try:
        # GetCapabilities 中是否声明 Audio / DeviceIO
        for name in ("Audio", "Device", "DeviceIO", "Extension"):
            node = getattr(caps, name, None)
            if node is not None:
                onvif_hints.append(name)
        dio = None
        for factory in ("create_deviceio_service", "create_device_io_service"):
            fn = getattr(cam, factory, None)
            if callable(fn):
                try:
                    dio = fn()
                    break
                except Exception:  # noqa: BLE001
                    dio = None
        if dio is not None:
            try:
                outs = dio.GetAudioOutputs()
                if outs is None:
                    onvif_audio_outputs = 0
                elif isinstance(outs, (list, tuple)):
                    onvif_audio_outputs = len(outs)
                else:
                    onvif_audio_outputs = 1
            except Exception as e:  # noqa: BLE001
                onvif_hints.append(f"GetAudioOutputs失败:{str(e)[:60]}")
    except Exception as e:  # noqa: BLE001
        onvif_hints.append(f"DeviceIO:{str(e)[:60]}")

    # 关键：RTSP Require backchannel（与 ODM 一致）
    rtsp_url = ""
    for p in profiles or []:
        u = (p.get("rtsp_url") or "").strip()
        if u.lower().startswith(("rtsp://", "rtsps://")):
            rtsp_url = u
            break
    bc: Dict[str, Any] = {}
    if rtsp_url:
        try:
            from visionai.core.rtsp_backchannel import probe_rtsp_backchannel

            bc = probe_rtsp_backchannel(rtsp_url).as_dict()
        except Exception as e:  # noqa: BLE001
            bc = {"ok": False, "talk_supported": False, "error": str(e)[:160]}

    talk_supported = bool(bc.get("talk_supported"))
    # 仅有 AudioOutputs 而无 backchannel 时标记为「可能支持」，仍以 RTSP 实测为准
    talk_possible = talk_supported or onvif_audio_outputs > 0
    protocol = (bc.get("talk_protocol") or "") if talk_supported else ""
    detail_parts = []
    if bc.get("detail"):
        detail_parts.append(str(bc.get("detail")))
    if bc.get("error"):
        detail_parts.append(str(bc.get("error")))
    if onvif_audio_outputs:
        detail_parts.append(f"ONVIF AudioOutputs={onvif_audio_outputs}")
    if onvif_hints:
        detail_parts.append("caps=" + ",".join(onvif_hints[:6]))

    return {
        "talk_supported": talk_supported,
        "talk_possible": talk_possible,
        "talk_protocol": protocol or ("rtsp-backchannel" if talk_supported else ""),
        "talk_codec": bc.get("codec") or "",
        "talk_payload_type": int(bc.get("payload_type") or 0),
        "talk_sample_rate": int(bc.get("sample_rate") or 8000),
        "talk_detail": "；".join([p for p in detail_parts if p])[:400],
        "talk_sdp": bc.get("sdp_summary") or "",
        "onvif_audio_outputs": onvif_audio_outputs,
    }


def list_profiles(
    host: str,
    port: int = 80,
    username: str = "",
    password: str = "",
    cam: Any = None,
) -> List[Dict[str, Any]]:
    """列举 Media Profile 及对应 RTSP URI。"""
    host = (host or "").strip()
    if not host:
        return []

    if cam is None:
        cam, _ = _connect_camera(host, int(port or 80), username, password)

    media = cam.create_media_service()
    profiles = media.GetProfiles()
    out: List[Dict[str, Any]] = []

    for prof in profiles or []:
        token = str(_attr(prof, "token", "Token", default="") or "")
        pname = str(_attr(prof, "Name", "name", default="") or token or "Profile")
        encoding = ""
        width = None
        height = None
        try:
            vec = _attr(prof, "VideoEncoderConfiguration")
            if vec is not None:
                encoding = str(_attr(vec, "Encoding", default="") or "")
                res = _attr(vec, "Resolution")
                if res is not None:
                    width = int(_attr(res, "Width", default=0) or 0) or None
                    height = int(_attr(res, "Height", default=0) or 0) or None
        except Exception:  # noqa: BLE001
            pass

        rtsp_url = ""
        try:
            uri_resp = media.GetStreamUri(
                {
                    "StreamSetup": {
                        "Stream": "RTP-Unicast",
                        "Transport": {"Protocol": "RTSP"},
                    },
                    "ProfileToken": token,
                }
            )
            rtsp_url = str(_attr(uri_resp, "Uri", "URI", default="") or "")
        except Exception as e:  # noqa: BLE001
            logger.debug("GetStreamUri failed for %s: %s", token, e)

        if rtsp_url and username and "://" in rtsp_url:
            rtsp_url = inject_rtsp_auth(rtsp_url, username, password)

        out.append(
            {
                "token": token,
                "name": pname,
                "encoding": encoding,
                "width": width,
                "height": height,
                "rtsp_url": rtsp_url,
            }
        )
    return out


def inject_rtsp_auth(rtsp_url: str, username: str, password: str) -> str:
    """若 URI 无 userinfo，则写入 user:pass（密码中的 @ 编码为 %40）。"""
    u = (rtsp_url or "").strip()
    if not u or not username:
        return u
    p = urlparse(u)
    if p.username:
        return u
    user = quote(username, safe="")
    pw = quote(password or "", safe="")
    netloc = f"{user}:{pw}@{p.hostname}"
    if p.port:
        netloc += f":{p.port}"
    return urlunparse((p.scheme, netloc, p.path, p.params, p.query, p.fragment))


def mask_url_for_log(url: str) -> str:
    """日志脱敏。"""
    u = url or ""
    return re.sub(r"(://[^:/@]+:)[^@/]+@", r"\1***@", u)
