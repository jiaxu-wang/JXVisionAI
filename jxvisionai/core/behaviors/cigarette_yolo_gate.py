"""可选：香烟小目标检测（专训 YOLO）与人物框关联，用于压低「手靠近脸」所致吸烟误报。

配置见 SMOKING_CIGARETTE_DETECTOR_*。权重需自备（如 Roboflow 等训单类 cigarette 后导出 Ultralytics .pt）。"""

from __future__ import annotations

import logging
import threading
from typing import Any, Dict, List, Optional, Sequence, Tuple

from ultralytics import YOLO

from jxvisionai.config.settings import (
    SMOKING_CIGARETTE_CLASS_IDS,
    SMOKING_CIGARETTE_DETECTOR_CONF,
    SMOKING_CIGARETTE_DETECTOR_PATH,
    yolo_inference_device,
)

logger = logging.getLogger(__name__)

_yolo = None
_load_lock = threading.Lock()
_load_attempted = False
_warned_fail = False


def _parse_class_ids(raw: str) -> Optional[List[int]]:
    """空或全空白 = 不设类过滤（接受全部检出类）。"""
    s = (raw or "").strip()
    if not s:
        return None
    out: List[int] = []
    for p in s.replace("，", ",").split(","):
        p = p.strip()
        if not p:
            continue
        try:
            out.append(int(p))
        except ValueError:
            continue
    return out if out else None


def allowed_class_ids() -> Optional[List[int]]:
    return _parse_class_ids(SMOKING_CIGARETTE_CLASS_IDS)


def ensure_model() -> Optional[Any]:
    global _yolo, _load_attempted, _warned_fail
    path = (SMOKING_CIGARETTE_DETECTOR_PATH or "").strip()
    if not path:
        return None
    if _yolo is not None:
        return _yolo
    with _load_lock:
        if _yolo is not None:
            return _yolo
        if _load_attempted:
            return None
        _load_attempted = True
        try:
            _yolo = YOLO(path)
            logger.info("吸烟专模已加载: %s", path)
        except Exception as ex:  # noqa: BLE001
            if not _warned_fail:
                _warned_fail = True
                logger.warning(
                    "吸烟-香烟门控 YOLO 加载失败，将继续仅使用人物 ViT 二分类（易误报）：%s",
                    ex,
                )
            _yolo = None
    return _yolo


def infer_cigarette_boxes(
    frame_bgr: np.ndarray,
) -> List[Dict[str, Any]]:
    """当前帧检出候选香烟框（原图坐标）。"""
    m = ensure_model()
    if m is None:
        return []

    dev = yolo_inference_device()
    kw: dict[str, Any] = {"conf": SMOKING_CIGARETTE_DETECTOR_CONF, "verbose": False}
    if dev is not None:
        kw["device"] = dev

    cls_ids = allowed_class_ids()
    if cls_ids:
        kw["classes"] = cls_ids

    try:
        results = m(frame_bgr, **kw)
    except Exception as ex:  # noqa: BLE001
        logger.debug("香烟门控 YOLO 推理异常: %s", ex)
        return []

    boxes: List[Dict[str, Any]] = []
    for r in results:
        if r.boxes is None:
            continue
        for box in r.boxes:
            cls = int(box.cls[0])
            if cls_ids is not None and cls not in cls_ids:
                continue
            x1, y1, x2, y2 = map(int, box.xyxy[0].tolist())
            conf = float(box.conf[0])
            boxes.append(
                {
                    "box": (x1, y1, x2, y2),
                    "class_id": cls,
                    "confidence": conf,
                }
            )
    return boxes


def _boxes_intersect_area(
    a: Tuple[int, int, int, int], b: Tuple[int, int, int, int]
) -> int:
    ax1, ay1, ax2, ay2 = a
    bx1, by1, bx2, by2 = b
    ix1, iy1 = max(ax1, bx1), max(ay1, by1)
    ix2, iy2 = min(ax2, bx2), min(ay2, by2)
    if ix1 >= ix2 or iy1 >= iy2:
        return 0
    return (ix2 - ix1) * (iy2 - iy1)


def _cigar_center_in_person(
    person_box: Tuple[int, int, int, int],
    cig_box: Tuple[int, int, int, int],
    margin_ratio: float,
) -> bool:
    px1, py1, px2, py2 = map(float, person_box)
    w, h = px2 - px1, py2 - py1
    mx, my = w * margin_ratio * 0.5, h * margin_ratio * 0.5
    cx = (cig_box[0] + cig_box[2]) * 0.5
    cy = (cig_box[1] + cig_box[3]) * 0.5
    return (px1 - mx) <= cx <= (px2 + mx) and (py1 - my) <= cy <= (py2 + my)


def person_has_overlapping_cigarette(
    person_box: Tuple[int, int, int, int],
    cigarette_detections: Sequence[Dict[str, Any]],
    *,
    margin_ratio: float = 0.08,
) -> bool:
    """人物与任一香烟框有交集，或香烟框中心落在略带边距的人物框内（细目标 IoU 偏小）。"""
    if not cigarette_detections:
        return False
    pb = tuple(int(x) for x in person_box[:4])
    for d in cigarette_detections:
        cb = d.get("box")
        if not cb or len(cb) < 4:
            continue
        b = (int(cb[0]), int(cb[1]), int(cb[2]), int(cb[3]))
        if _boxes_intersect_area(pb, b) > 0:
            return True
        if _cigar_center_in_person(pb, b, margin_ratio):
            return True
    return False


def gate_enabled() -> bool:
    return bool((SMOKING_CIGARETTE_DETECTOR_PATH or "").strip())


def best_overlap_conf(
    person_box: Tuple[int, int, int, int],
    detections: Sequence[Dict[str, Any]],
    *,
    margin_ratio: float = 0.08,
) -> float:
    """人物与检测框有关联时，返回关联框中的最高置信度，否则 0。"""
    if not detections:
        return 0.0
    best = 0.0
    pb = tuple(int(x) for x in person_box[:4])
    for d in detections:
        cb = d.get("box")
        if not cb or len(cb) < 4:
            continue
        b = (int(cb[0]), int(cb[1]), int(cb[2]), int(cb[3]))
        if _boxes_intersect_area(pb, b) <= 0 and not _cigar_center_in_person(pb, b, margin_ratio):
            continue
        best = max(best, float(d.get("confidence", 0.0)))
    return best
