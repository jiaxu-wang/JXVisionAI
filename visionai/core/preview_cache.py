"""检测线程写入、/api/preview 读取：避免预览与 Detector 处理结果不一致。"""

from __future__ import annotations

import threading
import time
from typing import Optional

_lock = threading.Lock()
_jpeg_by_stream: dict[str, tuple[bytes, float]] = {}


def set_preview_jpeg(stream_id: str, jpeg_bytes: bytes) -> None:
    if not stream_id or not jpeg_bytes:
        return
    with _lock:
        _jpeg_by_stream[stream_id] = (jpeg_bytes, time.monotonic())


def get_preview_jpeg(stream_id: str) -> Optional[bytes]:
    with _lock:
        row = _jpeg_by_stream.get(stream_id)
        if not row:
            return None
        return row[0]


def get_preview_jpeg_meta(stream_id: str) -> Optional[tuple[bytes, float]]:
    """返回 (jpeg_bytes, monotonic_ts)，用于 WebSocket 仅在帧更新时推送。"""
    with _lock:
        row = _jpeg_by_stream.get(stream_id)
        if not row:
            return None
        return row[0], row[1]


def preview_age_sec(stream_id: str) -> Optional[float]:
    with _lock:
        row = _jpeg_by_stream.get(stream_id)
        if not row:
            return None
        return time.monotonic() - row[1]
