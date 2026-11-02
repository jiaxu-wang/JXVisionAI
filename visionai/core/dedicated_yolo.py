"""专训 YOLO 权重（.pt / .onnx）加载与推理，供行为层与场景检测复用。

运行时只走 visionai-inferd。``.pt`` 在首次使用时导出为同名 ``.onnx``。
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np

from visionai.core.weights_onnx import ensure_onnx

logger = logging.getLogger(__name__)


def drop_model(model_path: str) -> None:
    """权重替换后清掉已加载记录，下次推理重新 LoadModel。"""
    path = (model_path or "").strip()
    if not path:
        return
    try:
        from visionai.core import cpp_yolo
        from visionai.core.infer_client import get_infer_client

        onnx_path = ensure_onnx(path)
        if not onnx_path:
            return
        name = cpp_yolo.model_key(onnx_path)
        with cpp_yolo._lock:
            cpp_yolo._loaded.discard(name)
            for sid in list(cpp_yolo._sessions):
                if sid.startswith(name + ":"):
                    cpp_yolo._sessions.discard(sid)
        get_infer_client().unload_model(name)
    except Exception as ex:  # noqa: BLE001
        logger.debug("卸载专模失败 %s: %s", path, ex)


def ensure_model(model_path: str) -> Optional[str]:
    """权重能导出/找到 onnx 时返回路径，否则 None。"""
    return ensure_onnx(model_path)


def infer_detections(
    model_path: str,
    frame_bgr: np.ndarray,
    *,
    conf: float,
    class_ids: Optional[Sequence[int]] = None,
) -> List[Dict[str, Any]]:
    """原图坐标检测框列表。"""
    from visionai.core.cpp_yolo import infer_boxes

    boxes = infer_boxes(model_path, frame_bgr, conf=float(conf), class_ids=class_ids, task="detect")
    out: List[Dict[str, Any]] = []
    for box in boxes:
        out.append(
            {
                "box": box.box,
                "class_id": int(box.class_id),
                "name": box.label or str(box.class_id),
                "confidence": float(box.conf),
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
