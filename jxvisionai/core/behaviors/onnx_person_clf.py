"""ONNX 图像分类：人物裁剪 + ImageNet 归一化；供吸烟等行为复用。"""

from __future__ import annotations

import threading
from typing import Any, List, Optional, Sequence, Tuple

import cv2
import numpy as np

from jxvisionai.config.settings import onnx_runtime_providers_ordered

_ort = None
try:
    import onnxruntime as _ort  # type: ignore
except ImportError:
    pass

_session_lock = threading.Lock()
_session_path: Optional[str] = None
_session: Any = None
_input_name: Optional[str] = None
_input_shape: Optional[Tuple[int, ...]] = None  # NCHW with possible dynamic dim


def ort_available() -> bool:
    return _ort is not None


def load_session(model_path: str) -> bool:
    global _session_path, _session, _input_name, _input_shape
    if not model_path or not ort_available():
        return False
    with _session_lock:
        if _session is not None and _session_path == model_path:
            return True
        try:
            so = _ort.SessionOptions()
            so.graph_optimization_level = _ort.GraphOptimizationLevel.ORT_ENABLE_ALL
            plist = onnx_runtime_providers_ordered()
            sess = _ort.InferenceSession(
                model_path,
                sess_options=so,
                providers=list(plist),
            )
        except Exception:
            _session = None
            _session_path = None
            _input_name = None
            _input_shape = None
            return False
        _session = sess
        _session_path = model_path
        inp = sess.get_inputs()[0]
        _input_name = inp.name
        _input_shape = tuple(inp.shape)
        return True


def resolve_hw(shape: Sequence[Any], fallback: int) -> Tuple[int, int]:
    """从 NCHW 推断 H,W；动态维或非常量维用 fallback。"""
    if len(shape) < 4:
        return fallback, fallback

    def dim(x: Any) -> int:
        if isinstance(x, int) and x > 0:
            return x
        return fallback

    return dim(shape[2]), dim(shape[3])


def get_resolved_input_hw(fallback: int) -> Tuple[int, int]:
    return resolve_hw(_input_shape or (), fallback)


def preprocess_bgr_crop(
    bgr: np.ndarray,
    height: int,
    width: int,
    *,
    style: str = "imagenet",
) -> np.ndarray:
    """Resize + RGB → NCHW float32。style=imagenet | vit_hf（与 HF ViTImageProcessor 一致）。"""
    if bgr.size == 0:
        raise ValueError("empty crop")
    rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
    rgb = cv2.resize(rgb, (width, height), interpolation=cv2.INTER_LINEAR)
    x = rgb.astype(np.float32) / 255.0
    st = (style or "imagenet").lower()
    if st in ("vit", "vit_hf", "huggingface", "hf_vit"):
        mean = np.array([0.5, 0.5, 0.5], dtype=np.float32)
        std = np.array([0.5, 0.5, 0.5], dtype=np.float32)
    else:
        mean = np.array([0.485, 0.456, 0.406], dtype=np.float32)
        std = np.array([0.229, 0.224, 0.225], dtype=np.float32)
    x = (x - mean) / std
    x = np.transpose(x, (2, 0, 1))
    return np.expand_dims(x, axis=0)


def run_inference(batch_nchw: np.ndarray) -> List[np.ndarray]:
    if _session is None or _input_name is None:
        return []
    with _session_lock:
        out = _session.run(None, {_input_name: batch_nchw})
    return out


def positive_prob_from_logits(logits: np.ndarray, positive_index: int) -> float:
    """二分类：softmax 取 positive_index；[1,1] 用 sigmoid。"""
    o = np.asarray(logits)
    if o.ndim == 2 and o.shape[1] >= 2:
        row = o[0].astype(np.float64)
        row = row - np.max(row)
        e = np.exp(row)
        p = e / (np.sum(e) + 1e-12)
        idx = min(positive_index, p.shape[0] - 1)
        return float(p[idx])
    if o.size == 1:
        x = float(o.reshape(-1)[0])
        return float(1.0 / (1.0 + np.exp(-x)))
    if o.ndim == 1 and o.shape[0] >= 2:
        row = o.astype(np.float64)
        row = row - np.max(row)
        e = np.exp(row)
        p = e / (np.sum(e) + 1e-12)
        idx = min(positive_index, p.shape[0] - 1)
        return float(p[idx])
    return 0.0
