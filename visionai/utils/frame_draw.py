"""在 OpenCV 帧上绘制文字（含中文，PIL 回退）。"""

from __future__ import annotations

import logging
from functools import lru_cache
from typing import Optional, Tuple

import cv2
import numpy as np

logger = logging.getLogger(__name__)

_FONT_CANDIDATES = (
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
    "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
    "/usr/share/fonts/truetype/arphic/ukai.ttc",
    "/usr/share/fonts/truetype/arphic/uming.ttc",
)


def _needs_unicode(text: str) -> bool:
    return any(ord(ch) > 127 for ch in text)


@lru_cache(maxsize=8)
def _load_font(size: int):
    try:
        from PIL import ImageFont
    except ImportError:
        return None
    for path in _FONT_CANDIDATES:
        try:
            return ImageFont.truetype(path, size=size)
        except OSError:
            continue
    try:
        return ImageFont.load_default()
    except Exception:  # noqa: BLE001
        return None


def put_text(
    frame: np.ndarray,
    text: str,
    org: Tuple[int, int],
    color_bgr: Tuple[int, int, int],
    *,
    font_scale: float = 0.55,
    thickness: int = 2,
) -> None:
    """在 BGR 图像上绘制文字；含中文时用 PIL + 系统中文字体。"""
    if frame is None or frame.size == 0 or not text:
        return
    x, y = int(org[0]), int(org[1])
    if not _needs_unicode(text):
        cv2.putText(
            frame,
            text,
            (x, y),
            cv2.FONT_HERSHEY_SIMPLEX,
            font_scale,
            color_bgr,
            thickness,
        )
        return

    try:
        from PIL import Image, ImageDraw
    except ImportError:
        ascii_text = "".join(ch if ord(ch) < 128 else "?" for ch in text)
        cv2.putText(
            frame,
            ascii_text,
            (x, y),
            cv2.FONT_HERSHEY_SIMPLEX,
            font_scale,
            color_bgr,
            thickness,
        )
        return

    font_size = max(14, int(font_scale * 30))
    font = _load_font(font_size)
    if font is None:
        return

    rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    pil_img = Image.fromarray(rgb)
    draw = ImageDraw.Draw(pil_img)
    color_rgb = (int(color_bgr[2]), int(color_bgr[1]), int(color_bgr[0]))
    draw.text((x, max(y - font_size, 0)), text, font=font, fill=color_rgb)
    frame[:] = cv2.cvtColor(np.asarray(pil_img), cv2.COLOR_RGB2BGR)


def draw_labeled_box(
    frame: np.ndarray,
    box,
    label: str,
    color_bgr: Tuple[int, int, int],
    *,
    font_scale: float = 0.55,
) -> None:
    if not box or len(box) < 4:
        return
    x1, y1, x2, y2 = map(int, box[:4])
    cv2.rectangle(frame, (x1, y1), (x2, y2), color_bgr, 2)
    put_text(
        frame,
        label,
        (x1, max(y1 - 8, 16)),
        color_bgr,
        font_scale=font_scale,
    )
