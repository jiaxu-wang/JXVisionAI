"""告警短录像：检测线程里保留触发前几秒的画面，写成可在页面播放的帧序列。"""

from __future__ import annotations

import struct
import time
from typing import List, Optional, Sequence, Tuple

MAGIC = b"JVCLIP1"
_HEADER = struct.Struct("<fH")
_LEN = struct.Struct("<I")


class FrameRing:
    """按时间丢掉过旧的帧。帧已缩小，避免每路占太多内存。"""

    def __init__(self, seconds: float = 6.0, min_interval: float = 0.25, max_width: int = 640):
        self.seconds = max(0.0, float(seconds))
        self.min_interval = max(0.05, float(min_interval))
        self.max_width = max(160, int(max_width))
        self._items: List[Tuple[float, object]] = []

    def push(self, frame, now: Optional[float] = None) -> None:
        if frame is None or self.seconds <= 0:
            return
        now = time.time() if now is None else float(now)
        if self._items and now - self._items[-1][0] < self.min_interval:
            return
        small = _downscale(frame, self.max_width)
        self._items.append((now, small))
        cutoff = now - self.seconds
        while len(self._items) > 2 and self._items[0][0] < cutoff:
            self._items.pop(0)

    def clear(self) -> None:
        self._items.clear()

    def frames(self):
        return [frame for _, frame in self._items]

    def fps(self) -> float:
        if len(self._items) < 2:
            return 4.0
        span = self._items[-1][0] - self._items[0][0]
        if span <= 0:
            return 4.0
        return max(1.0, min(15.0, (len(self._items) - 1) / span))


def _downscale(frame, max_width: int):
    shape = getattr(frame, "shape", None)
    if not shape or len(shape) < 2:
        return frame
    height, width = int(shape[0]), int(shape[1])
    if width <= max_width or width <= 0:
        return frame
    step = max(1, int(round(width / float(max_width))))
    return frame[::step, ::step]


def normalize_alert_clip_enabled(raw) -> bool:
    """没配过的流默认录像。显式 false / 0 / off 才关闭。"""
    if raw is None:
        return True
    if isinstance(raw, bool):
        return raw
    if isinstance(raw, (int, float)):
        return bool(raw)
    s = str(raw).strip().lower()
    if s in ("0", "false", "no", "off", "disabled"):
        return False
    if s in ("1", "true", "yes", "on", "enabled"):
        return True
    return True


def encode_jclip(jpegs: Sequence[bytes], fps: float) -> bytes:
    body = bytearray(MAGIC)
    body += _HEADER.pack(float(fps), len(jpegs))
    for blob in jpegs:
        raw = bytes(blob)
        body += _LEN.pack(len(raw))
        body += raw
    return bytes(body)


def decode_jclip(blob: bytes):
    if not blob.startswith(MAGIC) or len(blob) < len(MAGIC) + _HEADER.size:
        return None
    fps, count = _HEADER.unpack_from(blob, len(MAGIC))
    off = len(MAGIC) + _HEADER.size
    frames = []
    for _ in range(int(count)):
        if off + _LEN.size > len(blob):
            return None
        (n,) = _LEN.unpack_from(blob, off)
        off += _LEN.size
        if n < 0 or off + n > len(blob):
            return None
        frames.append(blob[off : off + n])
        off += n
    return {"fps": float(fps), "frames": frames}


def write_clip_file(frames, dest_path: str, fps: float) -> bool:
    """把 BGR 帧写成 .jclip。至少两帧才有意义。"""
    if frames is None or len(frames) < 2:
        return False
    try:
        import cv2
    except Exception:  # noqa: BLE001
        return False
    jpegs = []
    for frame in frames:
        ok, buf = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), 70])
        if ok:
            jpegs.append(buf.tobytes())
    if len(jpegs) < 2:
        return False
    data = encode_jclip(jpegs, fps)
    with open(dest_path, "wb") as fh:
        fh.write(data)
    return True
