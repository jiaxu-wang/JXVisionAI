"""GB/T 28181 语音广播：Broadcast Notify XML 与音频 SDP。"""

from __future__ import annotations

import re
from typing import Any, Dict, Tuple


def notify_xml(source_id: str, target_id: str, sn: int) -> str:
    src = (source_id or "").strip()
    tgt = (target_id or "").strip()
    return (
        '<?xml version="1.0" encoding="GB2312"?>\r\n'
        "<Notify>\r\n"
        "<CmdType>Broadcast</CmdType>\r\n"
        f"<SN>{int(sn)}</SN>\r\n"
        f"<SourceID>{src}</SourceID>\r\n"
        f"<TargetID>{tgt}</TargetID>\r\n"
        "</Notify>\r\n"
    )


def parse_broadcast_response(body: str) -> Dict[str, str]:
    cmd = ""
    m = re.search(r"<CmdType>\s*([^<]+)\s*</CmdType>", body or "", re.I)
    if m:
        cmd = m.group(1).strip()
    did = ""
    m = re.search(r"<DeviceID>\s*([^<]+)\s*</DeviceID>", body or "", re.I)
    if m:
        did = m.group(1).strip()
    result = ""
    m = re.search(r"<Result>\s*([^<]+)\s*</Result>", body or "", re.I)
    if m:
        result = m.group(1).strip()
    return {"cmd": cmd, "device_id": did, "result": result}


def parse_audio_offer(sdp: str) -> Dict[str, Any]:
    """解析设备 INVITE 音频 offer。"""
    text = (sdp or "").replace("\r\n", "\n").replace("\r", "\n")
    conn = ""
    ssrc = ""
    audio: Dict[str, Any] = {
        "port": 0,
        "protocol": "RTP/AVP",
        "formats": [],
        "setup": "",
        "has_pcma": False,
        "has_pcmu": False,
        "has_ps": False,
        "tcp": False,
    }
    in_audio = False
    for raw in text.split("\n"):
        line = raw.strip()
        if not line:
            continue
        if line.startswith("c=IN IP4 "):
            conn = line.split()[-1].strip()
            continue
        if line.startswith("y="):
            ssrc = line[2:].strip()
            continue
        if line.startswith("m="):
            in_audio = line.lower().startswith("m=audio")
            if not in_audio:
                continue
            parts = line.split()
            try:
                audio["port"] = int(parts[1])
            except (IndexError, ValueError):
                audio["port"] = 0
            if len(parts) >= 3:
                audio["protocol"] = parts[2]
            audio["formats"] = parts[3:]
            audio["tcp"] = "TCP" in str(audio["protocol"]).upper()
            continue
        if not in_audio:
            continue
        low = line.lower()
        if low.startswith("a=rtpmap:"):
            val = line.split(":", 1)[-1].strip()
            if val.startswith("8 ") or "PCMA/8000" in val.upper():
                audio["has_pcma"] = True
            elif val.startswith("0 ") or "PCMU/8000" in val.upper():
                audio["has_pcmu"] = True
            elif "PS/90000" in val.upper():
                audio["has_ps"] = True
        elif low.startswith("a=setup:"):
            audio["setup"] = line.split(":", 1)[-1].strip().lower()
        elif low.startswith("a=ssrc:"):
            ssrc = ssrc or line.split(":", 1)[-1].split()[0].strip()
    formats = {str(x) for x in audio.get("formats") or []}
    if "8" in formats:
        audio["has_pcma"] = True
    if "0" in formats:
        audio["has_pcmu"] = True
    if "96" in formats:
        audio["has_ps"] = True
    audio["connection"] = conn
    audio["ssrc"] = ssrc
    return audio


def pick_payload(offer: Dict[str, Any]) -> Tuple[str, str, bool]:
    """返回 (pt, rtpmap 值, use_ps)。优先 PCMA。"""
    if offer.get("has_pcma"):
        return "8", "8 PCMA/8000", False
    if offer.get("has_ps"):
        return "96", "96 PS/90000", True
    if offer.get("has_pcmu"):
        return "0", "0 PCMU/8000", False
    return "8", "8 PCMA/8000", False


def answer_sdp(
    *,
    server_id: str,
    media_ip: str,
    port: int,
    ssrc: str,
    rtpmap: str,
    tcp: bool,
) -> str:
    sid = (server_id or "34020000002000000001").strip()
    ip = (media_ip or "").strip()
    lines = [
        "v=0",
        f"o={sid} 0 0 IN IP4 {ip}",
        "s=Play",
        f"c=IN IP4 {ip}",
        "t=0 0",
    ]
    if tcp:
        lines.append(f"m=audio {int(port)} TCP/RTP/AVP {rtpmap.split()[0]}")
        lines.extend(["a=setup:passive", "a=connection:new"])
    else:
        lines.append(f"m=audio {int(port)} RTP/AVP {rtpmap.split()[0]}")
    lines.extend(
        [
            f"a=rtpmap:{rtpmap}",
            "a=sendonly",
            f"y={ssrc}",
        ]
    )
    return "\r\n".join(lines) + "\r\n"
