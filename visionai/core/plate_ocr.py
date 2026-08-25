"""车牌 OCR：裁剪框 → RapidOCR → 规范化车牌号。"""

from __future__ import annotations

import logging
import re
import threading
from typing import Any, List, Optional, Tuple

import cv2
import numpy as np

logger = logging.getLogger(__name__)

# 大陆车牌常见字符（省简称 + 字母数字；不含 I/O 作为正式位，但 OCR 会误出）
_PROVINCE = (
    "京津沪渝冀豫云辽黑湘皖鲁新苏浙赣鄂桂甘晋蒙陕吉闽贵粤青藏川宁琼使领学警港澳"
)
_PLATE_KEEP = re.compile(rf"[^{_PROVINCE}A-Z0-9]")

_engine = None
_engine_lock = threading.Lock()
_engine_failed = False


def normalize_plate_text(raw: str) -> str:
    """去空格/点号，转大写，去掉非法字符；常见易混修正。"""
    s = (raw or "").strip().upper()
    for ch in (" ", "·", ".", "-", "_", "\u3000"):
        s = s.replace(ch, "")
    s = _PLATE_KEEP.sub("", s)
    # 车牌号段中 I→1、O→0（第二位及以后）
    if len(s) >= 3:
        body = []
        for i, c in enumerate(s):
            if i == 0:
                body.append(c)
                continue
            if c == "I":
                body.append("1")
            elif c == "O":
                body.append("0")
            else:
                body.append(c)
        s = "".join(body)
    return s


def is_plausible_plate(text: str) -> bool:
    """粗校验：长度与首字符为省简称。"""
    t = normalize_plate_text(text)
    if len(t) < 7 or len(t) > 10:
        return False
    if t[0] not in _PROVINCE:
        return False
    return True


def _get_engine():
    global _engine, _engine_failed
    if _engine_failed:
        return None
    if _engine is not None:
        return _engine
    with _engine_lock:
        if _engine is not None or _engine_failed:
            return _engine
        try:
            from rapidocr_onnxruntime import RapidOCR

            _engine = RapidOCR()
            logger.info("RapidOCR 车牌读号引擎已加载")
        except Exception as e:  # noqa: BLE001
            _engine_failed = True
            logger.warning("RapidOCR 不可用（请 pip install rapidocr_onnxruntime）: %s", e)
            _engine = None
        return _engine


def is_available() -> bool:
    return _get_engine() is not None


def _expand_box(
    box: List[int],
    frame_shape: Tuple[int, ...],
    *,
    pad_ratio: float = 0.12,
) -> Tuple[int, int, int, int]:
    h, w = int(frame_shape[0]), int(frame_shape[1])
    x1, y1, x2, y2 = [int(v) for v in box[:4]]
    bw = max(1, x2 - x1)
    bh = max(1, y2 - y1)
    px = int(bw * pad_ratio)
    py = int(bh * pad_ratio)
    return (
        max(0, x1 - px),
        max(0, y1 - py),
        min(w, x2 + px),
        min(h, y2 + py),
    )


def recognize_plate_bgr(
    crop_bgr: np.ndarray,
) -> Tuple[str, float]:
    """对裁剪的车牌图做 OCR，返回 (规范化文本, 置信度)。失败返回 ('', 0)。"""
    if crop_bgr is None or getattr(crop_bgr, "size", 0) == 0:
        return "", 0.0
    eng = _get_engine()
    if eng is None:
        return "", 0.0
    try:
        # RapidOCR 接受 BGR/路径；结果 [[box, text, score], ...] 或 (result, elapse)
        result, _ = eng(crop_bgr)
    except Exception as e:  # noqa: BLE001
        logger.debug("OCR 失败: %s", e)
        return "", 0.0
    if not result:
        return "", 0.0

    best_text = ""
    best_score = 0.0
    for item in result:
        try:
            if isinstance(item, (list, tuple)) and len(item) >= 3:
                text = str(item[1] or "")
                score = float(item[2] or 0.0)
            elif isinstance(item, dict):
                text = str(item.get("text") or item.get("transcription") or "")
                score = float(item.get("score") or item.get("confidence") or 0.0)
            else:
                continue
        except (TypeError, ValueError, IndexError):
            continue
        norm = normalize_plate_text(text)
        if not norm:
            continue
        # 优先像车牌的结果
        score_adj = score + (0.15 if is_plausible_plate(norm) else 0.0)
        if score_adj > best_score or (
            abs(score_adj - best_score) < 1e-6 and len(norm) > len(best_text)
        ):
            best_score = score
            best_text = norm

    if not best_text:
        # 拼接所有片段再规范化（竖排/拆字时）
        parts = []
        scores = []
        for item in result:
            try:
                if isinstance(item, (list, tuple)) and len(item) >= 3:
                    parts.append(str(item[1] or ""))
                    scores.append(float(item[2] or 0.0))
            except (TypeError, ValueError, IndexError):
                continue
        best_text = normalize_plate_text("".join(parts))
        best_score = float(sum(scores) / len(scores)) if scores else 0.0

    return best_text, float(best_score)


def recognize_from_frame(
    frame_bgr: np.ndarray,
    box: List[Any],
    *,
    pad_ratio: float = 0.12,
    min_side: int = 16,
) -> Tuple[str, float, List[int]]:
    """从整帧按 box 裁剪并 OCR。返回 (plate_no, conf, used_box)。"""
    if frame_bgr is None or frame_bgr.size == 0 or not box or len(box) < 4:
        return "", 0.0, [0, 0, 0, 0]
    x1, y1, x2, y2 = _expand_box([int(v) for v in box[:4]], frame_bgr.shape, pad_ratio=pad_ratio)
    if x2 - x1 < min_side or y2 - y1 < min_side:
        return "", 0.0, [x1, y1, x2, y2]
    crop = frame_bgr[y1:y2, x1:x2]
    # 过小则放大，利于 OCR
    ch, cw = crop.shape[:2]
    if max(ch, cw) < 80:
        scale = 80.0 / float(max(ch, cw) or 1)
        crop = cv2.resize(
            crop,
            (max(1, int(cw * scale)), max(1, int(ch * scale))),
            interpolation=cv2.INTER_CUBIC,
        )
    text, conf = recognize_plate_bgr(crop)
    return text, conf, [x1, y1, x2, y2]
