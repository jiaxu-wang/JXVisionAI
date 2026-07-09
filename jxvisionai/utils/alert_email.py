"""告警邮件：全局 SMTP（settings）+ 每路流收件人列表；异步发送以免阻塞检测线程。"""

from __future__ import annotations

import logging
import re
import smtplib
import ssl
import threading
from datetime import datetime
from email.header import Header
from email.mime.image import MIMEImage
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Any, List, Optional, Sequence

from jxvisionai.config.settings import (
    SMTP_ALERT_ATTACH_MAX_BYTES,
    SMTP_ALERT_ENABLED,
    SMTP_FROM,
    SMTP_HOST,
    SMTP_PASSWORD,
    SMTP_PORT,
    SMTP_TIMEOUT,
    SMTP_USE_SSL,
    SMTP_USE_TLS,
    SMTP_USER,
)

logger = logging.getLogger(__name__)

_EMAIL_RE = re.compile(
    r"^[a-zA-Z0-9.!#$%&'*+/=?^_`{|}~-]+@[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?"
    r"(?:\.[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?)+$"
)


def normalize_stream_alert_email_enabled(raw: Any) -> bool:
    """每路流是否外发告警邮件；缺省为开启，与历史配置兼容。"""
    if raw is None:
        return True
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
        return True
    return True


def normalize_stream_alert_emails(raw: Any) -> List[str]:
    """将前端 / Redis 中的字段规范为去重后的有效邮箱列表。"""
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
    for addr in candidates:
        key = addr.lower()
        if key in seen:
            continue
        if _EMAIL_RE.match(addr):
            seen.add(key)
            out.append(addr)
        else:
            logger.warning("忽略无效告警邮箱地址: %s", addr[:80])
    return out


def smtp_is_configured() -> bool:
    return bool(SMTP_ALERT_ENABLED and SMTP_HOST and SMTP_FROM)


def _build_message(
    stream_name: str,
    detection_types: Sequence[str],
    ts: datetime,
    image_path: Optional[str],
) -> MIMEMultipart:
    msg = MIMEMultipart()
    msg["From"] = SMTP_FROM
    subject = f"JXVisionAI 告警 | {stream_name} | {', '.join(detection_types)}"
    msg["Subject"] = Header(subject, "utf-8")

    lines = [
        f"视频流: {stream_name}",
        f"时间: {ts.isoformat(timespec='seconds')}",
        f"类型: {', '.join(detection_types)}",
        "",
        "（本邮件由 JXVisionAI 自动发送）",
    ]
    body = "\n".join(lines)
    msg.attach(MIMEText(body, "plain", "utf-8"))

    if image_path:
        try:
            import os

            if os.path.isfile(image_path):
                size = os.path.getsize(image_path)
                if size <= SMTP_ALERT_ATTACH_MAX_BYTES:
                    with open(image_path, "rb") as f:
                        img_data = f.read()
                    part = MIMEImage(img_data, _subtype="jpeg")
                    part.add_header(
                        "Content-Disposition",
                        "attachment",
                        filename=os.path.basename(image_path),
                    )
                    msg.attach(part)
        except OSError as e:
            logger.warning("告警邮件跳过附件（读取失败）: %s", e)

    return msg


def _send_sync(
    recipients: List[str],
    stream_name: str,
    detection_types: Sequence[str],
    ts: datetime,
    image_path: Optional[str],
) -> None:
    if not recipients or not smtp_is_configured():
        return
    msg = _build_message(stream_name, detection_types, ts, image_path)
    msg["To"] = ", ".join(recipients)

    try:
        tls_ctx = ssl.create_default_context()
        if SMTP_USE_SSL:
            server = smtplib.SMTP_SSL(
                SMTP_HOST,
                SMTP_PORT,
                timeout=SMTP_TIMEOUT,
                context=tls_ctx,
            )
        else:
            server = smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=SMTP_TIMEOUT)
        try:
            if SMTP_USE_TLS and not SMTP_USE_SSL:
                server.starttls(context=tls_ctx)
            if SMTP_USER:
                server.login(SMTP_USER, SMTP_PASSWORD or "")
            server.sendmail(SMTP_FROM, recipients, msg.as_string())
        finally:
            try:
                server.quit()
            except Exception:
                pass
        logger.info(
            "告警邮件已发送: stream=%s recipients=%s", stream_name, recipients
        )
    except Exception as e:
        logger.error(
            "告警邮件发送失败 [%s]: %s", stream_name, e, exc_info=True
        )


def notify_alert_by_email(
    stream_name: str,
    recipients: Sequence[str],
    detection_types: Sequence[str],
    image_path: Optional[str],
    timestamp: datetime,
) -> None:
    """在后台线程发送邮件（multipart + 可选截图）。"""
    if not recipients or not smtp_is_configured():
        return
    to = list(recipients)
    thread = threading.Thread(
        target=_send_sync,
        args=(to, stream_name, detection_types, timestamp, image_path),
        name=f"alert-email-{stream_name}",
        daemon=True,
    )
    thread.start()
