"""把运行时权重准备成 ONNX。导出只发生一次，逐帧推理不走 Ultralytics。"""

from __future__ import annotations

import logging
import os
import threading
from typing import Optional

logger = logging.getLogger(__name__)

_lock = threading.Lock()


def ensure_onnx(path: str, *, imgsz: int = 640) -> Optional[str]:
    """返回可用的 .onnx 路径。``.pt`` 在旁边没有更新的 onnx 时导出一次。"""
    raw = (path or "").strip()
    if not raw:
        return None
    if not os.path.isabs(raw):
        from visionai.config.settings import PROJECT_ROOT

        raw = os.path.join(PROJECT_ROOT, raw)
    raw = os.path.abspath(raw)
    if not os.path.isfile(raw):
        return None
    if raw.lower().endswith(".onnx"):
        return raw
    if not raw.lower().endswith(".pt"):
        logger.warning("推理权重须为 .pt 或 .onnx: %s", raw)
        return None
    onnx_path = os.path.splitext(raw)[0] + ".onnx"
    try:
        pt_m = os.path.getmtime(raw)
    except OSError:
        return None
    if os.path.isfile(onnx_path):
        try:
            if os.path.getmtime(onnx_path) >= pt_m:
                return onnx_path
        except OSError:
            return None
    with _lock:
        if os.path.isfile(onnx_path):
            try:
                if os.path.getmtime(onnx_path) >= pt_m:
                    return onnx_path
            except OSError:
                return None
        try:
            from ultralytics import YOLO

            logger.info("导出 ONNX（仅此一次）: %s", raw)
            YOLO(raw).export(format="onnx", imgsz=int(imgsz))
        except Exception as ex:  # noqa: BLE001
            logger.error("ONNX 导出失败 %s: %s", raw, ex)
            return None
    return onnx_path if os.path.isfile(onnx_path) else None
