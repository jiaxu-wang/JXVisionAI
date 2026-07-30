"""在 OpenCV 帧上绘制检测标注（统一字号，不随检测框大小变化）。"""

from __future__ import annotations

import logging
from functools import lru_cache
from typing import Optional, Sequence, Tuple

import cv2
import numpy as np

logger = logging.getLogger(__name__)

# 优先中文字体；WSL 可回退到 Windows Fonts。DejaVu 无中文，仅作最后兜底。
_FONT_CANDIDATES = (
    # Linux 常见 CJK
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/noto/NotoSansCJK-Bold.ttc",
    "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
    "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
    "/usr/share/fonts/truetype/arphic/ukai.ttc",
    "/usr/share/fonts/truetype/arphic/uming.ttc",
    "/usr/share/fonts/truetype/droid/DroidSansFallbackFull.ttf",
    # WSL / 本机 Windows 中文字体
    "/mnt/c/Windows/Fonts/msyhbd.ttc",
    "/mnt/c/Windows/Fonts/msyh.ttc",
    "/mnt/c/Windows/Fonts/simhei.ttf",
    "/mnt/c/Windows/Fonts/simsun.ttc",
    "/mnt/c/Windows/Fonts/Dengb.ttf",
    "/mnt/c/Windows/Fonts/Deng.ttf",
    "/mnt/c/Windows/Fonts/NotoSansSC-VF.ttf",
    # 无中文：仅兜底英文/数字
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
)

_CJK_PROBE = "中"

# 全帧统一字号默认值（可被 config [preview] 覆盖，见 settings.LABEL_FONT_*）
_DEFAULT_LABEL_RATIO = 0.05
_DEFAULT_MIN_FONT_PX = 36
_DEFAULT_MAX_FONT_PX = 72
_ABS_MIN_FONT_PX = 8
_ABS_MAX_FONT_PX = 128

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
    """本帧所有标注共用的像素字高（只看整帧分辨率 / 配置，不看框大小）。

    - ``label_font_px > 0``：固定字号
    - 否则：短边 × ratio，再夹在 min~max
    """
    lo, hi, ratio, fixed = _font_limits()
    if fixed > 0:
        return _clamp_font_px(fixed)
    if frame is None or getattr(frame, "size", 0) == 0:
        return lo
    h, w = frame.shape[:2]
    short = float(min(h, w) or 720.0)
    return int(max(lo, min(hi, round(short * ratio))))


def _font_supports_cjk(font) -> bool:
    """粗判字体是否能画出中文（避免 DejaVu 等显示成方块）。"""
    try:
        from PIL import Image, ImageDraw

        img = Image.new("L", (64, 64), 0)
        draw = ImageDraw.Draw(img)
        draw.text((2, 2), _CJK_PROBE, font=font, fill=255)
        return bool(np.asarray(img).max() > 0)
    except Exception:  # noqa: BLE001
        return False


@lru_cache(maxsize=16)
def _load_font(size: int):
    global _warned_no_cjk
    try:
        from PIL import ImageFont
    except ImportError:
        return None

    latin_fallback = None
    for path in _FONT_CANDIDATES:
        try:
            font = ImageFont.truetype(path, size=size)
        except OSError:
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
                "未找到中文字体，姓名等中文标签将显示为方块。"
                "请安装 fonts-wqy-microhei / fonts-noto-cjk，"
                "或在 WSL 下确保可访问 /mnt/c/Windows/Fonts/msyh.ttc"
            )
        return latin_fallback

    try:
        return ImageFont.load_default()
    except Exception:  # noqa: BLE001
        return None


def label_font_scale(frame: Optional[np.ndarray], *, base: float = 0.0) -> float:
    """兼容旧调用；实际绘制以 label_font_px 为准，不再用 OpenCV fontScale。"""
    del base
    # 返回值仅占位；draw/put_text 内部一律用像素字高
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
    del font_scale, thickness  # 废弃参数，避免各处传入导致不一致
    if frame is None or frame.size == 0 or not text:
        return

    px = _clamp_font_px(int(font_px) if font_px is not None else label_font_px(frame))
    font = _load_font(px)
    x, y_anchor = int(org[0]), int(org[1])

    try:
        from PIL import Image, ImageDraw
    except ImportError:
        # 极端回退：仍用固定 scale，不用框尺寸
        scale = px / 22.0
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

    # org 约定为「文字底边附近」；转成 PIL 顶边
    ty = max(0, y_anchor - px)
    tx = max(0, x)
    color_rgb = (int(color_bgr[2]), int(color_bgr[1]), int(color_bgr[0]))

    rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    pil_img = Image.fromarray(rgb)
    draw = ImageDraw.Draw(pil_img)

    try:
        bbox = draw.textbbox((tx, ty), text, font=font)
    except Exception:  # noqa: BLE001
        bbox = (tx, ty, tx + px * len(text), ty + px)

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
    # 线宽也固定按字号，不按框大小
    box_thick = 3 if px >= 48 else 2
    cv2.rectangle(frame, (x1, y1), (x2, y2), color_bgr, box_thick)

    # 优先框上方；贴顶则放到框内顶部 —— 只改位置，不改字号
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
