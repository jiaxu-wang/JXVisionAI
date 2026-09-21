"""开放集成鉴权：X-Api-Key 与告警截图短时 HMAC token。"""

from __future__ import annotations

import base64
import hashlib
import hmac
from typing import Optional
from urllib.parse import quote

from flask import request


def configured_open_api_key() -> str:
    from visionai.config.settings import OPEN_API_KEY

    return (OPEN_API_KEY or "").strip()


def public_base_url() -> str:
    from visionai.config.settings import PUBLIC_BASE_URL

    return (PUBLIC_BASE_URL or "").strip().rstrip("/")


def request_api_key() -> str:
    return (request.headers.get("X-Api-Key") or "").strip()


def _digest_eq(a: str, b: str) -> bool:
    if not a or not b:
        return False
    try:
        return hmac.compare_digest(a.encode("utf-8"), b.encode("utf-8"))
    except Exception:  # noqa: BLE001
        return False


def api_key_matches(provided: Optional[str]) -> bool:
    expected = configured_open_api_key()
    got = (provided or "").strip()
    if not expected or not got:
        return False
    return _digest_eq(got, expected)


def sign_alert_image_token(detection_id: str) -> str:
    key = configured_open_api_key()
    sid = (detection_id or "").strip()
    if not key or not sid:
        return ""
    digest = hmac.new(key.encode("utf-8"), sid.encode("utf-8"), hashlib.sha256).digest()
    return base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")


def verify_alert_image_token(detection_id: str, token: Optional[str]) -> bool:
    expected = sign_alert_image_token(detection_id)
    got = (token or "").strip()
    if not expected or not got:
        return False
    return _digest_eq(got, expected)


def build_alert_image_url(detection_id: str) -> str:
    """绝对截图地址；未配置 public_base_url 或 api key 时返回空串。"""
    base = public_base_url()
    sid = (detection_id or "").strip()
    token = sign_alert_image_token(sid)
    if not base or not sid or not token:
        return ""
    return f"{base}/api/open/v1/alerts/{quote(sid, safe='')}/image?token={quote(token, safe='')}"
