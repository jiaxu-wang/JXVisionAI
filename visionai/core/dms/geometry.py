"""5 点 + 眼区开合 + 头部俯仰。网格级 EAR 的可部署近似。"""

from __future__ import annotations

from typing import Any, Dict, Optional, Tuple

import cv2
import numpy as np

# 通用人脸 5 点（毫米量级相对坐标）
_MODEL_5 = np.array(
    [
        [-30.0, 35.0, -30.0],
        [30.0, 35.0, -30.0],
        [0.0, 0.0, 0.0],
        [-25.0, -30.0, -20.0],
        [25.0, -30.0, -20.0],
    ],
    dtype=np.float32,
)


def _gray(frame_bgr: np.ndarray) -> np.ndarray:
    if frame_bgr.ndim == 2:
        return frame_bgr
    return cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2GRAY)


def inter_ocular(kps: np.ndarray) -> float:
    pts = np.asarray(kps, dtype=np.float32).reshape(-1, 2)
    if pts.shape[0] < 2:
        return 0.0
    return float(np.linalg.norm(pts[0] - pts[1]))


def eye_open_score(frame_bgr: np.ndarray, eye_xy: np.ndarray, iod: float) -> float:
    """眼区垂直对比：睁眼更高。返回约 0–0.5，可与 ear_close 比较。"""
    if iod < 8:
        return 0.0
    gray = _gray(frame_bgr)
    h, w = gray.shape[:2]
    cx, cy = float(eye_xy[0]), float(eye_xy[1])
    rw = max(6, int(iod * 0.28))
    rh = max(4, int(iod * 0.18))
    x1 = max(0, int(cx - rw))
    x2 = min(w, int(cx + rw))
    y1 = max(0, int(cy - rh))
    y2 = min(h, int(cy + rh))
    if x2 - x1 < 6 or y2 - y1 < 4:
        return 0.0
    crop = gray[y1:y2, x1:x2]
    mid = crop.shape[1] // 2
    strip = crop[:, max(0, mid - 2) : mid + 3]
    if strip.size < 8:
        return 0.0
    col = strip.astype(np.float32).mean(axis=1)
    if col.size < 4:
        return 0.0
    # 归一化垂直变化：闭眼接近一条水平纹理
    g = np.abs(np.diff(col)).mean()
    rng = float(col.max() - col.min()) + 1e-3
    return float(max(0.0, min(0.55, (g / 40.0) * 0.35 + (rng / 80.0) * 0.2)))


def mouth_open_ratio(kps: np.ndarray) -> float:
    pts = np.asarray(kps, dtype=np.float32).reshape(-1, 2)
    if pts.shape[0] < 5:
        return 0.0
    iod = inter_ocular(pts)
    if iod < 8:
        return 0.0
    mouth_w = float(np.linalg.norm(pts[3] - pts[4]))
    # 哈欠时嘴角相对变宽，且鼻-嘴中点下移
    mid_m = (pts[3] + pts[4]) * 0.5
    drop = float(mid_m[1] - pts[2][1]) / iod
    return float(max(0.0, mouth_w / iod - 0.55) + max(0.0, drop - 0.55))


def _pitch_from_5pts(pts: np.ndarray) -> Optional[float]:
    """5 点几何近似俯仰：低头时鼻尖相对双眼下移。避免 OpenCV5 solvePnP 要 6 点。"""
    iod = inter_ocular(pts)
    if iod < 8:
        return None
    eye_mid = (pts[0] + pts[1]) * 0.5
    drop = float(pts[2][1] - eye_mid[1]) / iod
    return float((drop - 0.42) * 55.0)


def head_pitch_deg(kps: np.ndarray, frame_shape: Tuple[int, int]) -> Optional[float]:
    pts = np.asarray(kps, dtype=np.float32).reshape(-1, 2)
    if pts.shape[0] < 5:
        return None
    h, w = int(frame_shape[0]), int(frame_shape[1])
    if w < 8 or h < 8:
        return None
    # OpenCV 5 的 SOLVEPNP_ITERATIVE/DLT 要求 ≥6 点；5 点脸标改走 SQPNP 或几何近似
    try:
        flag = getattr(cv2, "SOLVEPNP_SQPNP", None) or getattr(cv2, "SOLVEPNP_EPNP", None)
        if flag is not None:
            cam = np.array(
                [[w, 0, w / 2.0], [0, w, h / 2.0], [0, 0, 1]],
                dtype=np.float64,
            )
            dist = np.zeros((4, 1), dtype=np.float64)
            ok, rvec, _ = cv2.solvePnP(
                _MODEL_5,
                pts[:5],
                cam,
                dist,
                flags=int(flag),
            )
            if ok:
                rot, _ = cv2.Rodrigues(rvec)
                return float(np.degrees(np.arcsin(np.clip(-rot[1, 2], -1.0, 1.0))))
    except Exception:  # noqa: BLE001
        pass
    return _pitch_from_5pts(pts[:5])


def measure_face(
    frame_bgr: np.ndarray,
    face: Dict[str, Any],
    *,
    night_mode: bool = False,
) -> Dict[str, Any]:
    kps = face.get("kps")
    bbox = face.get("bbox") or [0, 0, 0, 0]
    width = int(face.get("face_width") or max(0, int(bbox[2]) - int(bbox[0])))
    out: Dict[str, Any] = {
        "box": [int(bbox[0]), int(bbox[1]), int(bbox[2]), int(bbox[3])],
        "face_width": width,
        "ear": 0.0,
        "mouth": 0.0,
        "pitch": None,
        "closed": False,
        "yawn_like": False,
        "nod_like": False,
    }
    if kps is None:
        return out
    pts = np.asarray(kps, dtype=np.float32).reshape(-1, 2)
    iod = inter_ocular(pts)
    left = eye_open_score(frame_bgr, pts[0], iod)
    right = eye_open_score(frame_bgr, pts[1], iod)
    ear = (left + right) * 0.5
    if night_mode:
        ear *= 1.05
    mouth = mouth_open_ratio(pts)
    pitch = head_pitch_deg(pts, frame_bgr.shape[:2])
    out["ear"] = round(ear, 4)
    out["mouth"] = round(mouth, 4)
    out["pitch"] = None if pitch is None else round(float(pitch), 2)
    return out
