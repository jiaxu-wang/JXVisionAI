"""Minimal SIP request/response codec for GB28181."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple


def _canon(name: str) -> str:
    return "-".join(p.capitalize() for p in name.split("-"))


@dataclass
class SipMessage:
    start_line: str = ""
    headers: Dict[str, List[str]] = field(default_factory=dict)
    body: str = ""

    @property
    def method(self) -> str:
        parts = self.start_line.split()
        if parts and parts[0].upper() != "SIP/2.0":
            return parts[0].upper()
        return ""

    @property
    def request_uri(self) -> str:
        parts = self.start_line.split()
        if len(parts) >= 2 and parts[0].upper() != "SIP/2.0":
            return parts[1]
        return ""

    @property
    def status(self) -> Optional[int]:
        parts = self.start_line.split()
        if len(parts) >= 2 and parts[0].upper() == "SIP/2.0":
            try:
                return int(parts[1])
            except ValueError:
                return None
        return None

    def get(self, name: str, default: str = "") -> str:
        vals = self.headers.get(name.lower())
        return vals[0] if vals else default

    def add(self, name: str, value: str) -> None:
        self.headers.setdefault(name.lower(), []).append(value)

    def set(self, name: str, value: str) -> None:
        self.headers[name.lower()] = [value]

    def via(self) -> str:
        return self.get("via")

    def from_header(self) -> str:
        return self.get("from") or self.get("f")

    def to_header(self) -> str:
        return self.get("to") or self.get("t")

    def call_id(self) -> str:
        return self.get("call-id") or self.get("i")

    def cseq(self) -> str:
        return self.get("cseq")

    def contact(self) -> str:
        return self.get("contact") or self.get("m")

    def encode(self) -> bytes:
        lines = [self.start_line]
        for key, vals in self.headers.items():
            if key == "content-length":
                continue
            for v in vals:
                lines.append(f"{_canon(key)}: {v}")
        body = self.body or ""
        lines.append(f"Content-Length: {len(body.encode('utf-8'))}")
        text = "\r\n".join(lines) + "\r\n\r\n" + body
        return text.encode("utf-8")


def parse_sip(raw: bytes) -> Optional[SipMessage]:
    if not raw:
        return None
    try:
        text = raw.decode("utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        return None
    text = text.replace("\r\n", "\n")
    if "\n\n" in text:
        head, body = text.split("\n\n", 1)
    else:
        head, body = text, ""
    lines = [ln.rstrip("\r") for ln in head.split("\n") if ln.strip() or True]
    if not lines:
        return None
    start = lines[0].strip()
    if not start:
        return None
    msg = SipMessage(start_line=start, body=body)
    current: Optional[str] = None
    for ln in lines[1:]:
        if not ln:
            continue
        if ln[0] in (" ", "\t") and current:
            msg.headers[current][-1] += ln.strip()
            continue
        if ":" not in ln:
            continue
        name, val = ln.split(":", 1)
        current = name.strip().lower()
        msg.add(current, val.strip())
    cl = msg.get("content-length")
    if cl.isdigit():
        n = int(cl)
        raw_body = body.encode("utf-8")[:n]
        msg.body = raw_body.decode("utf-8", errors="replace")
    return msg


def sip_uri_user(value: str) -> str:
    m = re.search(r"sip:([^@;>]+)@", value or "", re.I)
    if m:
        return m.group(1)
    m = re.search(r"sip:([^;>]+)", value or "", re.I)
    return m.group(1) if m else ""


def header_tag(value: str) -> str:
    m = re.search(r"[;?]tag=([^;>\s]+)", value or "", re.I)
    return m.group(1) if m else ""


def with_to_tag(to_hdr: str, tag: str) -> str:
    if header_tag(to_hdr):
        return to_hdr
    return f"{to_hdr};tag={tag}"


def parse_via_sent_by(via: str) -> Tuple[str, int]:
    m = re.search(r"SIP/2.0/\w+\s+([^:;>\s]+)(?::(\d+))?", via or "", re.I)
    if not m:
        return "", 5060
    host = m.group(1)
    port = int(m.group(2) or 5060)
    return host, port


def via_has_rport(via: str) -> bool:
    return "rport" in (via or "").lower()


def reply_via(via: str, recv_ip: str, recv_port: int) -> str:
    if not via:
        return via
    out = via
    if "received=" not in out.lower():
        out = f"{out};received={recv_ip}"
    if via_has_rport(via) and "rport=" not in out.lower():
        out = re.sub(r";rport(?!=)", f";rport={recv_port}", out, flags=re.I)
        if "rport=" not in out.lower():
            out = f"{out};rport={recv_port}"
    return out
