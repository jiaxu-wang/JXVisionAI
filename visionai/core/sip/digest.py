"""SIP Digest (RFC 2617) for GB28181 REGISTER."""

from __future__ import annotations

import hashlib
import re
from typing import Dict


def md5_hex(text: str) -> str:
    return hashlib.md5(text.encode("utf-8")).hexdigest()


def parse_authorization(header: str) -> Dict[str, str]:
    out: Dict[str, str] = {}
    if not header:
        return out
    raw = header.strip()
    if raw.lower().startswith("digest"):
        raw = raw[6:].strip()
    for m in re.finditer(r'(\w+)=(?:"([^"]*)"|([^\s,]+))', raw):
        out[m.group(1).lower()] = m.group(2) if m.group(2) is not None else (m.group(3) or "")
    return out


def digest_response(
    *,
    username: str,
    realm: str,
    password: str,
    method: str,
    uri: str,
    nonce: str,
    qop: str = "",
    nc: str = "",
    cnonce: str = "",
) -> str:
    ha1 = md5_hex(f"{username}:{realm}:{password}")
    ha2 = md5_hex(f"{method}:{uri}")
    if qop:
        return md5_hex(f"{ha1}:{nonce}:{nc}:{cnonce}:{qop}:{ha2}")
    return md5_hex(f"{ha1}:{nonce}:{ha2}")


def verify_digest(
    header: str,
    *,
    username: str,
    realm: str,
    password: str,
    method: str,
    request_uri: str,
    nonce: str,
) -> bool:
    fields = parse_authorization(header)
    if not fields.get("response"):
        return False
    user = fields.get("username") or ""
    if user != username:
        return False
    uri = fields.get("uri") or request_uri
    expect = digest_response(
        username=username,
        realm=fields.get("realm") or realm,
        password=password,
        method=method,
        uri=uri,
        nonce=fields.get("nonce") or nonce,
        qop=fields.get("qop") or "",
        nc=fields.get("nc") or "",
        cnonce=fields.get("cnonce") or "",
    )
    return expect.lower() == fields["response"].lower()
