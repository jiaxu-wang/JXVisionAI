"""应用显示/落库时区（IANA 名，如 Asia/Shanghai、Europe/Berlin、America/New_York）。

优先级见 ``visionai.config.settings.APP_TIMEZONE``；改配置后需重启进程。
"""

from __future__ import annotations

import os
from datetime import datetime
from functools import lru_cache
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


def app_tz_name() -> str:
    try:
        from visionai.config.settings import APP_TIMEZONE

        name = (APP_TIMEZONE or "").strip()
        if name:
            return name
    except Exception:  # noqa: BLE001
        pass
    for key in ("VISIONAI_TIMEZONE", "TIMEZONE", "TZ"):
        v = (os.environ.get(key) or "").strip()
        if v:
            return v
    return "Asia/Shanghai"


@lru_cache(maxsize=8)
def _zoneinfo(name: str) -> ZoneInfo:
    try:
        return ZoneInfo(name)
    except ZoneInfoNotFoundError:
        return ZoneInfo("UTC")


def app_tz() -> ZoneInfo:
    return _zoneinfo(app_tz_name())


def app_now() -> datetime:
    """带配置时区的当前时间；isoformat 含偏移，前端按同一时区展示。"""
    return datetime.now(app_tz())
