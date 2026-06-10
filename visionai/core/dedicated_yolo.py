"""专训 YOLO 权重（.pt / .onnx）加载与推理，供行为层与场景检测复用。"""

from __future__ import annotations

import logging
import threading
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np
from ultralytics import YOLO

from visionai.config.settings import yolo_inference_device

logger = logging.getLogger(__name__)

_load_lock = threading.Lock()
_models: Dict[str, YOLO] = {}
_failed: set[str] = set()


def _resolve_path(path: str) -> str:
    return (path or "").strip()


def ensure_model(model_path: str) -> Optional[YOLO]:
    path = _resolve_path(model_path)
    if not path:
        return None
    if path in _models:
        return _models[path]
    if path in _failed:
        return None
    with _load_lock:
        if path in _models:
            return _models[path]
        if path in _failed:
            return None
        try:
            m = YOLO(path)
            _models[path] = m
            logger.info("专模 YOLO 已加载: %s names=%s", path, getattr(m, "names", {}))
        except Exception as ex:  # noqa: BLE001
            _failed.add(path)
            logger.warning("专模 YOLO 加载失败 %s: %s", path, ex)
            return None
    return _models.get(path)


def infer_detections(
    model_path: str,
    frame_bgr: np.ndarray,
    *,
    conf: float,
    class_ids: Optional[Sequence[int]] = None,
) -> List[Dict[str, Any]]:
    """原图坐标检测框列表。"""
    m = ensure_model(model_path)
    if m is None or frame_bgr is None or frame_bgr.size == 0:
        return []

    dev = yolo_inference_device()
    kw: Dict[str, Any] = {"conf": conf, "verbose": False}
    if dev is not None:
        kw["device"] = dev
    if class_ids:
        kw["classes"] = list(class_ids)

    try:
        results = m(frame_bgr, **kw)
    except Exception as ex:  # noqa: BLE001
        logger.debug("专模推理异常 %s: %s", model_path, ex)
        return []

    names = getattr(m, "names", {}) or {}
    out: List[Dict[str, Any]] = []
    for r in results:
        if r.boxes is None:
            continue
        for box in r.boxes:
            cls = int(box.cls[0])
            if class_ids is not None and cls not in class_ids:
                continue
            x1, y1, x2, y2 = map(int, box.xyxy[0].tolist())
            out.append(
                {
                    "box": (x1, y1, x2, y2),
                    "class_id": cls,
                    "name": str(names.get(cls, cls)),
                    "confidence": float(box.conf[0]),
                }
            )
    return out


def boxes_intersect_area(
    a: Tuple[int, int, int, int], b: Tuple[int, int, int, int]
) -> int:
    ax1, ay1, ax2, ay2 = a
    bx1, by1, bx2, by2 = b
    ix1, iy1 = max(ax1, bx1), max(ay1, by1)
    ix2, iy2 = min(ax2, bx2), min(ay2, by2)
    if ix1 >= ix2 or iy1 >= iy2:
        return 0
    return (ix2 - ix1) * (iy2 - iy1)


def center_in_box(
    inner: Tuple[int, int, int, int],
    outer: Tuple[int, int, int, int],
    *,
    margin_ratio: float = 0.08,
) -> bool:
    ox1, oy1, ox2, oy2 = map(float, outer)
    w, h = ox2 - ox1, oy2 - oy1
    mx, my = w * margin_ratio * 0.5, h * margin_ratio * 0.5
    cx = (inner[0] + inner[2]) * 0.5
    cy = (inner[1] + inner[3]) * 0.5
    return (ox1 - mx) <= cx <= (ox2 + mx) and (oy1 - my) <= cy <= (oy2 + my)


def boxes_associated(
    a: Tuple[int, int, int, int],
    b: Tuple[int, int, int, int],
    *,
    margin_ratio: float = 0.08,
) -> bool:
    bb = (int(b[0]), int(b[1]), int(b[2]), int(b[3]))
    aa = (int(a[0]), int(a[1]), int(a[2]), int(a[3]))
    if boxes_intersect_area(aa, bb) > 0:
        return True
    return center_in_box(bb, aa, margin_ratio=margin_ratio) or center_in_box(
        aa, bb, margin_ratio=margin_ratio
    )


def best_overlap_conf(
    anchor_box: Tuple[int, int, int, int],
    detections: Sequence[Dict[str, Any]],
    *,
    class_ids: Optional[Sequence[int]] = None,
    margin_ratio: float = 0.08,
) -> float:
    best = 0.0
    ab = tuple(int(x) for x in anchor_box[:4])
    for d in detections:
        if class_ids is not None and int(d.get("class_id", -1)) not in class_ids:
            continue
        cb = d.get("box")
        if not cb or len(cb) < 4:
            continue
        b = (int(cb[0]), int(cb[1]), int(cb[2]), int(cb[3]))
        if not boxes_associated(ab, b, margin_ratio=margin_ratio):
            continue
        best = max(best, float(d.get("confidence", 0.0)))
    return best


def filter_class(detections: Sequence[Dict[str, Any]], class_ids: Sequence[int]) -> List[Dict[str, Any]]:
    want = set(int(x) for x in class_ids)
    return [d for d in detections if int(d.get("class_id", -1)) in want]
