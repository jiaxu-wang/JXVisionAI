"""GB28181 SIP 信令：REGISTER / Keepalive / Catalog / INVITE。"""

from __future__ import annotations

import asyncio
import logging
import secrets
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, Optional, Tuple

from visionai.core import gb28181_store as store
from visionai.core.redis_manager import redis_manager
from visionai.core.sip import broadcast as bc
from visionai.core.sip import catalog as cat
from visionai.core.sip import ptz as ptzcmd
from visionai.core.sip.cmd import blpop_cmd, reply_cmd
from visionai.core.sip.digest import verify_digest
from visionai.core.sip.message import (
    SipMessage,
    parse_sip,
    reply_via,
    sip_uri_user,
    via_has_rport,
    with_to_tag,
)

logger = logging.getLogger(__name__)


def _now() -> str:
    return store._now_str()


def _branch() -> str:
    return "z9hG4bK" + secrets.token_hex(8)


def _tag() -> str:
    return secrets.token_hex(6)


def _call_id() -> str:
    return secrets.token_hex(12)


def _gb_date() -> str:
    try:
        from visionai.utils.timeutil import app_now

        return app_now().strftime("%Y-%m-%dT%H:%M:%S.000")
    except Exception:  # noqa: BLE001
        return time.strftime("%Y-%m-%dT%H:%M:%S.000")


def _ssrc_for(channel_id: str, serial: str = "") -> str:
    return store.ssrc_for_channel(channel_id, serial)


def _ssrc_stream_names(ssrc: str) -> list:
    return store.ssrc_stream_names(ssrc)


@dataclass
class DeviceSession:
    sip_user: str
    contact_ip: str
    contact_port: int
    transport: str
    last_register: float = 0.0
    last_keepalive: float = 0.0
    missed_keepalive: int = 0
    via_rport: bool = False
    tcp_writer: Optional[asyncio.StreamWriter] = None
    invites: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    nonce: str = ""


class SipStack:
    def __init__(self) -> None:
        self.sessions: Dict[str, DeviceSession] = {}
        self._nonces: Dict[str, str] = {}
        self._udp: Optional[asyncio.DatagramTransport] = None
        self._cseq = 20
        self._sn = 1
        self._stopping = False
        self._broadcasts: Dict[str, Dict[str, Any]] = {}
        self._broadcast_waiters: Dict[str, asyncio.Future] = {}
        self._boot_id = uuid.uuid4().hex

    def platform(self) -> Dict[str, Any]:
        return store.get_platform(redis_manager)

    def _listen_transports(self, plat: Dict[str, Any]) -> Tuple[bool, bool]:
        t = str(plat.get("transport") or "tcp").lower()
        if t == "both":
            return True, True
        if t == "udp":
            return True, False
        return False, True

    async def run(self) -> None:
        # Redis 里上次的 online 不能当会话：重启后内存 sessions 是空的。
        store.mark_all_runtime_offline(redis_manager)
        plat = self.platform()
        host = str(plat.get("bind_host") or "0.0.0.0")
        port = int(plat.get("bind_port") or 5060)
        use_udp, use_tcp = self._listen_transports(plat)
        logger.info(
            "GB28181 SIP listen %s:%s transport=%s udp=%s tcp=%s",
            host,
            port,
            plat.get("transport"),
            use_udp,
            use_tcp,
        )
        loop = asyncio.get_running_loop()
        if use_udp:
            self._udp, _proto = await loop.create_datagram_endpoint(
                lambda: _UdpProto(self),
                local_addr=(host, port),
            )
        servers = []
        if use_tcp:
            servers.append(await asyncio.start_server(self._handle_tcp, host=host, port=port))
        tasks = [
            asyncio.create_task(self._alive_loop(), name="sip-alive"),
            asyncio.create_task(self._expire_loop(), name="sip-expire"),
            asyncio.create_task(self._cmd_loop(), name="sip-cmd"),
        ]
        try:
            if servers:
                await asyncio.gather(*(s.serve_forever() for s in servers), *tasks)
            else:
                await asyncio.gather(*tasks)
        finally:
            self._stopping = True
            for t in tasks:
                t.cancel()
            if self._udp:
                self._udp.close()
            for s in servers:
                s.close()

    async def _handle_tcp(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        peer = writer.get_extra_info("peername") or ("0.0.0.0", 0)
        addr = (str(peer[0]), int(peer[1]))
        try:
            while not self._stopping:
                raw = await _read_sip_tcp(reader)
                if not raw:
                    break
                resp = await self.handle(
                    raw, addr, transport_name="tcp", tcp_writer=writer
                )
                if resp:
                    writer.write(resp)
                    await writer.drain()
        except Exception:
            logger.debug("tcp sip closed %s", addr)
        finally:
            for user, sess in list(self.sessions.items()):
                if sess.tcp_writer is writer:
                    logger.info("tcp sip disconnect %s device=%s", addr, user)
                    self._write_runtime(user, sess, status="offline", note="TCP 连接断开")
                    self.sessions.pop(user, None)
            try:
                writer.close()
                await writer.wait_closed()
            except Exception:  # noqa: BLE001
                pass

    async def _alive_loop(self) -> None:
        while not self._stopping:
            store.touch_sip_alive(
                redis_manager,
                ttl_sec=15,
                boot_id=self._boot_id,
                session_count=len(self.sessions),
            )
            await asyncio.sleep(5)

    async def _expire_loop(self) -> None:
        while not self._stopping:
            await asyncio.sleep(10)
            plat = self.platform()
            interval = float(plat.get("keepalive_interval_sec") or 60)
            max_miss = int(plat.get("keepalive_timeout_count") or 3)
            now = time.time()
            for user, sess in list(self.sessions.items()):
                last = max(sess.last_keepalive, sess.last_register)
                if last and now - last > interval * 1.5:
                    sess.missed_keepalive += 1
                    sess.last_keepalive = now
                if sess.missed_keepalive >= max_miss:
                    logger.info("device timeout offline: %s", user)
                    self._write_runtime(user, sess, status="offline", note="心跳超时")
                    self.sessions.pop(user, None)

    async def _cmd_loop(self) -> None:
        while not self._stopping:
            cmd = await asyncio.to_thread(blpop_cmd, 1)
            if not cmd:
                continue
            rid = str(cmd.get("request_id") or "")
            op = str(cmd.get("op") or "")
            try:
                if op == "invite":
                    result = await self.invite_play(
                        str(cmd.get("device_id") or ""),
                        str(cmd.get("channel_id") or ""),
                        force=bool(cmd.get("force")),
                    )
                elif op == "bye":
                    result = await self.bye_play(
                        str(cmd.get("device_id") or ""),
                        str(cmd.get("channel_id") or ""),
                    )
                elif op == "catalog":
                    result = await self.query_catalog(str(cmd.get("device_id") or ""))
                elif op == "ptz":
                    result = await self.ptz_control(cmd)
                elif op == "broadcast":
                    result = await self.start_broadcast(cmd)
                elif op == "broadcast_stop":
                    result = await self.stop_broadcast(
                        str(cmd.get("device_id") or ""),
                        str(cmd.get("channel_id") or ""),
                    )
                else:
                    result = {"ok": False, "message": f"unknown op {op}"}
            except Exception as e:  # noqa: BLE001
                logger.exception("sip cmd %s failed", op)
                result = {"ok": False, "message": str(e)}
            reply_cmd(rid, result)

    def _touch_or_restore_session(
        self,
        sip_user: str,
        msg: SipMessage,
        peer: Tuple[str, int],
        transport_name: str,
        tcp_writer: Optional[asyncio.StreamWriter],
    ) -> Optional[DeviceSession]:
        """REGISTER 后的 Keepalive 也可恢复会话（信令重启后不必等重新 REGISTER）。"""
        sip_user = (sip_user or "").strip()
        if not sip_user:
            return None
        device = store.find_device_for_channel(redis_manager, sip_user)
        if device:
            sip_user = str(device.get("sip_user") or sip_user)
        sess = self.sessions.get(sip_user)
        if sess:
            sess.last_keepalive = time.time()
            sess.missed_keepalive = 0
            sess.contact_ip = peer[0]
            sess.contact_port = int(peer[1])
            sess.transport = transport_name
            if tcp_writer is not None:
                sess.tcp_writer = tcp_writer
            return sess
        if not device:
            return None
        via = msg.via()
        sess = DeviceSession(
            sip_user=sip_user,
            contact_ip=peer[0],
            contact_port=int(peer[1]),
            transport=transport_name,
            last_register=time.time(),
            last_keepalive=time.time(),
            via_rport=via_has_rport(via),
            tcp_writer=tcp_writer,
        )
        self.sessions[sip_user] = sess
        logger.info(
            "SIP session restored from MESSAGE %s %s:%s %s",
            sip_user,
            peer[0],
            peer[1],
            transport_name,
        )
        return sess

    def _device_password(self, plat: Dict[str, Any], device: Dict[str, Any]) -> str:
        return store.effective_password(plat, device)

    def _write_runtime(
        self,
        sip_user: str,
        sess: DeviceSession,
        *,
        status: str,
        note: str = "",
        channels: Optional[list] = None,
    ) -> None:
        store.write_runtime(
            redis_manager,
            sip_user,
            {
                "status": status,
                "last_register_at": _now() if status == "online" else "",
                "last_keepalive_at": _now() if status == "online" else "",
                "remote_ip": sess.contact_ip,
                "remote_port": sess.contact_port,
                "transport": sess.transport,
                "via_rport": sess.via_rport,
                "sip_boot_id": self._boot_id,
                "note": note,
                "channels": channels or [],
            },
        )

    async def handle(
        self,
        raw: bytes,
        peer: Tuple[str, int],
        *,
        transport_name: str,
        tcp_writer: Optional[asyncio.StreamWriter] = None,
    ) -> Optional[bytes]:
        msg = parse_sip(raw)
        if not msg:
            return None
        if msg.status is not None:
            return await self._on_response(msg, peer)
        if not msg.method:
            return None
        method = msg.method
        if method == "REGISTER":
            return self._on_register(msg, peer, transport_name, tcp_writer)
        if method == "MESSAGE":
            return await self._on_message(msg, peer, transport_name, tcp_writer)
        if method == "ACK":
            return None
        if method in ("BYE", "CANCEL"):
            await self._on_bye(msg)
            return self._reply(msg, 200, "OK", peer)
        if method == "INVITE" and msg.status is None:
            return await self._on_invite(msg, peer)
        return self._reply(msg, 200, "OK", peer) if msg.status is None else None

    def _on_register(
        self,
        msg: SipMessage,
        peer: Tuple[str, int],
        transport_name: str,
        tcp_writer: Optional[asyncio.StreamWriter],
    ) -> bytes:
        plat = self.platform()
        sip_user = sip_uri_user(msg.from_header()) or sip_uri_user(msg.to_header())
        if not plat.get("enabled"):
            logger.warning("REGISTER rejected %s from %s:%s: 平台未启用", sip_user, peer[0], peer[1])
            return self._reply(msg, 403, "Platform Disabled", peer)
        device = store.get_device(redis_manager, sip_user)
        if not device:
            logger.warning("REGISTER rejected %s from %s:%s: 未知 SIP 用户", sip_user, peer[0], peer[1])
            return self._reply(msg, 403, "User Unknown", peer)
        realm = str(plat.get("realm") or plat.get("domain") or "")
        auth_id = str(device.get("auth_id") or sip_user)
        password = self._device_password(plat, device)
        auth = msg.get("authorization")
        nonce = self._nonces.get(sip_user) or secrets.token_hex(8)
        if not auth:
            self._nonces[sip_user] = nonce
            extra = {
                "WWW-Authenticate": (
                    f'Digest realm="{realm}", nonce="{nonce}", algorithm=MD5'
                )
            }
            return self._reply(msg, 401, "Unauthorized", peer, extra=extra)
        if not verify_digest(
            auth,
            username=auth_id,
            realm=realm,
            password=password,
            method="REGISTER",
            request_uri=msg.request_uri,
            nonce=nonce,
        ):
            logger.warning("REGISTER rejected %s from %s:%s: Digest 认证失败", sip_user, peer[0], peer[1])
            return self._reply(msg, 403, "Forbidden", peer)

        expires_hdr = msg.get("expires")
        try:
            expires = int(expires_hdr) if expires_hdr else int(plat.get("register_expires_sec") or 3600)
        except ValueError:
            expires = int(plat.get("register_expires_sec") or 3600)
        if expires <= 0:
            self.sessions.pop(sip_user, None)
            self._write_runtime(
                sip_user,
                DeviceSession(sip_user, peer[0], peer[1], transport_name),
                status="offline",
                note="注销",
            )
            return self._reply(msg, 200, "OK", peer, extra={"Expires": "0"})

        via = msg.via()
        sess = DeviceSession(
            sip_user=sip_user,
            contact_ip=peer[0],
            contact_port=int(peer[1]),
            transport=transport_name,
            last_register=time.time(),
            last_keepalive=time.time(),
            via_rport=via_has_rport(via),
            tcp_writer=tcp_writer,
        )
        self.sessions[sip_user] = sess
        self._nonces.pop(sip_user, None)
        self._write_runtime(sip_user, sess, status="online", note="REGISTER")
        logger.info("REGISTER ok %s from %s:%s %s", sip_user, peer[0], peer[1], transport_name)
        extra = {
            "Expires": str(plat.get("register_expires_sec") or 3600),
            "Date": _gb_date(),
            "Contact": msg.contact() or f"<sip:{sip_user}@{peer[0]}:{peer[1]}>",
        }
        resp = self._reply(msg, 200, "OK", peer, extra=extra)
        asyncio.create_task(self.query_catalog(sip_user))
        return resp

    async def _on_message(
        self,
        msg: SipMessage,
        peer: Tuple[str, int],
        transport_name: str,
        tcp_writer: Optional[asyncio.StreamWriter],
    ) -> bytes:
        body = msg.body or ""
        cmd = cat.manscdp_cmd(body).lower()
        sip_user = sip_uri_user(msg.from_header()) or cat.manscdp_device_id(body)
        sess = self._touch_or_restore_session(
            sip_user, msg, peer, transport_name, tcp_writer
        )
        if cmd == "keepalive":
            if sess:
                self._write_runtime(sess.sip_user, sess, status="online", note="Keepalive")
            return self._reply(msg, 200, "OK", peer)
        if cmd in ("catalog",) and "<Item>" in body:
            items = cat.parse_catalog_items(body)
            owner = (sess.sip_user if sess else sip_user)
            if owner and items:
                store.merge_catalog_channels(redis_manager, owner, items)
                logger.info("Catalog merged %s items=%d", owner, len(items))
            return self._reply(msg, 200, "OK", peer)
        if cmd == "broadcast":
            info = bc.parse_broadcast_response(body)
            owner = sess.sip_user if sess else sip_user
            audio_ch = str(info.get("device_id") or "").strip()
            result = str(info.get("result") or "").strip()
            ok = result.upper() == "OK"
            waiter = self._broadcast_waiters.get(owner or "")
            if waiter and not waiter.done():
                waiter.set_result(info)
            if ok and owner and audio_ch:
                pending = self._broadcasts.get(owner)
                if pending:
                    pending["audio_channel_id"] = audio_ch
                device = store.get_device(redis_manager, owner)
                if device and store.is_voice_output_id(audio_ch):
                    try:
                        store.upsert_device(
                            redis_manager,
                            {**device, "audio_out_channel_id": audio_ch, "auto_allocate": False},
                        )
                    except Exception:  # noqa: BLE001
                        logger.exception("save audio_out_channel failed %s", owner)
            logger.info(
                "Broadcast response %s ch=%s result=%s",
                owner,
                audio_ch,
                result or "(empty)",
            )
            return self._reply(msg, 200, "OK", peer)
        return self._reply(msg, 200, "OK", peer)

    def _reply(
        self,
        req: SipMessage,
        code: int,
        reason: str,
        peer: Tuple[str, int],
        extra: Optional[Dict[str, str]] = None,
        body: str = "",
        content_type: str = "",
    ) -> bytes:
        resp = SipMessage(start_line=f"SIP/2.0 {code} {reason}")
        via = req.via()
        if via:
            resp.set("Via", reply_via(via, peer[0], peer[1]))
        frm = req.from_header()
        if frm:
            resp.set("From", frm)
        to_hdr = req.to_header()
        if to_hdr:
            resp.set("To", with_to_tag(to_hdr, _tag()) if code != 401 else to_hdr)
        if req.call_id():
            resp.set("Call-ID", req.call_id())
        if req.cseq():
            resp.set("CSeq", req.cseq())
        resp.set("User-Agent", "JXVisionAI-SIP")
        for k, v in (extra or {}).items():
            resp.set(k, v)
        if body:
            resp.body = body
            if content_type:
                resp.set("Content-Type", content_type)
        return resp.encode()

    async def _send_to_device(self, sess: DeviceSession, data: bytes) -> None:
        if sess.transport == "tcp" and sess.tcp_writer is not None:
            sess.tcp_writer.write(data)
            await sess.tcp_writer.drain()
            return
        if self._udp:
            self._udp.sendto(data, (sess.contact_ip, sess.contact_port))

    def _next_cseq(self) -> int:
        self._cseq += 1
        return self._cseq

    def _build_request(
        self,
        method: str,
        plat: Dict[str, Any],
        sess: DeviceSession,
        request_uri: str,
        *,
        to_user: str,
        body: str = "",
        content_type: str = "",
        extra: Optional[Dict[str, str]] = None,
    ) -> SipMessage:
        server_id = str(plat.get("server_id") or "")
        domain = str(plat.get("domain") or "")
        public_host = str(plat.get("public_host") or sess.contact_ip)
        public_port = int(plat.get("public_port") or plat.get("bind_port") or 5060)
        proto = "TCP" if sess.transport == "tcp" else "UDP"
        msg = SipMessage(start_line=f"{method} {request_uri} SIP/2.0")
        msg.set(
            "Via",
            f"SIP/2.0/{proto} {public_host}:{public_port};rport;branch={_branch()}",
        )
        msg.set("From", f"<sip:{server_id}@{domain}>;tag={_tag()}")
        msg.set("To", f"<sip:{to_user}@{domain}>")
        msg.set("Call-ID", _call_id())
        msg.set("CSeq", f"{self._next_cseq()} {method}")
        msg.set("Max-Forwards", "70")
        msg.set("User-Agent", "JXVisionAI-SIP")
        msg.set("Contact", f"<sip:{server_id}@{public_host}:{public_port}>")
        if body:
            msg.body = body
            if content_type:
                msg.set("Content-Type", content_type)
        for k, v in (extra or {}).items():
            msg.set(k, v)
        return msg

    async def _on_response(self, msg: SipMessage, peer: Tuple[str, int]) -> Optional[bytes]:
        cseq = msg.cseq()
        method = cseq.split()[-1].upper() if cseq else ""
        if method == "INVITE" and msg.status == 200:
            call_id = msg.call_id()
            logger.info("INVITE 200 from %s:%s call_id=%s", peer[0], peer[1], call_id)
            for sess in self.sessions.values():
                info = None
                for _ch, item in sess.invites.items():
                    if item.get("call_id") == call_id:
                        info = item
                        break
                if info is None and sess.contact_ip != peer[0]:
                    continue
                if info is None:
                    info = {}
                else:
                    info["to"] = msg.to_header()
                if msg.body:
                    sdp_lines = [
                        ln for ln in msg.body.replace("\r\n", "\n").split("\n") if ln
                    ]
                    logger.info("INVITE 200 sdp %s", " | ".join(sdp_lines[:24]))
                ack_uri = self._ack_uri(msg, info, sess)
                plat = self.platform()
                public_host = str(plat.get("public_host") or sess.contact_ip)
                public_port = int(plat.get("public_port") or plat.get("bind_port") or 15060)
                server_id = str(plat.get("server_id") or "")
                proto = "TCP" if sess.transport == "tcp" else "UDP"
                ack = SipMessage(start_line=f"ACK {ack_uri} SIP/2.0")
                ack.set(
                    "Via",
                    info.get("via")
                    or f"SIP/2.0/{proto} {public_host}:{public_port};rport;branch={_branch()}",
                )
                ack.set("From", info.get("from") or msg.from_header())
                ack.set("To", msg.to_header())
                if call_id:
                    ack.set("Call-ID", call_id)
                cseq_num = ""
                if info.get("cseq"):
                    cseq_num = str(info.get("cseq") or "").split()[0]
                if not cseq_num and cseq:
                    cseq_num = cseq.split()[0]
                ack.set("CSeq", f"{cseq_num or '1'} ACK")
                ack.set("Max-Forwards", "70")
                ack.set("User-Agent", "JXVisionAI-SIP")
                ack.set("Contact", f"<sip:{server_id}@{public_host}:{public_port}>")
                await self._send_to_device(sess, ack.encode())
                logger.info("ACK sent %s uri=%s", sess.sip_user, ack_uri)
                break
        elif method == "INVITE" and msg.status and msg.status >= 400:
            logger.warning("INVITE failed %s from %s:%s", msg.status, peer[0], peer[1])
            call_id = msg.call_id()
            for sess in self.sessions.values():
                for item in sess.invites.values():
                    if item.get("call_id") == call_id:
                        item["fail_status"] = msg.status
                        break
        return None

    def _ack_uri(
        self,
        msg: SipMessage,
        info: Optional[Dict[str, Any]] = None,
        sess: Optional[DeviceSession] = None,
    ) -> str:
        # 海康 200 Contact 常是设备 ID；ACK 对 INVITE 的通道 URI 更稳
        stored = str((info or {}).get("invite_uri") or "").strip()
        target = str((info or {}).get("channel_id") or "")
        contact = (msg.contact() or "").strip()
        if contact.startswith("<") and ">" in contact:
            contact = contact[1:contact.index(">")]
        contact = contact.split(";")[0].strip()
        contact_user = sip_uri_user(contact) if contact else ""
        if stored and target and contact_user and contact_user != target:
            return stored
        if contact.lower().startswith("sip:"):
            return contact
        if stored:
            return stored
        if target and sess:
            return f"sip:{target}@{sess.contact_ip}:{sess.contact_port}"
        user = sip_uri_user(msg.to_header())
        return f"sip:{user}"

    def _play_sdp(
        self,
        plat: Dict[str, Any],
        media_ip: str,
        port: int,
        ssrc: str,
        *,
        tcp: bool,
    ) -> str:
        server_id = str(plat.get("server_id") or "")
        lines = [
            "v=0",
            f"o={server_id} 0 0 IN IP4 {media_ip}",
            "s=Play",
            f"c=IN IP4 {media_ip}",
            "t=0 0",
        ]
        if tcp:
            lines.append(f"m=video {port} TCP/RTP/AVP 96")
            lines.append("a=setup:passive")
            lines.append("a=connection:new")
        else:
            lines.append(f"m=video {port} RTP/AVP 96")
        lines.extend(
            [
                "a=recvonly",
                "a=rtpmap:96 PS/90000",
                f"y={ssrc}",
                "f=",
            ]
        )
        return "\r\n".join(lines) + "\r\n"

    async def _send_invite(
        self,
        plat: Dict[str, Any],
        sess: DeviceSession,
        target: str,
        sdp: str,
        ssrc: str,
        stream: str,
    ) -> Dict[str, Any]:
        invite_uri = f"sip:{target}@{sess.contact_ip}:{sess.contact_port}"
        req = self._build_request(
            "INVITE",
            plat,
            sess,
            invite_uri,
            to_user=target,
            body=sdp,
            content_type="Application/SDP",
            extra={"Subject": f"{target}:{ssrc},{plat.get('server_id')}:0"},
        )
        await self._send_to_device(sess, req.encode())
        sess.invites[target] = {
            "call_id": req.call_id(),
            "from": req.from_header(),
            "to": req.to_header(),
            "via": req.via(),
            "cseq": req.cseq(),
            "stream": stream,
            "ssrc": ssrc,
            "invite_uri": invite_uri,
            "channel_id": target,
        }
        return sess.invites[target]

    async def _send_dialog_bye(
        self,
        sess: DeviceSession,
        target: str,
        info: Optional[Dict[str, Any]],
    ) -> None:
        if not info:
            return
        plat = self.platform()
        req = self._build_request(
            "BYE",
            plat,
            sess,
            str(info.get("invite_uri") or f"sip:{target}@{sess.contact_ip}:{sess.contact_port}"),
            to_user=target,
        )
        if info.get("call_id"):
            req.set("Call-ID", str(info["call_id"]))
        if info.get("from"):
            req.set("From", str(info["from"]))
        if info.get("to"):
            req.set("To", str(info["to"]))
        await self._send_to_device(sess, req.encode())

    async def _wait_rtp(self, zlm: Any, stream: str, seconds: float, ssrc: str = "") -> str:
        names = [stream, *(_ssrc_stream_names(ssrc) if ssrc else [])]
        steps = max(1, int(seconds / 0.4))
        for _ in range(steps):
            await asyncio.sleep(0.4)
            got = zlm.rtp_online_name(*names)
            if got:
                return got
        return ""

    def _session_for(self, device_id: str) -> Optional[DeviceSession]:
        sess = self.sessions.get(device_id)
        if sess:
            return sess
        device = store.get_device(redis_manager, device_id)
        sip_user = str((device or {}).get("sip_user") or "")
        if sip_user and sip_user != device_id:
            return self.sessions.get(sip_user)
        return None

    async def query_catalog(self, device_id: str) -> Dict[str, Any]:
        sess = self._session_for(device_id)
        if not sess:
            return {"ok": False, "message": "设备未注册"}
        plat = self.platform()
        domain = str(plat.get("domain") or "")
        self._sn += 1
        body = cat.catalog_query_xml(device_id, self._sn)
        req = self._build_request(
            "MESSAGE",
            plat,
            sess,
            f"sip:{device_id}@{sess.contact_ip}:{sess.contact_port}",
            to_user=device_id,
            body=body,
            content_type="Application/MANSCDP+xml",
        )
        await self._send_to_device(sess, req.encode())
        return {"ok": True, "message": "Catalog 已发送"}

    async def ptz_control(self, spec: Dict[str, Any]) -> Dict[str, Any]:
        device_id = str(spec.get("device_id") or "").strip()
        channel_id = str(spec.get("channel_id") or "").strip()
        if not device_id or not channel_id:
            return {"ok": False, "message": "缺少设备或通道"}
        sess = self._session_for(device_id)
        if not sess:
            return {
                "ok": False,
                "message": "设备未在 SIP 注册：信令进程内存中没有该设备会话，无法点播。请等待摄像机 REGISTER 或心跳后再试",
            }
        hex_cmd, err = ptzcmd.encode_action(spec)
        if err or not hex_cmd:
            return {"ok": False, "message": err or "PTZ 编码失败"}
        plat = self.platform()
        self._sn += 1
        body = ptzcmd.control_xml(channel_id, self._sn, hex_cmd)
        req = self._build_request(
            "MESSAGE",
            plat,
            sess,
            f"sip:{channel_id}@{sess.contact_ip}:{sess.contact_port}",
            to_user=channel_id,
            body=body,
            content_type="Application/MANSCDP+xml",
        )
        await self._send_to_device(sess, req.encode())
        logger.info(
            "PTZ %s ch=%s action=%s cmd=%s",
            device_id,
            channel_id,
            spec.get("action"),
            hex_cmd,
        )
        return {"ok": True, "ptz_cmd": hex_cmd, "channel_id": channel_id}

    def _zlm(self) -> Any:
        try:
            from visionai.core.zlm_client import get_zlm_client

            return get_zlm_client()
        except Exception:  # noqa: BLE001
            return None

    def _broadcast_for(self, device_id: str) -> Optional[Dict[str, Any]]:
        if not device_id:
            return None
        hit = self._broadcasts.get(device_id)
        if hit:
            return hit
        for item in self._broadcasts.values():
            if device_id in (
                str(item.get("device_id") or ""),
                str(item.get("audio_channel_id") or ""),
                str(item.get("video_channel_id") or ""),
            ):
                return item
        return None

    async def start_broadcast(self, spec: Dict[str, Any]) -> Dict[str, Any]:
        device_id = str(spec.get("device_id") or "").strip()
        video_ch = str(spec.get("channel_id") or "").strip()
        app = str(spec.get("app") or store.BROADCAST_APP).strip() or store.BROADCAST_APP
        stream = str(spec.get("stream") or "").strip()
        if not device_id or not video_ch:
            return {"ok": False, "message": "缺少设备或通道"}
        sess = self._session_for(device_id)
        if not sess:
            return {
                "ok": False,
                "message": "设备未在 SIP 注册：请等摄像机心跳或重新 REGISTER 后再试",
            }
        device = store.get_device(redis_manager, device_id)
        targets = store.broadcast_target_candidates(device, video_ch)
        if not targets:
            return {"ok": False, "message": "未找到广播目标通道"}
        if not stream:
            stream = store.broadcast_stream_id(device_id, video_ch)
        existing = self._broadcasts.get(sess.sip_user)
        if existing:
            await self.stop_broadcast(device_id, video_ch)
            await asyncio.sleep(0.2)
        # rtc 在线即可 Notify；rtsp 转封装在 INVITE 的 startSendRtp 重试里等，避免先卡 2 秒
        if not await self._wait_app_stream(app, stream, 1.2):
            return {"ok": False, "message": "麦克风音频尚未到达 ZLM，请再开一次麦克风"}
        plat = self.platform()
        server_id = str(plat.get("server_id") or "")
        last_err = ""
        accepted = ""
        for audio_ch in targets:
            self._sn += 1
            body = bc.notify_xml(server_id, audio_ch, self._sn)
            req = self._build_request(
                "MESSAGE",
                plat,
                sess,
                f"sip:{audio_ch}@{sess.contact_ip}:{sess.contact_port}",
                to_user=audio_ch,
                body=body,
                content_type="Application/MANSCDP+xml",
            )
            loop = asyncio.get_running_loop()
            fut: asyncio.Future = loop.create_future()
            self._broadcast_waiters[sess.sip_user] = fut
            await self._send_to_device(sess, req.encode())
            logger.info(
                "Broadcast notify %s target=%s stream=%s/%s",
                sess.sip_user,
                audio_ch,
                app,
                stream,
            )
            try:
                info = await asyncio.wait_for(fut, 3.0)
            except asyncio.TimeoutError:
                info = {"result": "TIMEOUT", "device_id": audio_ch}
            if self._broadcast_waiters.get(sess.sip_user) is fut:
                self._broadcast_waiters.pop(sess.sip_user, None)
            result = str((info or {}).get("result") or "").strip().upper()
            if result == "OK":
                accepted = str((info or {}).get("device_id") or audio_ch).strip() or audio_ch
                break
            last_err = result or "无应答"
            logger.warning(
                "Broadcast rejected %s target=%s result=%s, try next",
                sess.sip_user,
                audio_ch,
                last_err,
            )
        if not accepted:
            return {
                "ok": False,
                "message": f"摄像机拒绝广播（{last_err or '无应答'}）。可先确认预览已出图，目标通道是否为视频编码而非虚构 137",
            }
        self._broadcasts[sess.sip_user] = {
            "device_id": sess.sip_user,
            "video_channel_id": video_ch,
            "audio_channel_id": accepted,
            "app": app,
            "stream": stream,
            "ssrc": "",
            "tcp": True,
        }
        return {
            "ok": True,
            "message": "Broadcast 已接受，等待设备 INVITE",
            "audio_channel_id": accepted,
            "app": app,
            "stream": stream,
        }

    async def stop_broadcast(self, device_id: str, channel_id: str = "") -> Dict[str, Any]:
        sess = self._session_for(device_id)
        key = (sess.sip_user if sess else device_id).strip()
        info = self._broadcast_for(key) or self._broadcast_for(channel_id)
        if info:
            key = str(info.get("device_id") or key)
        self._stop_send_rtp(info)
        if sess and info:
            audio_ch = str(info.get("audio_channel_id") or channel_id or "")
            plat = self.platform()
            bye_uri = str(
                info.get("invite_uri")
                or f"sip:{audio_ch}@{sess.contact_ip}:{sess.contact_port}"
            )
            req = self._build_request(
                "BYE",
                plat,
                sess,
                bye_uri,
                to_user=audio_ch,
            )
            if info.get("call_id"):
                req.set("Call-ID", str(info["call_id"]))
            if info.get("to"):
                req.set("From", str(info["to"]))
            if info.get("from"):
                req.set("To", str(info["from"]))
            try:
                await self._send_to_device(sess, req.encode())
            except Exception:  # noqa: BLE001
                logger.exception("broadcast BYE failed %s", key)
        self._broadcasts.pop(key, None)
        return {"ok": True, "message": "已停止广播"}

    def _stop_send_rtp(self, info: Optional[Dict[str, Any]]) -> None:
        if not info:
            return
        zlm = self._zlm()
        if not zlm:
            return
        try:
            zlm.stop_send_rtp(
                app=str(info.get("app") or store.BROADCAST_APP),
                stream=str(info.get("stream") or ""),
                ssrc=str(info.get("ssrc") or ""),
            )
        except Exception:  # noqa: BLE001
            logger.exception("stopSendRtp failed")

    async def _wait_app_stream(self, app: str, stream: str, seconds: float = 5.0) -> bool:
        zlm = self._zlm()
        if not zlm or not stream:
            return False
        deadline = time.time() + max(0.2, float(seconds))
        while time.time() < deadline:
            if zlm.is_app_online(stream, app, "rtc") or zlm.is_app_online(stream, app, "rtsp"):
                return True
            await asyncio.sleep(0.05)
        return zlm.is_app_online(stream, app)

    async def _start_send_rtp_retry(
        self,
        *,
        use_tcp: bool,
        app: str,
        stream: str,
        ssrc: str,
        pt: str,
        use_ps: bool,
        dst: str = "",
        dst_port: int = 0,
    ) -> Dict[str, Any]:
        zlm = self._zlm()
        last: Dict[str, Any] = {"success": False, "message": "ZLM 不可用"}
        if zlm is None:
            return last
        for i in range(40):
            if use_tcp:
                last = zlm.start_send_rtp_passive(
                    app=app, stream=stream, ssrc=ssrc, pt=pt, use_ps=use_ps, only_audio=True
                )
            else:
                last = zlm.start_send_rtp(
                    app=app,
                    stream=stream,
                    ssrc=ssrc,
                    pt=pt,
                    dst_url=dst,
                    dst_port=dst_port,
                    use_ps=use_ps,
                    only_audio=True,
                    is_udp=True,
                )
            if last.get("success"):
                if i:
                    logger.info("startSendRtp ok after retry %s %s/%s", i, app, stream)
                return last
            logger.warning("startSendRtp retry %s %s/%s: %s", i, app, stream, last.get("message"))
            await asyncio.sleep(0.05)
        return last

    async def _on_bye(self, msg: SipMessage) -> None:
        call_id = msg.call_id()
        if not call_id:
            return
        for key, info in list(self._broadcasts.items()):
            if str(info.get("call_id") or "") == call_id:
                self._stop_send_rtp(info)
                self._broadcasts.pop(key, None)
                logger.info("broadcast BYE from device %s", key)
                return

    async def _on_invite(self, msg: SipMessage, peer: Tuple[str, int]) -> bytes:
        from_user = sip_uri_user(msg.from_header())
        to_user = sip_uri_user(msg.to_header())
        device = store.find_device_for_channel(redis_manager, from_user) or store.find_device_for_channel(
            redis_manager, to_user
        )
        sip_user = str((device or {}).get("sip_user") or from_user or "")
        pending = self._broadcast_for(sip_user) or self._broadcast_for(from_user)
        if not pending:
            logger.info("inbound INVITE ignored from=%s (no broadcast)", from_user)
            return self._reply(msg, 488, "Not Acceptable Here", peer)
        offer = bc.parse_audio_offer(msg.body or "")
        if not offer.get("port") and not (msg.body or "").strip():
            return self._reply(msg, 400, "Bad Request", peer)
        audio_ch = from_user
        if audio_ch == sip_user:
            audio_ch = str(pending.get("audio_channel_id") or audio_ch)
        pending["audio_channel_id"] = audio_ch or pending.get("audio_channel_id")
        pt, rtpmap, use_ps = bc.pick_payload(offer)
        ssrc = str(offer.get("ssrc") or "").strip()
        if not ssrc:
            ssrc = _ssrc_for(audio_ch or pending.get("video_channel_id") or sip_user)
        pending["ssrc"] = ssrc
        use_tcp = bool(offer.get("tcp")) or str(offer.get("setup") or "") in ("active", "actpass", "passive")
        pending["tcp"] = use_tcp
        zlm = self._zlm()
        if zlm is None:
            return self._reply(msg, 503, "Service Unavailable", peer)
        app = str(pending.get("app") or store.BROADCAST_APP)
        stream = str(pending.get("stream") or "")
        dst = str(offer.get("connection") or peer[0])
        dst_port = int(offer.get("port") or 0)
        sent = await self._start_send_rtp_retry(
            use_tcp=use_tcp,
            app=app,
            stream=stream,
            ssrc=ssrc,
            pt=pt,
            use_ps=use_ps,
            dst=dst,
            dst_port=dst_port,
        )
        if not sent.get("success"):
            logger.warning("startSendRtp failed %s: %s", sip_user, sent.get("message"))
            return self._reply(msg, 488, "Not Acceptable Here", peer)
        plat = self.platform()
        media_ip = str(plat.get("media_ip") or plat.get("public_host") or "")
        local_port = int(sent.get("local_port") or 0)
        sdp = bc.answer_sdp(
            server_id=str(plat.get("server_id") or ""),
            media_ip=media_ip,
            port=local_port,
            ssrc=ssrc,
            rtpmap=rtpmap,
            tcp=use_tcp,
        )
        sess = self._session_for(sip_user)
        public_host = str(plat.get("public_host") or (sess.contact_ip if sess else media_ip))
        public_port = int(plat.get("public_port") or plat.get("bind_port") or 15060)
        server_id = str(plat.get("server_id") or "")
        extra = {"Contact": f"<sip:{server_id}@{public_host}:{public_port}>"}
        raw = self._reply(
            msg,
            200,
            "OK",
            peer,
            extra=extra,
            body=sdp,
            content_type="Application/SDP",
        )
        # 记下带 tag 的 To，停止时 BYE 要互换 From/To
        parsed = parse_sip(raw)
        pending["call_id"] = msg.call_id()
        pending["from"] = msg.from_header()
        pending["to"] = parsed.to_header() if parsed else msg.to_header()
        pending["invite_uri"] = (
            f"sip:{audio_ch}@{(sess.contact_ip if sess else peer[0])}:"
            f"{(sess.contact_port if sess else peer[1])}"
        )
        logger.info(
            "broadcast INVITE 200 %s audio=%s tcp=%s pt=%s port=%s stream=%s/%s",
            sip_user,
            audio_ch,
            use_tcp,
            pt,
            local_port,
            app,
            stream,
        )
        return raw

    async def invite_play(
        self, device_id: str, channel_id: str, *, force: bool = False
    ) -> Dict[str, Any]:
        plat = self.platform()
        media_ip = str(plat.get("media_ip") or "").strip()
        port_min = int(plat.get("media_port") or 0)
        port_max = int(plat.get("media_port_end") or port_min or 0)
        if not media_ip or not port_min:
            return {"ok": False, "message": "请先填写媒体收流 IP 与端口范围（勿与 SIP 对外地址混用）"}
        sess = self._session_for(device_id)
        if not sess:
            return {
                "ok": False,
                "message": "设备未在 SIP 注册：信令进程内存中没有该设备会话，无法点播。请等待摄像机 REGISTER 或心跳后再试",
            }
        device = store.get_device(redis_manager, device_id)
        channels = store.normalize_channels((device or {}).get("channels") or [])
        target = (channel_id or "").strip()
        if not target:
            target = channels[0]["channel_id"] if channels else device_id
        stream = store.rtp_stream_id(device_id, target)
        ssrc = _ssrc_for(target, str(plat.get("server_id") or ""))
        zlm = None
        try:
            from visionai.core.zlm_client import get_zlm_client

            zlm = get_zlm_client()
        except Exception:  # noqa: BLE001
            zlm = None
        if zlm is None:
            return {"ok": False, "message": "ZLM 未启用或不可达"}
        aliases = [stream, *_ssrc_stream_names(ssrc)]
        got = zlm.rtp_live_name(stream)
        if got == stream and not force:
            logger.info("GB media live as rtp/%s, skip INVITE", got)
            return {
                "ok": True,
                "stream": got,
                "url": store.rtp_pull_url(got),
                "channel_id": target,
                "reused": True,
            }
        for name in aliases:
            if zlm.is_rtp_online(name) and (force or name != stream or not zlm.rtp_is_live(name)):
                logger.info("close stale rtp/%s before INVITE force=%s", name, force)
                zlm.close_rtp_stream(name)
        zlm.close_rtp_server(stream)
        await asyncio.sleep(0.3)
        if force:
            last_info = sess.invites.get(target)
            if last_info:
                await self._send_dialog_bye(sess, target, last_info)
                sess.invites.pop(target, None)
        # 独立 RTP 口 + openRtpServer(stream_id=设备_通道)，不要打到 rtp_proxy:10000
        # 否则 ZLM 会用 SSRC 十六进制当流名（0310000001 → 127A3981）
        last_info: Optional[Dict[str, Any]] = None
        play_stream = stream
        range_end = port_max if port_max >= port_min else port_min
        for use_tcp in (True, False):
            if last_info:
                if last_info.get("fail_status"):
                    await self._send_dialog_bye(sess, target, last_info)
                    sess.invites.pop(target, None)
                else:
                    got = zlm.rtp_live_name(stream)
                    if got == stream:
                        logger.info("GB media live as rtp/%s", got)
                        return {
                            "ok": True,
                            "stream": stream,
                            "url": store.rtp_pull_url(stream),
                            "channel_id": target,
                        }
                    await self._send_dialog_bye(sess, target, last_info)
                    sess.invites.pop(target, None)
                zlm.close_rtp_server(stream)
            tcp_mode = 1 if use_tcp else 0
            opened = zlm.open_rtp_in_range(
                stream,
                port_min,
                range_end,
                tcp_mode=tcp_mode,
                ssrc=ssrc,
                reuse=False,
            )
            if not opened.get("success"):
                logger.warning(
                    "openRtp %s failed tcp_mode=%s: %s",
                    stream,
                    tcp_mode,
                    opened.get("message"),
                )
                continue
            use_port = int(opened.get("port") or 0)
            if not use_port:
                continue
            sdp = self._play_sdp(plat, media_ip, use_port, ssrc, tcp=use_tcp)
            last_info = await self._send_invite(plat, sess, target, sdp, ssrc, stream)
            logger.info(
                "INVITE %s ch=%s media=%s:%s stream=%s proto=%s ssrc=%s openRtp=%s",
                device_id,
                target,
                media_ip,
                use_port,
                stream,
                "TCP" if use_tcp else "UDP",
                ssrc,
                opened.get("message") or "ok",
            )
            got = ""
            for _ in range(20):
                await asyncio.sleep(0.4)
                if last_info.get("fail_status"):
                    break
                got = zlm.rtp_live_name(stream)
                if got == stream:
                    break
            if got == stream:
                logger.info("GB media live as rtp/%s", stream)
                return {
                    "ok": True,
                    "stream": stream,
                    "url": store.rtp_pull_url(stream),
                    "channel_id": target,
                }
            if last_info.get("fail_status") == 415:
                logger.warning("INVITE 415, try next proto")
                continue
        return {
            "ok": True,
            "stream": play_stream,
            "url": store.rtp_pull_url(play_stream),
            "channel_id": target,
            "media_online": False,
            "message": "INVITE 已发送，媒体尚未上线（未在 rtp/%s 收到推流）" % stream,
        }

    async def bye_play(self, device_id: str, channel_id: str) -> Dict[str, Any]:
        sess = self.sessions.get(device_id)
        target = (channel_id or "").strip()
        info = (sess.invites.pop(target, None) if sess else None)
        stream = store.rtp_stream_id(device_id, target) if target else ""
        if sess and info:
            await self._send_dialog_bye(sess, target, info)
        try:
            from visionai.core.zlm_client import get_zlm_client

            zlm = get_zlm_client()
            if zlm and stream:
                zlm.close_rtp_server(stream)
        except Exception as e:  # noqa: BLE001
            logger.debug("closeRtpServer: %s", e)
        return {"ok": True, "stream": stream}


class _UdpProto(asyncio.DatagramProtocol):
    def __init__(self, stack: SipStack):
        self.stack = stack

    def datagram_received(self, data: bytes, addr) -> None:
        asyncio.create_task(self._handle(data, addr))

    async def _handle(self, data: bytes, addr) -> None:
        try:
            resp = await self.stack.handle(data, addr, transport_name="udp")
            if resp and self.stack._udp:
                self.stack._udp.sendto(resp, addr)
        except Exception:
            logger.exception("udp sip handle failed")


async def _read_sip_tcp(reader: asyncio.StreamReader) -> Optional[bytes]:
    header = b""
    while b"\r\n\r\n" not in header and b"\n\n" not in header:
        chunk = await reader.read(4096)
        if not chunk:
            return header or None
        header += chunk
        if len(header) > 65536:
            return None
    sep = b"\r\n\r\n" if b"\r\n\r\n" in header else b"\n\n"
    head, rest = header.split(sep, 1)
    cl = 0
    for ln in head.replace(b"\r\n", b"\n").split(b"\n"):
        if ln.lower().startswith(b"content-length:"):
            try:
                cl = int(ln.split(b":", 1)[1].strip() or 0)
            except ValueError:
                cl = 0
    while len(rest) < cl:
        rest += await reader.read(cl - len(rest))
        if not rest:
            break
    return head + sep + rest[:cl]
