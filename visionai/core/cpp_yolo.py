"""YOLO 检测 / 姿态的运行时入口：只调用 visionai-inferd。"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import threading
from typing import List, Optional, Sequence

import numpy as np

from visionai.core.infer_types import DetectionBox
from visionai.core.weights_onnx import ensure_onnx

logger = logging.getLogger(__name__)

_lock = threading.Lock()
_loaded: set[str] = set()
_sessions: set[str] = set()


def model_key(onnx_path: str) -> str:
    digest = hashlib.sha1(os.path.abspath(onnx_path).encode()).hexdigest()[:16]
    return "m_" + digest


def _labels_near(path: str) -> tuple[str, int, int]:
    """返回 (逗号分隔类名, 类别数, imgsz)。找不到元数据时类别数 0。"""
    base = os.path.dirname(os.path.abspath(path))
    for name in ("specialist.json", "model.json"):
        fp = os.path.join(base, name)
        if not os.path.isfile(fp):
            continue
        try:
            with open(fp, encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError):
            continue
        classes = data.get("classes")
        if isinstance(classes, list) and classes:
            names = [str(c).replace(",", " ") for c in classes]
            return ",".join(names), len(names), int(data.get("imgsz") or 640)
        raw = str(data.get("labels") or "").strip()
        nc = int(data.get("num_classes") or 0)
        imgsz = int(data.get("imgsz") or 640)
        if raw and raw != "coco80":
            return raw, nc, imgsz
        if nc:
            return "", nc, imgsz
    return "", 0, 640


def infer_boxes(
    weights_path: str,
    frame_bgr: np.ndarray,
    *,
    conf: float,
    class_ids: Optional[Sequence[int]] = None,
    task: str = "detect",
    num_classes: int = 0,
    imgsz: int = 640,
    labels: str = "",
) -> List[DetectionBox]:
    if frame_bgr is None or getattr(frame_bgr, "size", 0) == 0:
        return []
    onnx_path = ensure_onnx(weights_path, imgsz=imgsz)
    if not onnx_path:
        return []
    near_labels, near_nc, near_imgsz = _labels_near(weights_path)
    if not near_labels:
        near_labels, near_nc2, near_imgsz2 = _labels_near(onnx_path)
        if not near_nc:
            near_nc = near_nc2
        if near_imgsz2:
            near_imgsz = near_imgsz2
    use_labels = labels or near_labels
    use_nc = num_classes or near_nc or (1 if task == "pose" else 80)
    use_imgsz = imgsz or near_imgsz or 640
    name = model_key(onnx_path)
    session_id = f"{name}:{float(conf):.3f}:{int(use_imgsz)}"
    try:
        from visionai.core.infer_client import get_infer_client

        client = get_infer_client()
        with _lock:
            if name not in _loaded:
                client.load_model(
                    name,
                    onnx_path,
                    task=task,
                    num_classes=use_nc,
                    imgsz=use_imgsz,
                    labels=use_labels,
                )
                _loaded.add(name)
            if session_id not in _sessions:
                client.open_session(
                    session_id,
                    model_name=name,
                    conf=float(conf),
                    imgsz=int(use_imgsz),
                )
                _sessions.add(session_id)
        result = client.infer(session_id, frame_bgr)
    except Exception as ex:  # noqa: BLE001
        logger.warning("C++ 推理失败 %s: %s", weights_path, ex)
        return []
    if not result.ok:
        logger.warning("C++ 推理失败 %s: %s %s", weights_path, result.error_code, result.message)
        return []
    if not class_ids:
        return result.boxes
    allow = {int(x) for x in class_ids}
    return [b for b in result.boxes if int(b.class_id) in allow]
