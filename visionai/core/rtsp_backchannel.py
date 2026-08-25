"""ONVIF RTSP Audio Backchannel：能力探测与 G.711 上行对讲。

探测方式对齐 ODM：DESCRIBE 带 ``Require: www.onvif.org/ver20/backchannel``，
解析 SDP 中 ``a=sendonly`` 音频轨。对讲会话优先用 RTP/AVP/TCP interleaved，
便于穿越 NAT/防火墙。
"""

from __future__ import annotations

import logging
import random
import re
import socket
import struct
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import unquote, urlparse

logger = logging.getLogger(__name__)

BACKCHANNEL_REQUIRE = "www.onvif.org/ver20/backchannel"
DEFAULT_TIMEOUT = 6.0


def _parse_rtsp_url(url: str) -> Tuple[str, int, str, str, str]:
    """返回 host, port, path_query, username, password。"""
    u = urlparse((url or "").strip())
    if u.scheme not in ("rtsp", "rtsps"):
        raise ValueError("仅支持 rtsp/rtsps")
    host = u.hostname or ""
    if not host:
        raise ValueError("RTSP 缺少主机")
    port = int(u.port or (322 if u.scheme == "rtsps" else 554))
    path = u.path or "/"
    if u.query:
        path = f"{path}?{u.query}"
    user = unquote(u.username or "")
    password = unquote(u.password or "")
    return host, port, path, user, password


def _basic_auth_header(user: str, password: str) -> str:
    import base64

    token = base64.b64encode(f"{user}:{password}".encode("utf-8")).decode("ascii")
    return f"Authorization: Basic {token}\r\n"


def _parse_www_authenticate(header: str) -> Dict[str, str]:
    """解析 WWW-Authenticate: Digest realm="...", nonce="...", ..."。"""
    out: Dict[str, str] = {}
    h = (header or "").strip()
    if not h:
        return out
    if h.lower().startswith("digest"):
        out["scheme"] = "digest"
        h = h[6:].strip()
    elif h.lower().startswith("basic"):
        out["scheme"] = "basic"
        return out
    for m in re.finditer(r'(\w+)=(?:"([^"]*)"|([^\s,]+))', h):
        out[m.group(1).lower()] = m.group(2) if m.group(2) is not None else (m.group(3) or "")
    return out


def _digest_auth_header(
    user: str,
    password: str,
    method: str,
    uri: str,
    challenge: Dict[str, str],
    *,
    nc: int = 1,
) -> str:
    import hashlib
    import os

    realm = challenge.get("realm", "")
    nonce = challenge.get("nonce", "")
    qop = (challenge.get("qop") or "").split(",")[0].strip()
    opaque = challenge.get("opaque", "")
    algorithm = (challenge.get("algorithm") or "MD5").upper()
    if algorithm not in ("MD5", "MD5-SESS", ""):
        algorithm = "MD5"

    def md5(s: str) -> str:
        return hashlib.md5(s.encode("utf-8")).hexdigest()

    ha1 = md5(f"{user}:{realm}:{password}")
    ha2 = md5(f"{method}:{uri}")
    if qop:
        cnonce = os.urandom(8).hex()
        nc_str = f"{nc:08x}"
        if algorithm == "MD5-SESS":
            ha1 = md5(f"{ha1}:{nonce}:{cnonce}")
        response = md5(f"{ha1}:{nonce}:{nc_str}:{cnonce}:{qop}:{ha2}")
        parts = [
            f'username="{user}"',
            f'realm="{realm}"',
            f'nonce="{nonce}"',
            f'uri="{uri}"',
            f'response="{response}"',
            f"algorithm={algorithm or 'MD5'}",
            f'qop={qop}',
            f"nc={nc_str}",
            f'cnonce="{cnonce}"',
        ]
        if opaque:
            parts.append(f'opaque="{opaque}"')
        return "Authorization: Digest " + ", ".join(parts) + "\r\n"
    response = md5(f"{ha1}:{nonce}:{ha2}")
    parts = [
        f'username="{user}"',
        f'realm="{realm}"',
        f'nonce="{nonce}"',
        f'uri="{uri}"',
        f'response="{response}"',
    ]
    if opaque:
        parts.append(f'opaque="{opaque}"')
    return "Authorization: Digest " + ", ".join(parts) + "\r\n"


class _RtspConn:
    """带 Basic/Digest 重试的简易 RTSP 连接。"""

    def __init__(self, host: str, port: int, user: str, password: str, timeout: float):
        self.host = host
        self.port = port
        self.user = user
        self.password = password
        self.timeout = timeout
        self.sock = socket.create_connection((host, port), timeout=timeout)
        self.cseq = 1
        self._challenge: Dict[str, str] = {}
        self._nc = 1

    def close(self) -> None:
        sock = self.sock
        self.sock = None
        if sock is None:
            return
        try:
            sock.close()
        except Exception:  # noqa: BLE001
            pass

    def detach(self) -> socket.socket:
        """交出底层 socket，供对讲会话长期持有。"""
        sock = self.sock
        self.sock = None
        if sock is None:
            raise RuntimeError("RTSP 连接已关闭")
        return sock

    def _auth_header(self, method: str, url: str) -> str:
        if not self.user:
            return ""
        # 海康等设备：必须先无 Authorization 拿 401，再在同一 TCP 上带 Digest；
        # 勿先发 Basic，也勿换连后复用旧 nonce（会一直 401）。
        if self._challenge.get("scheme") == "digest" or self._challenge.get("nonce"):
            hdr = _digest_auth_header(
                self.user, self.password, method, url, self._challenge, nc=self._nc
            )
            self._nc += 1
            return hdr
        return ""

    def request(
        self, method: str, url: str, extra: str = "", *, allow_digest_retry: bool = True
    ) -> Tuple[str, Dict[str, str], bytes]:
        if self.sock is None:
            self.sock = socket.create_connection((self.host, self.port), timeout=self.timeout)
        auth = self._auth_header(method, url)
        req = (
            f"{method} {url} RTSP/1.0\r\n"
            f"CSeq: {self.cseq}\r\n"
            f"User-Agent: JXVisionAI-Talk/1.0\r\n"
            f"{auth}"
            f"{extra}"
            f"\r\n"
        )
        self.cseq += 1
        try:
            self.sock.sendall(req.encode("utf-8"))
            status, _, headers, body = _recv_rtsp_response(self.sock, self.timeout)
        except (OSError, TimeoutError, ConnectionError):
            # 仅连接断开时重连；Digest 必须尽量在同一 TCP 完成
            try:
                if self.sock is not None:
                    self.sock.close()
            except Exception:  # noqa: BLE001
                pass
            self.sock = socket.create_connection((self.host, self.port), timeout=self.timeout)
            self._challenge = {}
            self._nc = 1
            if not allow_digest_retry:
                raise
            # 新连接重新走 401→Digest
            return self.request(method, url, extra=extra, allow_digest_retry=True)
        code_m = re.match(r"RTSP/1\.\d\s+(\d+)", status)
        code = int(code_m.group(1)) if code_m else 0
        if code in (401, 407) and allow_digest_retry and self.user:
            wa = headers.get("www-authenticate") or headers.get("proxy-authenticate") or ""
            ch = _parse_www_authenticate(wa)
            if ch.get("scheme") == "digest" or "nonce" in ch:
                ch.setdefault("scheme", "digest")
                self._challenge = ch
                self._nc = 1
                return self.request(method, url, extra=extra, allow_digest_retry=False)
            if ch.get("scheme") == "basic":
                # 少数设备仅 Basic：同连接补发一次
                auth_b = _basic_auth_header(self.user, self.password)
                req_b = (
                    f"{method} {url} RTSP/1.0\r\n"
                    f"CSeq: {self.cseq}\r\n"
                    f"User-Agent: JXVisionAI-Talk/1.0\r\n"
                    f"{auth_b}"
                    f"{extra}"
                    f"\r\n"
                )
                self.cseq += 1
                self.sock.sendall(req_b.encode("utf-8"))
                status, _, headers, body = _recv_rtsp_response(self.sock, self.timeout)
                return status, headers, body
        return status, headers, body


@dataclass
class BackchannelProbeResult:
    ok: bool
    talk_supported: bool = False
    talk_protocol: str = ""
    codec: str = ""
    payload_type: int = 0
    sample_rate: int = 8000
    channels: int = 1
    control_url: str = ""
    detail: str = ""
    sdp_summary: str = ""
    error: str = ""

    def as_dict(self) -> Dict[str, Any]:
        return {
            "ok": self.ok,
            "talk_supported": self.talk_supported,
            "talk_protocol": self.talk_protocol,
            "codec": self.codec,
            "payload_type": self.payload_type,
            "sample_rate": self.sample_rate,
            "channels": self.channels,
            "control_url": self.control_url,
            "detail": self.detail,
            "sdp_summary": self.sdp_summary,
            "error": self.error,
        }


def _recv_rtsp_response(sock: socket.socket, timeout: float) -> Tuple[str, bytes, Dict[str, str], bytes]:
    sock.settimeout(timeout)
    buf = b""
    while b"\r\n\r\n" not in buf:
        chunk = sock.recv(4096)
        if not chunk:
            break
        buf += chunk
        if len(buf) > 256 * 1024:
            break
    if b"\r\n\r\n" not in buf:
        raise RuntimeError("RTSP 响应不完整")
    header_raw, rest = buf.split(b"\r\n\r\n", 1)
    header_text = header_raw.decode("utf-8", errors="replace")
    lines = header_text.split("\r\n")
    status_line = lines[0] if lines else ""
    headers: Dict[str, str] = {}
    for line in lines[1:]:
        if ":" in line:
            k, v = line.split(":", 1)
            headers[k.strip().lower()] = v.strip()
    body = rest
    cl = int(headers.get("content-length", "0") or "0")
    while len(body) < cl:
        chunk = sock.recv(min(4096, cl - len(body)))
        if not chunk:
            break
        body += chunk
    return status_line, header_raw, headers, body[:cl] if cl else body


def _parse_sendonly_audio(sdp: str) -> Optional[Dict[str, Any]]:
    """从 SDP 找 ONVIF backchannel 音频轨（a=sendonly）。"""
    blocks = re.split(r"(?=^m=)", sdp or "", flags=re.M)
    for block in blocks:
        if not block.startswith("m=audio"):
            continue
        if not re.search(r"^a=sendonly", block, re.M | re.I):
            # 部分设备用 inactive + backchannel 标记；仍要求 sendonly/sendrecv
            if not re.search(r"^a=sendrecv", block, re.M | re.I):
                continue
        m_line = block.splitlines()[0]
        # m=audio 0 RTP/AVP 0 8
        parts = m_line.split()
        pts = [int(x) for x in parts[3:] if x.isdigit()] if len(parts) >= 4 else []
        codec = ""
        pt = pts[0] if pts else 0
        rate = 8000
        ch = 1
        control = ""
        for line in block.splitlines():
            if line.startswith("a=control:"):
                control = line.split(":", 1)[1].strip()
            # codec 名不可用 \S+：否则 PCMU/8000/1 会被吃成 name=PCMU/8000、rate=1
            m = re.match(r"a=rtpmap:(\d+)\s+([^\s/]+)/(\d+)(?:/(\d+))?", line, re.I)
            if m:
                this_pt = int(m.group(1))
                name = m.group(2).upper()
                if name in ("PCMU", "PCMA", "G711U", "G711A") or this_pt in (0, 8):
                    pt = this_pt
                    codec = "PCMU" if name in ("PCMU", "G711U") or this_pt == 0 else "PCMA"
                    rate = int(m.group(3) or 8000)
                    ch = int(m.group(4) or 1)
        if not codec and pt == 0:
            codec = "PCMU"
        if not codec and pt == 8:
            codec = "PCMA"
        if not codec and pts:
            # 默认按列表顺序优先 G.711
            if 0 in pts:
                codec, pt = "PCMU", 0
            elif 8 in pts:
                codec, pt = "PCMA", 8
            else:
                codec, pt = "PCMU", pts[0]
        return {
            "codec": codec or "PCMA",
            "payload_type": int(pt),
            "sample_rate": rate if rate > 1 else 8000,
            "channels": ch,
            "control": control,
            "m_line": m_line.strip(),
        }
    return None


def probe_rtsp_backchannel(rtsp_url: str, timeout: float = DEFAULT_TIMEOUT) -> BackchannelProbeResult:
    """对 RTSP URL 做 ONVIF backchannel DESCRIBE 探测（类似 ODM）。"""
    try:
        host, port, path, user, password = _parse_rtsp_url(rtsp_url)
    except ValueError as e:
        return BackchannelProbeResult(ok=False, error=str(e))

    conn: Optional[_RtspConn] = None
    try:
        conn = _RtspConn(host, port, user, password, timeout)
        base = f"rtsp://{host}:{port}{path}"

        try:
            conn.request("OPTIONS", base)
        except Exception:  # noqa: BLE001
            pass

        status, headers, body = conn.request(
            "DESCRIBE",
            base,
            extra=f"Accept: application/sdp\r\nRequire: {BACKCHANNEL_REQUIRE}\r\n",
        )
        code_m = re.match(r"RTSP/1\.\d\s+(\d+)", status)
        code = int(code_m.group(1)) if code_m else 0
        if code in (401, 407):
            return BackchannelProbeResult(
                ok=False,
                error=f"RTSP 鉴权失败({code})，请确认 URL 内账号密码（已尝试 Digest）",
                detail=status,
            )
        if code == 551 or "option not supported" in (status + str(headers)).lower():
            return BackchannelProbeResult(
                ok=True,
                talk_supported=False,
                talk_protocol="",
                detail="设备拒绝 backchannel Require（无 ONVIF Audio Backchannel）",
                error="",
            )
        if code != 200:
            status2, _, body2 = conn.request("DESCRIBE", base, extra="Accept: application/sdp\r\n")
            code2_m = re.match(r"RTSP/1\.\d\s+(\d+)", status2)
            code2 = int(code2_m.group(1)) if code2_m else 0
            if code2 != 200:
                return BackchannelProbeResult(
                    ok=False,
                    error=f"DESCRIBE 失败: {status}",
                    detail=status2,
                )
            sdp = body2.decode("utf-8", errors="replace")
            audio = _parse_sendonly_audio(sdp)
            if not audio:
                return BackchannelProbeResult(
                    ok=True,
                    talk_supported=False,
                    detail=f"带 Require 的 DESCRIBE 返回 {status}；普通 SDP 亦无 sendonly 音频轨",
                )
            return BackchannelProbeResult(
                ok=True,
                talk_supported=True,
                talk_protocol="rtsp-backchannel",
                codec=audio["codec"],
                payload_type=audio["payload_type"],
                sample_rate=audio["sample_rate"],
                channels=audio["channels"],
                control_url=audio["control"],
                detail="普通 SDP 含 sendonly 音频（未强制 Require）",
                sdp_summary=audio["m_line"],
            )

        sdp = body.decode("utf-8", errors="replace")
        audio = _parse_sendonly_audio(sdp)
        if not audio:
            return BackchannelProbeResult(
                ok=True,
                talk_supported=False,
                talk_protocol="",
                detail="DESCRIBE(backchannel) 成功但 SDP 无 sendonly 音频轨",
                sdp_summary="(no sendonly audio)",
            )
        return BackchannelProbeResult(
            ok=True,
            talk_supported=True,
            talk_protocol="rtsp-backchannel",
            codec=audio["codec"],
            payload_type=audio["payload_type"],
            sample_rate=audio["sample_rate"],
            channels=audio["channels"],
            control_url=audio["control"],
            detail="ONVIF RTSP Audio Backchannel 可用",
            sdp_summary=audio["m_line"],
        )
    except Exception as e:  # noqa: BLE001
        logger.warning("RTSP backchannel probe failed: %s", e)
        return BackchannelProbeResult(ok=False, error=f"探测异常: {e}")
    finally:
        if conn is not None:
            conn.close()


@dataclass
class TalkSession:
    session_id: str
    stream_id: str
    rtsp_url: str
    codec: str = "PCMA"
    payload_type: int = 8
    sample_rate: int = 8000
    created_at: float = field(default_factory=time.time)
    _sock: Optional[socket.socket] = field(default=None, repr=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)
    _cseq: int = 1
    _session: str = ""
    _interleaved: int = 0
    _seq: int = field(default_factory=lambda: random.randint(0, 0xFFFF))
    _timestamp: int = 0
    _ssrc: int = field(default_factory=lambda: random.randint(1, 0x7FFFFFFF))
    _closed: bool = False
    detail: str = ""

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            sock = self._sock
            self._sock = None
        if sock is not None:
            try:
                if self._session:
                    self._teardown(sock)
            except Exception:  # noqa: BLE001
                pass
            try:
                sock.close()
            except Exception:  # noqa: BLE001
                pass

    def _teardown(self, sock: socket.socket) -> None:
        host, port, path, user, password = _parse_rtsp_url(self.rtsp_url)
        base = f"rtsp://{host}:{port}{path}"
        auth = _basic_auth_header(user, password) if user else ""
        req = (
            f"TEARDOWN {base} RTSP/1.0\r\n"
            f"CSeq: {self._cseq}\r\n"
            f"Session: {self._session}\r\n"
            f"User-Agent: JXVisionAI-Talk/1.0\r\n"
            f"{auth}\r\n"
        )
        try:
            sock.sendall(req.encode("utf-8"))
        except Exception:  # noqa: BLE001
            pass

    def send_g711(self, payload: bytes) -> int:
        """发送一帧/多帧 G.711（已编码），返回发送字节数。"""
        if not payload:
            return 0
        with self._lock:
            if self._closed or self._sock is None:
                raise RuntimeError("对讲会话已关闭")
            sock = self._sock
            pt = self.payload_type
            # 按 20ms @ 8kHz = 160 samples 切包
            frame = 160
            sent = 0
            off = 0
            while off < len(payload):
                chunk = payload[off : off + frame]
                off += len(chunk)
                rtp = struct.pack(
                    "!BBHII",
                    0x80,
                    pt & 0x7F,
                    self._seq & 0xFFFF,
                    self._timestamp & 0xFFFFFFFF,
                    self._ssrc & 0xFFFFFFFF,
                ) + chunk
                self._seq = (self._seq + 1) & 0xFFFF
                self._timestamp = (self._timestamp + len(chunk)) & 0xFFFFFFFF
                # interleaved: $, channel, len_hi, len_lo, rtp
                header = struct.pack("!BBH", 0x24, self._interleaved & 0xFF, len(rtp))
                sock.sendall(header + rtp)
                sent += len(chunk)
            return sent


def open_backchannel_session(
    rtsp_url: str,
    *,
    session_id: str,
    stream_id: str,
    timeout: float = DEFAULT_TIMEOUT,
) -> TalkSession:
    """建立带 backchannel 的 RTSP 会话（TCP interleaved）。"""
    host, port, path, user, password = _parse_rtsp_url(rtsp_url)
    conn = _RtspConn(host, port, user, password, timeout)
    base = f"rtsp://{host}:{port}{path}"

    try:
        status, headers, body = conn.request(
            "DESCRIBE",
            base,
            extra=f"Accept: application/sdp\r\nRequire: {BACKCHANNEL_REQUIRE}\r\n",
        )
        code_m = re.match(r"RTSP/1\.\d\s+(\d+)", status)
        code = int(code_m.group(1)) if code_m else 0
        if code != 200:
            status, headers, body = conn.request(
                "DESCRIBE", base, extra="Accept: application/sdp\r\n"
            )
            code_m = re.match(r"RTSP/1\.\d\s+(\d+)", status)
            code = int(code_m.group(1)) if code_m else 0
        if code != 200:
            raise RuntimeError(f"DESCRIBE 失败: {status}")

        content_base = headers.get("content-base") or headers.get("content-location") or base
        sdp = body.decode("utf-8", errors="replace")
        audio = _parse_sendonly_audio(sdp)
        if not audio:
            raise RuntimeError("SDP 无 sendonly 对讲音频轨")

        control = audio["control"] or ""
        if control.startswith("rtsp://"):
            setup_url = control
        elif control:
            setup_url = content_base.rstrip("/") + "/" + control.lstrip("/")
        else:
            setup_url = base

        status, headers, _ = conn.request(
            "SETUP",
            setup_url,
            extra="Transport: RTP/AVP/TCP;unicast;interleaved=0-1\r\n"
            f"Require: {BACKCHANNEL_REQUIRE}\r\n",
        )
        code_m = re.match(r"RTSP/1\.\d\s+(\d+)", status)
        code = int(code_m.group(1)) if code_m else 0
        if code != 200:
            status, headers, _ = conn.request(
                "SETUP",
                setup_url,
                extra="Transport: RTP/AVP/TCP;unicast;interleaved=0-1\r\n",
            )
            code_m = re.match(r"RTSP/1\.\d\s+(\d+)", status)
            code = int(code_m.group(1)) if code_m else 0
        if code != 200:
            raise RuntimeError(f"SETUP 失败: {status}")

        session = (headers.get("session") or "").split(";")[0].strip()
        transport = headers.get("transport") or ""
        interleaved = 0
        m = re.search(r"interleaved=(\d+)", transport, re.I)
        if m:
            interleaved = int(m.group(1))

        status, _, _ = conn.request(
            "PLAY",
            base,
            extra=f"Session: {session}\r\nRange: npt=0.000-\r\n",
        )
        code_m = re.match(r"RTSP/1\.\d\s+(\d+)", status)
        code = int(code_m.group(1)) if code_m else 0
        if code not in (200, 202):
            raise RuntimeError(f"PLAY 失败: {status}")

        ts = TalkSession(
            session_id=session_id,
            stream_id=stream_id,
            rtsp_url=rtsp_url,
            codec=audio["codec"],
            payload_type=int(audio["payload_type"]),
            sample_rate=int(audio["sample_rate"]),
            detail=f"TCP interleaved={interleaved}, {audio['codec']}/{audio['sample_rate']}",
        )
        ts._sock = conn.detach()
        ts._cseq = conn.cseq
        ts._session = session
        ts._interleaved = interleaved
        return ts
    except Exception:
        conn.close()
        raise
