"""一次性管理页嵌入票据：对接方用 X-Api-Key 签发，浏览器 /embed?token= 换 Session。"""

from __future__ import annotations

import re
import secrets
import threading
import time
from typing import List
from urllib.parse import quote

EMBED_TOKEN_TTL_SEC = 60
_MEM: dict[str, float] = {}
_MEM_LOCK = threading.Lock()
_ORIGIN_RE = re.compile(r"^https?://[^\s]+$", re.I)


def _redis_client():
    try:
        from visionai.core.redis_manager import redis_manager
    except Exception:  # noqa: BLE001
        return None
    if not redis_manager or not getattr(redis_manager, "is_connected", lambda: False)():
        return None
    return getattr(redis_manager, "_redis_client", None)


def _redis_key(token: str) -> str:
    from visionai.config.settings import REDIS_KEY_PREFIX

    return f"{REDIS_KEY_PREFIX}embed_token:{token}"


def issue_embed_token() -> str:
    token = secrets.token_urlsafe(32)
    client = _redis_client()
    if client is not None:
        client.set(_redis_key(token), "1", ex=EMBED_TOKEN_TTL_SEC)
        return token
    now = time.time()
    with _MEM_LOCK:
        expired = [k for k, exp in _MEM.items() if exp <= now]
        for k in expired:
            _MEM.pop(k, None)
        _MEM[token] = now + EMBED_TOKEN_TTL_SEC
    return token


def consume_embed_token(token: str) -> bool:
    tok = (token or "").strip()
    if not tok:
        return False
    client = _redis_client()
    if client is not None:
        key = _redis_key(tok)
        n = client.delete(key)
        return bool(n)
    now = time.time()
    with _MEM_LOCK:
        exp = _MEM.pop(tok, 0)
    return bool(exp) and exp > now


def parse_frame_ancestors(raw: str) -> List[str]:
    out: List[str] = []
    for part in re.split(r"[\s,]+", raw or ""):
        p = part.strip().rstrip("/")
        if _ORIGIN_RE.match(p) and p not in out:
            out.append(p)
    return out


def configured_frame_ancestors() -> List[str]:
    from visionai.config.settings import EMBED_FRAME_ANCESTORS

    return parse_frame_ancestors(EMBED_FRAME_ANCESTORS or "")


def build_embed_url(token: str, request_host_url: str = "") -> str:
    from visionai.utils.open_api_auth import public_base_url

    tok = (token or "").strip()
    if not tok:
        return ""
    base = public_base_url() or (request_host_url or "").strip().rstrip("/")
    if not base:
        return ""
    return f"{base}/embed?token={quote(tok, safe='')}"
