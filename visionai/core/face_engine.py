"""
buffalo_l 人脸推理。检测、对齐特征和性别年龄在 visionai-inferd（C++ ONNX Runtime）里跑。

- 检测：SCRFD（``det_10g.onnx``）
- 特征：ArcFace（``w600k_r50.onnx``），512 维 L2 归一化向量
- 属性：GenderAge（``genderage.onnx``），可选

画面旋转和坐标映射留在 Python：只是坐标变换，帧还要回到业务层。
"""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, List, Optional, Tuple

import cv2
import numpy as np

from visionai.config.settings import (
    FACE_RECOG_DET_CONF,
    FACE_RECOG_DET_MODEL_PATH,
    FACE_RECOG_DET_SIZE,
    FACE_RECOG_EMBED_MODEL_PATH,
    FACE_RECOG_GENDERAGE_ENABLED,
    FACE_RECOG_GENDERAGE_MODEL_PATH,
    PROJECT_ROOT,
)

logger = logging.getLogger(__name__)
_missing_logged = False


def _resolve(path: str) -> str:
    p = (path or "").strip()
    if not p:
        return ""
    if not os.path.isabs(p):
        p = os.path.join(PROJECT_ROOT, p)
    return os.path.abspath(p)


def _det_path() -> str:
    return _resolve(FACE_RECOG_DET_MODEL_PATH)


def _emb_path() -> str:
    return _resolve(FACE_RECOG_EMBED_MODEL_PATH)


def _ga_path() -> str:
    return _resolve(FACE_RECOG_GENDERAGE_MODEL_PATH)


def is_available() -> bool:
    global _missing_logged
    det, emb = _det_path(), _emb_path()
    ok = os.path.isfile(det) and os.path.isfile(emb)
    if not ok and not _missing_logged:
        _missing_logged = True
        logger.error("人脸模型文件缺失: det=%s emb=%s", det, emb)
    return ok


def genderage_available() -> bool:
    if not FACE_RECOG_GENDERAGE_ENABLED or not is_available():
        return False
    path = _ga_path()
    if not os.path.isfile(path):
        logger.warning("性别年龄模型缺失，已跳过: %s", path)
        return False
    return True


def _rotate_frame(frame_bgr: np.ndarray, degrees: int) -> np.ndarray:
    d = int(degrees) % 360
    if d == 90:
        return cv2.rotate(frame_bgr, cv2.ROTATE_90_CLOCKWISE)
    if d == 180:
        return cv2.rotate(frame_bgr, cv2.ROTATE_180)
    if d == 270:
        return cv2.rotate(frame_bgr, cv2.ROTATE_90_COUNTERCLOCKWISE)
    return frame_bgr


def _map_bbox_from_rotated(
    bbox: List[int], orig_w: int, orig_h: int, rotate: int
) -> List[int]:
    """将旋转后图像上的检测框映射回原始画面坐标。"""
    d = int(rotate) % 360
    if d == 0:
        return [int(bbox[0]), int(bbox[1]), int(bbox[2]), int(bbox[3])]
    x1, y1, x2, y2 = bbox
    corners = [(x1, y1), (x2, y1), (x2, y2), (x1, y2)]
    mapped: List[Tuple[float, float]] = []
    for x, y in corners:
        if d == 180:
            mapped.append((orig_w - x, orig_h - y))
        elif d == 90:
            mapped.append((y, orig_h - x))
        elif d == 270:
            mapped.append((orig_w - y, x))
        else:
            mapped.append((float(x), float(y)))
    xs = [p[0] for p in mapped]
    ys = [p[1] for p in mapped]
    return [
        max(0, int(min(xs))),
        max(0, int(min(ys))),
        min(orig_w - 1, int(max(xs))),
        min(orig_h - 1, int(max(ys))),
    ]


def _map_kps_from_rotated(
    kps: np.ndarray, orig_w: int, orig_h: int, rotate: int
) -> np.ndarray:
    d = int(rotate) % 360
    pts = np.asarray(kps, dtype=np.float32).reshape(-1, 2).copy()
    if d == 0:
        return pts
    mapped = []
    for x, y in pts:
        if d == 180:
            mapped.append((orig_w - x, orig_h - y))
        elif d == 90:
            mapped.append((y, orig_h - x))
        elif d == 270:
            mapped.append((orig_w - y, x))
        else:
            mapped.append((float(x), float(y)))
    return np.asarray(mapped, dtype=np.float32)


def _analyze(
    src: np.ndarray,
    *,
    max_faces: int,
    with_embedding: bool,
    with_genderage: bool,
):
    from visionai.core.infer_client import get_infer_client

    det_size = int(FACE_RECOG_DET_SIZE[0] if FACE_RECOG_DET_SIZE else 640)
    return get_infer_client().analyze_face(
        src,
        det_model=_det_path(),
        embed_model=_emb_path() if with_embedding else "",
        genderage_model=_ga_path() if with_genderage else "",
        det_conf=float(FACE_RECOG_DET_CONF),
        det_size=det_size,
        max_faces=max(1, int(max_faces)),
        with_embedding=with_embedding,
        with_genderage=with_genderage,
    )


def analyze_faces(
    frame_bgr: np.ndarray,
    *,
    max_faces: int = 5,
    rotate: int = 0,
    genderage: bool = False,
) -> List[Dict[str, Any]]:
    """检测人脸并提取特征。``genderage=True`` 时额外跑性别/年龄。"""
    if not is_available() or frame_bgr is None or frame_bgr.size == 0:
        return []
    orig_h, orig_w = frame_bgr.shape[:2]
    src = _rotate_frame(frame_bgr, rotate) if rotate else frame_bgr
    want_ga = bool(genderage) and genderage_available()
    try:
        resp = _analyze(src, max_faces=max_faces, with_embedding=True, with_genderage=want_ga)
    except Exception as ex:  # noqa: BLE001
        logger.debug("人脸检测异常: %s", ex, exc_info=True)
        return []
    out: List[Dict[str, Any]] = []
    for i, face in enumerate(resp.faces):
        if not face.embedding:
            continue
        bbox = [face.x1, face.y1, face.x2, face.y2]
        if rotate:
            bbox = _map_bbox_from_rotated(bbox, orig_w, orig_h, rotate)
        item: Dict[str, Any] = {
            "index": i,
            "bbox": [int(v) for v in bbox[:4]],
            "det_score": float(face.det_score),
            "embedding": np.asarray(list(face.embedding), dtype=np.float32),
        }
        if face.has_attr:
            item["gender"] = int(face.gender)
            item["age"] = int(face.age)
            item["gender_zh"] = "男" if int(face.gender) == 1 else "女"
        out.append(item)
    return out


def detect_faces_kps(
    frame_bgr: np.ndarray,
    *,
    max_faces: int = 2,
    rotate: int = 0,
) -> List[Dict[str, Any]]:
    """只做人脸框 + 5 点，不做 ArcFace（供 DMS）。"""
    det = _det_path()
    if not os.path.isfile(det) or frame_bgr is None or frame_bgr.size == 0:
        return []
    orig_h, orig_w = frame_bgr.shape[:2]
    src = _rotate_frame(frame_bgr, rotate) if rotate else frame_bgr
    try:
        resp = _analyze(src, max_faces=max_faces, with_embedding=False, with_genderage=False)
    except Exception as ex:  # noqa: BLE001
        logger.debug("DMS 人脸检测异常: %s", ex, exc_info=True)
        return []
    out: List[Dict[str, Any]] = []
    for i, face in enumerate(resp.faces):
        bbox = [face.x1, face.y1, face.x2, face.y2]
        kps = np.asarray(list(face.kps), dtype=np.float32).reshape(-1, 2) if face.kps else None
        if rotate:
            bbox = _map_bbox_from_rotated(bbox, orig_w, orig_h, rotate)
            if kps is not None:
                kps = _map_kps_from_rotated(kps, orig_w, orig_h, rotate)
        x1, y1, x2, y2 = [int(v) for v in bbox[:4]]
        out.append(
            {
                "index": i,
                "bbox": [x1, y1, x2, y2],
                "kps": kps,
                "det_score": float(face.det_score),
                "face_width": max(0, x2 - x1),
            }
        )
    return out


def extract_single_face_embedding(frame_bgr: np.ndarray) -> Optional[np.ndarray]:
    faces = analyze_faces(frame_bgr, max_faces=2)
    if len(faces) != 1:
        return None
    return faces[0]["embedding"]
