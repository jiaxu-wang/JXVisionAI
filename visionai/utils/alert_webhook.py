"""告警 WebHook：按路配置多个回调 URL，异步 POST JSON，不阻塞检测线程。"""

from __future__ import annotations

import json
import logging
import re
import threading
import urllib.error
import urllib.request
from datetime import datetime
from typing import Any, Dict, List, Optional, Sequence
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

_MAX_URL_LEN = 2048
_DEFAULT_TIMEOUT_SEC = 15.0


def normalize_stream_alert_webhook_enabled(raw: Any) -> bool:
    """每路流是否外发告警 Webhook；缺省关闭。"""
    if raw is None:
        return False
    if isinstance(raw, bool):
        return raw
    if isinstance(raw, (int, float)):
        return bool(raw)
    if isinstance(raw, str):
        s = raw.strip().lower()
        if s in ("0", "false", "no", "off", ""):
            return False
        if s in ("1", "true", "yes", "on"):
            return True
        return False
    return False


def _valid_http_url(url: str) -> bool:
    if not url or len(url) > _MAX_URL_LEN:
        return False
    try:
        p = urlparse(url)
        if p.scheme not in ("http", "https"):
            return False
        if not p.netloc:
            return False
        return True
    except Exception:
        return False


def normalize_stream_webhook_urls(raw: Any) -> List[str]:
    """规范为去重后的有效 HTTP(S) URL 列表。"""
    if raw is None:
        return []
    if isinstance(raw, str):
        parts = re.split(r"[\s,;，]+", raw)
        candidates = [p.strip() for p in parts if p.strip()]
    elif isinstance(raw, list):
        candidates = []
        for x in raw:
            if isinstance(x, str) and x.strip():
                candidates.append(x.strip())
    else:
        return []

    seen: set[str] = set()
    out: List[str] = []
    for u in candidates:
        if u in seen:
            continue
        if _valid_http_url(u):
            seen.add(u)
            out.append(u)
        else:
            logger.warning("忽略无效告警 Webhook URL: %s", u[:120])
    return out


def _post_one(url: str, payload: Dict[str, Any], timeout: float) -> None:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        headers={
            "Content-Type": "application/json; charset=utf-8",
            "User-Agent": "VisionAI-Webhook/1.0",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        resp.read(4096)


def _send_webhooks_sync(
    urls: List[str],
    payload: Dict[str, Any],
    stream_name: str,
    timeout: float,
) -> None:
    for url in urls:
        try:
            _post_one(url, payload, timeout)
            logger.info("告警 Webhook 已投递: stream=%s url=%s", stream_name, url[:160])
        except urllib.error.HTTPError as e:
            logger.error(
                "告警 Webhook HTTP 失败 stream=%s url=%s status=%s",
                stream_name,
                url[:120],
                e.code,
                exc_info=True,
            )
        except Exception as e:
            logger.error(
                "告警 Webhook 投递失败 stream=%s url=%s: %s",
                stream_name,
                url[:120],
                e,
                exc_info=True,
            )


def notify_alert_by_webhooks(
    stream_name: str,
    stream_id: Optional[str],
    webhook_urls: Sequence[str],
    detection_types: Sequence[str],
    image_path: Optional[str],
    object_key: Optional[str],
    storage_kind: Optional[str],
    detection_id: str,
    timestamp: datetime,
) -> None:
    """后台线程对每个 URL POST 一次 JSON。"""
    urls = list(webhook_urls)
    if not urls:
        return
    payload = {
        "event": "visionai.alert",
        "stream_name": stream_name,
        "stream_id": stream_id or "",
        "detection_id": detection_id,
        "detection_types": list(detection_types),
        "timestamp": timestamp.isoformat(timespec="seconds"),
        "image_path": image_path or "",
        "object_key": object_key or "",
        "storage_kind": storage_kind or "",
    }
    thread = threading.Thread(
        target=_send_webhooks_sync,
        args=(urls, payload, stream_name, _DEFAULT_TIMEOUT_SEC),
        name=f"alert-webhook-{stream_name}",
        daemon=True,
    )
    thread.start()
