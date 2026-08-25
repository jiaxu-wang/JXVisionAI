"""在 OpenCV 帧上绘制检测标注（统一字号，不随检测框大小变化）。"""

from __future__ import annotations

import logging
import os
from functools import lru_cache
from typing import Optional, Sequence, Tuple

import cv2
import numpy as np

logger = logging.getLogger(__name__)

_PKG_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_BUNDLED_FONT = os.path.join(_PKG_DIR, "assets", "fonts", "wqy-microhei.ttc")

# 优先：包内字体 → 系统 / Windows（WSL）CJK → Latin 兜底
_FONT_CANDIDATES = (
    _BUNDLED_FONT,
    "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
    "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/noto/NotoSansCJK-Bold.ttc",
    "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/arphic/uming.ttc",
    "/usr/share/fonts/truetype/droid/DroidSansFallbackFull.ttf",
    "/mnt/c/Windows/Fonts/msyhbd.ttc",
    "/mnt/c/Windows/Fonts/msyh.ttc",
    "/mnt/c/Windows/Fonts/simhei.ttf",
    "/mnt/c/Windows/Fonts/simsun.ttc",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
)

_CJK_PROBE = "中"

_DEFAULT_LABEL_RATIO = 0.055
_DEFAULT_MIN_FONT_PX = 40
_DEFAULT_MAX_FONT_PX = 96
_ABS_MIN_FONT_PX = 12
_ABS_MAX_FONT_PX = 160

_warned_no_cjk = False


def _font_limits() -> tuple[int, int, float, int]:
    """返回 (min_px, max_px, ratio, fixed_px)。fixed_px>0 表示固定字号。"""
    try:
        from visionai.config.settings import (
            LABEL_FONT_MAX_PX,
            LABEL_FONT_MIN_PX,
            LABEL_FONT_PX,
            LABEL_FONT_RATIO,
        )

        fixed = int(LABEL_FONT_PX or 0)
        lo = max(_ABS_MIN_FONT_PX, int(LABEL_FONT_MIN_PX))
        hi = max(lo, int(LABEL_FONT_MAX_PX))
        ratio = float(LABEL_FONT_RATIO)
        return lo, hi, ratio, fixed
    except Exception:  # noqa: BLE001
        return (
            _DEFAULT_MIN_FONT_PX,
            _DEFAULT_MAX_FONT_PX,
            _DEFAULT_LABEL_RATIO,
            0,
        )


def _clamp_font_px(px: int) -> int:
    return int(max(_ABS_MIN_FONT_PX, min(_ABS_MAX_FONT_PX, px)))


def label_font_px(frame: Optional[np.ndarray]) -> int:
    """本帧所有标注共用的像素字高（只看整帧分辨率 / 配置，不看框大小）。"""
    lo, hi, ratio, fixed = _font_limits()
    if fixed > 0:
        return _clamp_font_px(fixed)
    if frame is None or getattr(frame, "size", 0) == 0:
        return lo
    h, w = frame.shape[:2]
    short = float(min(h, w) or 720.0)
    return int(max(lo, min(hi, round(short * ratio))))


def _font_supports_cjk(font) -> bool:
    try:
        from PIL import Image, ImageDraw

        img = Image.new("L", (64, 64), 0)
        draw = ImageDraw.Draw(img)
        draw.text((2, 2), _CJK_PROBE, font=font, fill=255)
        return bool(np.asarray(img).max() > 0)
    except Exception:  # noqa: BLE001
        return False


def _try_truetype(path: str, size: int):
    from PIL import ImageFont

    last_err = None
    # .ttc 需指定 face index；部分字体 index=0 即 CJK
    for index in (0, 1):
        try:
            return ImageFont.truetype(path, size=size, index=index)
        except OSError as e:
            last_err = e
            continue
        except Exception as e:  # noqa: BLE001
            last_err = e
            break
    try:
        return ImageFont.truetype(path, size=size)
    except Exception:  # noqa: BLE001
        if last_err:
            logger.debug("load font %s failed: %s", path, last_err)
        return None


@lru_cache(maxsize=32)
def _load_font(size: int):
    global _warned_no_cjk
    try:
        from PIL import ImageFont
    except ImportError:
        return None

    latin_fallback = None
    for path in _FONT_CANDIDATES:
        if not path or not os.path.isfile(path):
            continue
        font = _try_truetype(path, size)
        if font is None:
            continue
        if _font_supports_cjk(font):
            logger.debug("frame_draw: using CJK font %s size=%s", path, size)
            return font
        if latin_fallback is None:
            latin_fallback = font

    if latin_fallback is not None:
        if not _warned_no_cjk:
            _warned_no_cjk = True
            logger.warning(
                "未找到中文字体，中文标签将乱码/方块。"
                "镜像请装 fonts-wqy-microhei，或确保 visionai/assets/fonts/wqy-microhei.ttc 存在"
            )
        return latin_fallback

    try:
        return ImageFont.load_default()
    except Exception:  # noqa: BLE001
        return None


def label_font_scale(frame: Optional[np.ndarray], *, base: float = 0.0) -> float:
    del base
    return label_font_px(frame) / 22.0


def put_text(
    frame: np.ndarray,
    text: str,
    org: Tuple[int, int],
    color_bgr: Tuple[int, int, int],
    *,
    font_scale: Optional[float] = None,
    thickness: Optional[int] = None,
    with_bg: bool = True,
    font_px: Optional[int] = None,
) -> None:
    """绘制文字：中英文同一套 PIL 字体与字号，字号与检测框无关。"""
    del font_scale, thickness
    if frame is None or frame.size == 0 or not text:
        return

    px = _clamp_font_px(int(font_px) if font_px is not None else label_font_px(frame))
    font = _load_font(px)
    x, y_anchor = int(org[0]), int(org[1])

    try:
        from PIL import Image, ImageDraw
    except ImportError:
        scale = max(0.6, px / 22.0)
        thick = 3 if px >= 48 else 2
        y = max(y_anchor, px + 8)
        cv2.putText(
            frame,
            text,
            (x, y),
            cv2.FONT_HERSHEY_SIMPLEX,
            scale,
            color_bgr,
            thick,
            lineType=cv2.LINE_AA,
        )
        return

    if font is None:
        return

    ty = max(0, y_anchor - px)
    tx = max(0, x)
    color_rgb = (int(color_bgr[2]), int(color_bgr[1]), int(color_bgr[0]))

    rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    pil_img = Image.fromarray(rgb)
    draw = ImageDraw.Draw(pil_img)

    try:
        bbox = draw.textbbox((tx, ty), text, font=font)
    except Exception:  # noqa: BLE001
        bbox = (tx, ty, tx + px * max(1, len(text)), ty + px)

    if with_bg:
        pad = max(4, px // 8)
        bg = [
            max(0, bbox[0] - pad),
            max(0, bbox[1] - pad),
            min(pil_img.width, bbox[2] + pad),
            min(pil_img.height, bbox[3] + pad),
        ]
        draw.rectangle(bg, fill=(16, 16, 16))

    for dx, dy in ((-2, 0), (2, 0), (0, -2), (0, 2)):
        draw.text((tx + dx, ty + dy), text, font=font, fill=(0, 0, 0))
    draw.text((tx, ty), text, font=font, fill=color_rgb)
    frame[:] = cv2.cvtColor(np.asarray(pil_img), cv2.COLOR_RGB2BGR)


def draw_labeled_box(
    frame: np.ndarray,
    box: Sequence[float],
    label: str,
    color_bgr: Tuple[int, int, int],
    *,
    font_scale: Optional[float] = None,
    font_px: Optional[int] = None,
) -> None:
    """画框 + 标签。标签字号仅由整帧 font_px 决定，与 box 宽高无关。"""
    del font_scale
    if not box or len(box) < 4:
        return
    px = int(font_px) if font_px is not None else label_font_px(frame)
    px = _clamp_font_px(px)
    x1, y1, x2, y2 = map(int, box[:4])
    box_thick = 3 if px >= 48 else 2
    cv2.rectangle(frame, (x1, y1), (x2, y2), color_bgr, box_thick)

    baseline_y = y1 - 8
    if baseline_y < px + 6:
        baseline_y = min(y1 + px + 10, frame.shape[0] - 4)
    put_text(
        frame,
        label,
        (x1, baseline_y),
        color_bgr,
        font_px=px,
        with_bg=True,
    )
