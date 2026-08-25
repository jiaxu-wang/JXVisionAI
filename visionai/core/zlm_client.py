"""ZLMediaKit REST 客户端：拉流代理与播放地址。"""

from __future__ import annotations

import logging
import re
import time
from typing import Any, Dict, List, Optional, Set
from urllib.parse import quote, urljoin

import requests

logger = logging.getLogger(__name__)

_SAFE_STREAM = re.compile(r"[^a-zA-Z0-9_]+")


def stream_key_for_id(stream_id: str) -> str:
    sid = (stream_id or "").strip() or "unknown"
    return _SAFE_STREAM.sub("_", sid)[:64]


def rewrite_webrtc_sdp_host(sdp: str, host: str, port: int) -> str:
    """把 answer 中的 Docker 内网 IP 换成浏览器可达 host（c= / candidate）。"""
    host = (host or "").strip() or "127.0.0.1"
    port = int(port)
    if not sdp:
        return sdp
    lines = sdp.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    out: list[str] = []
    for line in lines:
        if line.startswith("c=IN IP4 "):
            out.append(f"c=IN IP4 {host}")
            continue
        if line.startswith("o=") and " IN IP4 " in line:
            # o=- 0 0 IN IP4 x.x.x.x
            parts = line.split(" ")
            if len(parts) >= 6 and parts[-2] == "IP4":
                parts[-1] = host
                out.append(" ".join(parts))
                continue
        if line.startswith("a=candidate:"):
            # a=candidate:... udp|tcp priority ip port typ ...
            parts = line.split(" ")
            if len(parts) >= 6:
                # replace IP and port fields (index 4,5 in typical format)
                # candidate:foundation component protocol priority ip port typ ...
                try:
                    parts[4] = host
                    parts[5] = str(port)
                except Exception:  # noqa: BLE001
                    pass
                out.append(" ".join(parts))
                continue
        out.append(line)
    # 保证至少有 udp + tcp host 候选（WSL2 上 UDP 常不通，TCP 更稳）
    joined = "\n".join(out)
    if f" {host} {port} typ host" not in joined and "a=candidate:" in joined:
        # append tcp candidate after first candidate block if missing tcp
        pass
    text = "\r\n".join(out)
    if not text.endswith("\r\n"):
        text += "\r\n"
    # 若无 tcp 候选则追加一条
    if " tcp " not in text and "a=candidate:" in text:
        foundation = "tcpcand"
        text += (
            f"a=candidate:{foundation} 1 tcp 110 {host} {port} typ host tcptype passive\r\n"
        )
    return text


class ZlmClient:
    """封装 addStreamProxy / delStreamProxy / isMediaOnline 等。"""

    def __init__(
        self,
        api_base: str,
        secret: str = "",
        *,
        vhost: str = "__defaultVhost__",
        app: str = "live",
        rtsp_port: int = 554,
        http_port: int = 80,
        pull_host: str = "",
        pull_rtsp_port: int = 0,
        timeout: float = 8.0,
    ) -> None:
        self.api_base = (api_base or "http://127.0.0.1:80").rstrip("/") + "/"
        self.secret = secret or ""
        self.vhost = vhost or "__defaultVhost__"
        self.app = app or "live"
        self.rtsp_port = int(rtsp_port or 554)
        self.http_port = int(http_port or 80)
        self.pull_host = (pull_host or "").strip() or "127.0.0.1"
        self.pull_rtsp_port = int(pull_rtsp_port or 0) or self.rtsp_port
        self.timeout = float(timeout)
        self._key_by_stream: Dict[str, str] = {}

    def _params(self, extra: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        p: Dict[str, Any] = {}
        if self.secret:
            p["secret"] = self.secret
        if extra:
            p.update(extra)
        return p

    def _get(self, path: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        url = urljoin(self.api_base, path.lstrip("/"))
        try:
            r = requests.get(url, params=self._params(params), timeout=self.timeout)
            r.raise_for_status()
            data = r.json()
            if not isinstance(data, dict):
                return {"code": -1, "msg": "invalid json"}
            return data
        except Exception as e:  # noqa: BLE001
            logger.warning("ZLM GET %s failed: %s", path, e)
            return {"code": -1, "msg": str(e)}

    def probe(self) -> Dict[str, Any]:
        """探测可达性与鉴权。Docker 端口映射后源 IP 非 127.0.0.1，必须依赖 secret。"""
        data = self._get("/index/api/getApiList")
        code = int(data.get("code", -1))
        msg = str(data.get("msg") or "")
        if code == 0:
            return {"alive": True, "auth_ok": True, "message": ""}
        # -100 Please login first：服务可达但 secret 不匹配/仍为默认被服务端拒绝
        if code == -100 or "login" in msg.lower() or "secret" in msg.lower():
            return {
                "alive": True,
                "auth_ok": False,
                "message": msg or "API secret 无效（勿使用 ZLM 默认 secret）",
            }
        if code == -1:
            return {"alive": False, "auth_ok": False, "message": msg or "ZLM 请求失败"}
        return {"alive": False, "auth_ok": False, "message": msg or f"code={code}"}

    def alive(self) -> bool:
        p = self.probe()
        return bool(p.get("alive") and p.get("auth_ok"))

    def local_rtsp_url(self, stream: str, host: str = "") -> str:
        """worker 回源地址（compose 内用 zlmediakit:554；宿主机常用 127.0.0.1:8554）。"""
        h = (host or "").strip() or self.pull_host
        port = self.pull_rtsp_port
        return f"rtsp://{h}:{port}/{self.app}/{stream}"

    def play_urls(self, stream: str, host: str = "127.0.0.1", app: str = "") -> Dict[str, str]:
        """浏览器可播地址（相对本机/内网 host）。"""
        h = host or "127.0.0.1"
        app = (app or self.app).strip() or self.app
        return {
            "rtsp": f"rtsp://{h}:{self.rtsp_port}/{app}/{stream}",
            "http_flv": f"http://{h}:{self.http_port}/{app}/{stream}.live.flv",
            "hls": f"http://{h}:{self.http_port}/{app}/{stream}/hls.m3u8",
            "webrtc": f"http://{h}:{self.http_port}/index/api/webrtc?app={app}&stream={stream}&type=play",
        }

    def is_online(self, stream: str) -> bool:
        data = self._get(
            "/index/api/isMediaOnline",
            {
                "vhost": self.vhost,
                "app": self.app,
                "stream": stream,
                "schema": "rtsp",
            },
        )
        if int(data.get("code", -1)) != 0:
            return False
        return bool(data.get("online"))

    def ensure_proxy(
        self,
        stream_id: str,
        source_url: str,
        *,
        enable_hls: bool = True,
        enable_rtsp: bool = True,
        retry_count: int = 2,
    ) -> Dict[str, Any]:
        """为一路源 RTSP 建立拉流代理；已存在则复用。"""
        stream = stream_key_for_id(stream_id)
        source_url = (source_url or "").strip()
        if not source_url:
            return {"success": False, "message": "empty source url", "stream": stream}

        if self.is_online(stream):
            return {
                "success": True,
                "stream": stream,
                "local_rtsp": self.local_rtsp_url(stream),
                "play": self.play_urls(stream),
                "reused": True,
            }

        params = {
            "vhost": self.vhost,
            "app": self.app,
            "stream": stream,
            "url": source_url,
            "retry_count": max(0, int(retry_count)),
            "rtp_type": 0,
            "timeout_sec": 10,
            "enable_hls": 1 if enable_hls else 0,
            "enable_mp4": 0,
            "enable_rtsp": 1 if enable_rtsp else 0,
            "enable_rtmp": 1,
            "enable_ts": 0,
            "enable_fmp4": 0,
            "enable_audio": 1,
            "add_mute_audio": 1,
            "auto_close": 0,
        }
        data = self._get("/index/api/addStreamProxy", params)
        code = int(data.get("code", -1))
        if code != 0:
            return {
                "success": False,
                "message": data.get("msg") or f"addStreamProxy code={code}",
                "stream": stream,
                "raw": data,
            }
        key = ""
        if isinstance(data.get("data"), dict):
            key = str(data["data"].get("key") or "")
        if key:
            self._key_by_stream[stream] = key

        # 等待媒体上线
        deadline = time.time() + 12.0
        while time.time() < deadline:
            if self.is_online(stream):
                break
            time.sleep(0.4)

        return {
            "success": True,
            "stream": stream,
            "key": key,
            "local_rtsp": self.local_rtsp_url(stream),
            "play": self.play_urls(stream),
            "online": self.is_online(stream),
            "reused": False,
        }

    def webrtc_play(
        self,
        stream_id: str,
        offer_sdp: str,
        *,
        public_host: str = "",
        rtc_port: int = 8000,
        prefer_tcp: bool = True,
        app: str = "",
    ) -> Dict[str, Any]:
        """浏览器 WebRTC play：将 offer SDP POST 到 ZLM，返回 answer SDP。"""
        stream = stream_key_for_id(stream_id)
        sdp = (offer_sdp or "").strip()
        if not sdp:
            return {"success": False, "message": "empty offer sdp", "stream": stream}

        host = (public_host or "").strip() or "127.0.0.1"
        port = int(rtc_port)
        play_app = (app or "").strip() or self.app
        params: Dict[str, Any] = {
            "app": play_app,
            "stream": stream,
            "type": "play",
            # WSL2/Docker 下 UDP 映射常失败，优先 TCP ICE
            "preferred_tcp": 1 if prefer_tcp else 0,
            "cand_udp": f"{host}:{port}",
            "cand_tcp": f"{host}:{port}",
        }
        if self.secret:
            params["secret"] = self.secret

        url = urljoin(self.api_base, "/index/api/webrtc")
        try:
            r = requests.post(
                url,
                params=params,
                data=sdp.encode("utf-8"),
                headers={"Content-Type": "text/plain;charset=utf-8"},
                timeout=self.timeout,
            )
            r.raise_for_status()
            data = r.json()
        except Exception as e:  # noqa: BLE001
            logger.warning("ZLM webrtc play failed: %s", e)
            return {"success": False, "message": str(e), "stream": stream}

        if not isinstance(data, dict):
            return {"success": False, "message": "invalid webrtc response", "stream": stream}
        code = int(data.get("code", -1))
        answer = str(data.get("sdp") or "").strip()
        if code != 0 or not answer:
            return {
                "success": False,
                "message": data.get("msg") or f"webrtc code={code}",
                "stream": stream,
                "raw": data,
            }
        answer = rewrite_webrtc_sdp_host(answer, host, port)
        return {
            "success": True,
            "stream": stream,
            "sdp": answer,
            "type": "answer",
            "play": self.play_urls(stream, host=host),
        }

    def is_rtp_online(self, stream: str) -> bool:
        data = self._get(
            "/index/api/isMediaOnline",
            {
                "vhost": self.vhost,
                "app": "rtp",
                "stream": stream,
                "schema": "rtsp",
            },
        )
        if int(data.get("code", -1)) != 0:
            return False
        return bool(data.get("online"))

    def list_rtp_media(self) -> List[Dict[str, Any]]:
        data = self._get("/index/api/getMediaList", {"app": "rtp", "vhost": self.vhost})
        raw = data.get("data")
        if not isinstance(raw, list):
            return []
        return [x for x in raw if isinstance(x, dict)]

    def rtp_bytes_speed(self, stream: str) -> int:
        name = str(stream or "").strip()
        if not name:
            return 0
        speed = 0
        for item in self.list_rtp_media():
            sid = str(item.get("stream") or "")
            if sid != name and sid.upper() != name.upper():
                continue
            try:
                speed = max(speed, int(item.get("bytesSpeed") or 0))
            except (TypeError, ValueError):
                continue
        return speed

    def rtp_is_live(self, stream: str) -> bool:
        """isMediaOnline 对无推流的僵尸源也会为 true，必须看码率。"""
        return self.rtp_bytes_speed(stream) > 0

    def close_rtp_stream(self, stream: str) -> Dict[str, Any]:
        name = str(stream or "").strip()
        if not name:
            return {"success": False, "message": "empty stream"}
        data = self._get(
            "/index/api/close_streams",
            {
                "vhost": self.vhost,
                "app": "rtp",
                "stream": name,
                "force": 1,
            },
        )
        ok = int(data.get("code", -1)) == 0
        logger.info("ZLM close rtp/%s ok=%s msg=%s", name, ok, data.get("msg") or "")
        return {"success": ok, "stream": name, "raw": data}

    def rtp_online_name(self, *candidates: str, live_only: bool = False) -> str:
        """默认 rtp_proxy 口收流时，流名常是 SSRC 十六进制，不是 openRtp 的 stream_id。"""
        wanted = {str(x).strip() for x in candidates if str(x).strip()}
        wanted_u = {x.upper() for x in wanted}
        if live_only:
            for name in [str(x).strip() for x in candidates if str(x).strip()]:
                if self.rtp_is_live(name):
                    return name
            return ""
        for name in wanted:
            if self.is_rtp_online(name):
                return name
        for item in self.list_rtp_media():
            sid = str(item.get("stream") or "")
            if sid in wanted or sid.upper() in wanted_u:
                return sid
        return ""

    def rtp_live_name(self, *candidates: str) -> str:
        return self.rtp_online_name(*candidates, live_only=True)

    def rtp_rtsp_url(self, stream: str, host: str = "") -> str:
        h = (host or "").strip() or self.pull_host
        port = self.pull_rtsp_port
        return f"rtsp://{h}:{port}/rtp/{stream}"

    def list_rtp_server(self) -> List[Dict[str, Any]]:
        data = self._get("/index/api/listRtpServer")
        if int(data.get("code", -1)) != 0:
            return []
        raw = data.get("data")
        if isinstance(raw, list):
            return [x for x in raw if isinstance(x, dict)]
        return []

    def used_rtp_ports(self) -> Set[int]:
        used: Set[int] = set()
        for item in self.list_rtp_server():
            try:
                used.add(int(item.get("port")))
            except (TypeError, ValueError):
                continue
        return used

    def open_rtp_mux(
        self,
        stream: str,
        mux_port: int = 10000,
        *,
        tcp_mode: int = 2,
    ) -> Dict[str, Any]:
        """挂到 rtp_proxy 默认口（启动时已在听），避免再占 10001 却 bind 失败。"""
        port = max(1, min(65535, int(mux_port)))
        opened = self.open_rtp_server(stream, port=port, tcp_mode=int(tcp_mode))
        if opened.get("success"):
            opened["port"] = port
            opened["mux"] = True
            return opened
        # 默认口已被 rtp_proxy 占用时，仍视为可收流
        msg = str(opened.get("message") or "")
        if "already" in msg.lower() or "bind" in msg.lower() or "in use" in msg.lower():
            return {
                "success": True,
                "stream": stream,
                "port": port,
                "tcp_mode": int(tcp_mode),
                "mux": True,
                "reused": True,
                "message": msg,
            }
        return opened

    def open_rtp_in_range(
        self,
        stream: str,
        port_min: int,
        port_max: int,
        *,
        tcp_mode: int = 0,
        ssrc: str = "",
        reuse: bool = False,
    ) -> Dict[str, Any]:
        """每路一个端口。点播不要复用可能已失效的旧口。"""
        lo = max(1, min(65535, int(port_min)))
        hi = max(1, min(65535, int(port_max)))
        if hi < lo:
            lo, hi = hi, lo
        if reuse:
            for item in self.list_rtp_server():
                sid = str(item.get("stream_id") or item.get("stream") or "")
                if sid != stream:
                    continue
                try:
                    return {
                        "success": True,
                        "stream": stream,
                        "port": int(item.get("port")),
                        "tcp_mode": int(tcp_mode),
                        "reused": True,
                    }
                except (TypeError, ValueError):
                    break
        used = self.used_rtp_ports()
        last = "媒体端口范围内无空闲端口"
        for port in range(lo, hi + 1):
            # 10000 是 rtp_proxy 默认口，打上去会按 SSRC 十六进制命名（如 127A3981）
            if port == 10000 or port in used:
                continue
            opened = self.open_rtp_server(stream, port=port, tcp_mode=tcp_mode, ssrc=ssrc)
            if opened.get("success"):
                opened["tcp_mode"] = int(tcp_mode)
                return opened
            last = str(opened.get("message") or last)
        return {"success": False, "message": last, "stream": stream}

    def open_rtp_server(
        self,
        stream: str,
        *,
        port: int = 10000,
        tcp_mode: int = 0,
        ssrc: str = "",
    ) -> Dict[str, Any]:
        params: Dict[str, Any] = {
            "port": int(port),
            "tcp_mode": int(tcp_mode),
            "stream_id": stream,
        }
        if ssrc:
            params["ssrc"] = ssrc
        data = self._get("/index/api/openRtpServer", params)
        code = int(data.get("code", -1))
        # -300 already exists: reuse
        if code not in (0, -300):
            return {
                "success": False,
                "message": data.get("msg") or f"openRtpServer code={code}",
                "stream": stream,
                "raw": data,
            }
        got_port = port
        if isinstance(data.get("data"), dict) and data["data"].get("port"):
            try:
                got_port = int(data["data"]["port"])
            except (TypeError, ValueError):
                pass
        return {
            "success": True,
            "stream": stream,
            "port": got_port,
            "tcp_mode": int(tcp_mode),
            "raw": data,
        }

    def close_rtp_server(self, stream: str) -> Dict[str, Any]:
        data = self._get("/index/api/closeRtpServer", {"stream_id": stream})
        ok = int(data.get("code", -1)) == 0
        return {"success": ok, "stream": stream, "raw": data}

    def remove_proxy(self, stream_id: str) -> Dict[str, Any]:
        stream = stream_key_for_id(stream_id)
        key = self._key_by_stream.get(stream) or f"{self.vhost}/{self.app}/{stream}"
        data = self._get("/index/api/delStreamProxy", {"key": key})
        self._key_by_stream.pop(stream, None)
        ok = int(data.get("code", -1)) == 0
        return {"success": ok, "stream": stream, "raw": data}


_client: Optional[ZlmClient] = None


def get_zlm_client() -> Optional[ZlmClient]:
    global _client
    try:
        from visionai.config.settings import (
            ZLM_API_BASE,
            ZLM_APP,
            ZLM_ENABLED,
            ZLM_HTTP_PORT,
            ZLM_PULL_HOST,
            ZLM_PULL_RTSP_PORT,
            ZLM_RTSP_PORT,
            ZLM_SECRET,
            ZLM_VHOST,
        )
    except Exception:  # noqa: BLE001
        return None
    if not ZLM_ENABLED:
        return None
    if _client is None:
        _client = ZlmClient(
            ZLM_API_BASE,
            ZLM_SECRET,
            vhost=ZLM_VHOST,
            app=ZLM_APP,
            rtsp_port=ZLM_RTSP_PORT,
            http_port=ZLM_HTTP_PORT,
            pull_host=ZLM_PULL_HOST,
            pull_rtsp_port=ZLM_PULL_RTSP_PORT,
        )
    return _client
