"""
buffalo_l 人脸推理（纯 onnxruntime，不依赖 insightface 包）。

- 检测：SCRFD（``det_10g.onnx``），输出框与 5 点关键点
- 特征：ArcFace（``w600k_r50.onnx``），对齐后人脸 → 512 维 L2 归一化向量
- 属性：GenderAge（``genderage.onnx``），性别 + 年龄（可选）

会话在进程内懒加载并缓存；路径相对项目根解析。
"""

from __future__ import annotations

import logging
import os
import threading
from typing import Any, Dict, List, Optional, Tuple

import cv2
import numpy as np
import onnxruntime as ort

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

_lock = threading.RLock()
_det_sess: Optional[ort.InferenceSession] = None
_emb_sess: Optional[ort.InferenceSession] = None
_ga_sess: Optional[ort.InferenceSession] = None
_ga_input_name: Optional[str] = None
_ga_failed = False
_ready = False
_failed = False

_STRIDES = (8, 16, 32)
_NUM_ANCHORS = 2
_GENDERAGE_SIZE = 96
# buffalo_l genderage.onnx：mean=0 / std=1（与 InsightFace Attribute 一致）
_GENDERAGE_MEAN = 0.0
_GENDERAGE_STD = 1.0


def _resolve(path: str) -> str:
    p = (path or "").strip()
    if not p:
        return ""
    if not os.path.isabs(p):
        p = os.path.join(PROJECT_ROOT, p)
    return os.path.abspath(p)


def _ensure_genderage_session() -> bool:
    """懒加载 genderage；失败不影响检测/识别。"""
    global _ga_sess, _ga_input_name, _ga_failed
    if not FACE_RECOG_GENDERAGE_ENABLED:
        return False
    if _ga_sess is not None:
        return True
    if _ga_failed:
        return False
    with _lock:
        if _ga_sess is not None:
            return True
        if _ga_failed:
            return False
        ga_path = _resolve(FACE_RECOG_GENDERAGE_MODEL_PATH)
        if not os.path.isfile(ga_path):
            logger.warning("性别年龄模型缺失，已跳过: %s", ga_path)
            _ga_failed = True
            return False
        try:
            opts = ort.SessionOptions()
            opts.log_severity_level = 3
            _ga_sess = ort.InferenceSession(
                ga_path, opts, providers=["CPUExecutionProvider"]
            )
            _ga_input_name = _ga_sess.get_inputs()[0].name
            logger.info("性别年龄 ONNX 已加载: %s", ga_path)
            return True
        except Exception as ex:  # noqa: BLE001
            logger.warning("性别年龄 ONNX 加载失败，已跳过: %s", ex)
            _ga_failed = True
            _ga_sess = None
            return False


def _ensure_sessions() -> bool:
    global _det_sess, _emb_sess, _ready, _failed
    if _ready:
        return True
    if _failed:
        return False
    with _lock:
        if _ready:
            return True
        if _failed:
            return False
        det_path = _resolve(FACE_RECOG_DET_MODEL_PATH)
        emb_path = _resolve(FACE_RECOG_EMBED_MODEL_PATH)
        if not os.path.isfile(det_path) or not os.path.isfile(emb_path):
            logger.error("人脸模型文件缺失: det=%s emb=%s", det_path, emb_path)
            _failed = True
            return False
        try:
            opts = ort.SessionOptions()
            opts.log_severity_level = 3
            providers = ["CPUExecutionProvider"]
            _det_sess = ort.InferenceSession(det_path, opts, providers=providers)
            _emb_sess = ort.InferenceSession(emb_path, opts, providers=providers)
            _ready = True
            logger.info("人脸 ONNX 已加载: %s , %s", det_path, emb_path)
            _ensure_genderage_session()
        except Exception as ex:  # noqa: BLE001
            logger.error("人脸 ONNX 加载失败: %s", ex, exc_info=True)
            _failed = True
            return False
    return True


def is_available() -> bool:
    return _ensure_sessions()


def genderage_available() -> bool:
    if not _ensure_sessions():
        return False
    with _lock:
        return _ensure_genderage_session()


def _anchor_centers(det_size: int) -> List[np.ndarray]:
    centers: List[np.ndarray] = []
    for stride in _STRIDES:
        h = det_size // stride
        w = det_size // stride
        xs = (np.arange(w) * stride + stride * 0.5).astype(np.float32)
        ys = (np.arange(h) * stride + stride * 0.5).astype(np.float32)
        xv, yv = np.meshgrid(xs, ys)
        grid = np.stack([xv, yv], axis=-1).reshape(-1, 2)
        grid = np.repeat(grid, _NUM_ANCHORS, axis=0)
        centers.append(grid)
    return centers


def _preprocess_det(img_bgr: np.ndarray, det_size: int) -> Tuple[np.ndarray, float]:
    h, w = img_bgr.shape[:2]
    scale = min(det_size / h, det_size / w)
    nh, nw = int(h * scale), int(w * scale)
    resized = cv2.resize(img_bgr, (nw, nh))
    canvas = np.zeros((det_size, det_size, 3), dtype=np.uint8)
    canvas[:nh, :nw] = resized
    blob = canvas.astype(np.float32)
    blob = (blob - 127.5) / 128.0
    blob = blob.transpose(2, 0, 1)[np.newaxis, ...]
    return blob, scale


def _nms_boxes(boxes: np.ndarray, scores: np.ndarray, thresh: float = 0.4) -> List[int]:
    if len(boxes) == 0:
        return []
    x1 = boxes[:, 0]
    y1 = boxes[:, 1]
    x2 = boxes[:, 2]
    y2 = boxes[:, 3]
    areas = (x2 - x1) * (y2 - y1)
    order = scores.argsort()[::-1]
    keep: List[int] = []
    while order.size > 0:
        i = int(order[0])
        keep.append(i)
        if order.size == 1:
            break
        xx1 = np.maximum(x1[i], x1[order[1:]])
        yy1 = np.maximum(y1[i], y1[order[1:]])
        xx2 = np.minimum(x2[i], x2[order[1:]])
        yy2 = np.minimum(y2[i], y2[order[1:]])
        inter = np.maximum(0, xx2 - xx1) * np.maximum(0, yy2 - yy1)
        iou = inter / (areas[i] + areas[order[1:]] - inter + 1e-6)
        inds = np.where(iou <= thresh)[0]
        order = order[inds + 1]
    return keep


_ARCFACE_DST = np.array(
    [
        [38.2946, 51.6963],
        [73.5318, 51.5014],
        [56.0252, 71.7366],
        [41.5493, 92.3655],
        [70.7299, 92.2041],
    ],
    dtype=np.float32,
)


def _distance2kps(points: np.ndarray, distance: np.ndarray) -> np.ndarray:
    preds = []
    for i in range(0, distance.shape[1], 2):
        px = points[:, 0] + distance[:, i]
        py = points[:, 1] + distance[:, i + 1]
        preds.append(px)
        preds.append(py)
    return np.stack(preds, axis=-1)


def _distance2bbox(points: np.ndarray, distance: np.ndarray) -> np.ndarray:
    x1 = points[:, 0] - distance[:, 0]
    y1 = points[:, 1] - distance[:, 1]
    x2 = points[:, 0] + distance[:, 2]
    y2 = points[:, 1] + distance[:, 3]
    return np.stack([x1, y1, x2, y2], axis=-1)


def _detect_faces_scrfd(
    img_bgr: np.ndarray,
    *,
    det_size: int,
    conf_thresh: float,
) -> List[Dict[str, Any]]:
    assert _det_sess is not None
    blob, scale = _preprocess_det(img_bgr, det_size)
    orig_h, orig_w = img_bgr.shape[:2]
    input_name = _det_sess.get_inputs()[0].name
    outputs = _det_sess.run(None, {input_name: blob})

    score_outputs = outputs[0:3]
    bbox_outputs = outputs[3:6]
    kps_outputs = outputs[6:9]
    centers_list = _anchor_centers(det_size)

    all_boxes: List[List[float]] = []
    all_scores: List[float] = []
    all_kps: List[np.ndarray] = []

    for stride_idx, stride in enumerate(_STRIDES):
        scores = score_outputs[stride_idx].reshape(-1)
        bboxes = bbox_outputs[stride_idx].reshape(-1, 4) * stride
        kps_preds = kps_outputs[stride_idx].reshape(-1, 10) * stride
        centers = centers_list[stride_idx]
        n = min(len(scores), len(centers), len(bboxes), len(kps_preds))
        boxes = _distance2bbox(centers[:n], bboxes[:n])
        kps_all = _distance2kps(centers[:n], kps_preds[:n])
        for j in range(n):
            sc = float(scores[j])
            if sc < conf_thresh:
                continue
            x1, y1, x2, y2 = boxes[j] / scale
            x1 = max(0, min(orig_w - 1, x1))
            y1 = max(0, min(orig_h - 1, y1))
            x2 = max(0, min(orig_w - 1, x2))
            y2 = max(0, min(orig_h - 1, y2))
            if x2 <= x1 or y2 <= y1:
                continue
            kps = (kps_all[j] / scale).reshape(5, 2)
            kps[:, 0] = np.clip(kps[:, 0], 0, orig_w - 1)
            kps[:, 1] = np.clip(kps[:, 1], 0, orig_h - 1)
            all_boxes.append([x1, y1, x2, y2])
            all_scores.append(sc)
            all_kps.append(kps.astype(np.float32))

    if not all_boxes:
        return []

    boxes_np = np.array(all_boxes, dtype=np.float32)
    scores_np = np.array(all_scores, dtype=np.float32)
    keep = _nms_boxes(boxes_np, scores_np)
    faces = []
    for ki in keep:
        x1, y1, x2, y2 = boxes_np[ki].astype(int).tolist()
        faces.append(
            {
                "bbox": [x1, y1, x2, y2],
                "det_score": float(scores_np[ki]),
                "kps": all_kps[ki],
            }
        )
    faces.sort(key=lambda f: f["det_score"], reverse=True)
    return faces


def _norm_crop(
    img_bgr: np.ndarray, kps: np.ndarray, image_size: int = 112
) -> Optional[np.ndarray]:
    pts = np.asarray(kps, dtype=np.float32).reshape(5, 2)
    M, _ = cv2.estimateAffinePartial2D(pts, _ARCFACE_DST, method=cv2.LMEDS)
    if M is None:
        return None
    return cv2.warpAffine(
        img_bgr, M, (image_size, image_size), borderValue=(0, 0, 0)
    )


def _crop_align(img_bgr: np.ndarray, bbox: List[int], pad: float = 0.15) -> np.ndarray:
    h, w = img_bgr.shape[:2]
    x1, y1, x2, y2 = bbox
    bw, bh = x2 - x1, y2 - y1
    px, py = int(bw * pad), int(bh * pad)
    x1 = max(0, x1 - px)
    y1 = max(0, y1 - py)
    x2 = min(w, x2 + px)
    y2 = min(h, y2 + py)
    crop = img_bgr[y1:y2, x1:x2]
    if crop.size == 0:
        return np.zeros((112, 112, 3), dtype=np.uint8)
    return cv2.resize(crop, (112, 112))


def _embed_face(face_bgr_112: np.ndarray) -> Optional[np.ndarray]:
    assert _emb_sess is not None
    img = face_bgr_112.astype(np.float32)
    img = (img - 127.5) / 127.5
    img = img[:, :, ::-1]
    blob = img.transpose(2, 0, 1)[np.newaxis, ...]
    input_name = _emb_sess.get_inputs()[0].name
    out = _emb_sess.run(None, {input_name: blob})[0][0].astype(np.float32)
    norm = float(np.linalg.norm(out))
    if norm > 1e-8:
        out = out / norm
    return out


def _genderage_crop(img_bgr: np.ndarray, bbox: List[int]) -> np.ndarray:
    """按 InsightFace Attribute 方式：框中心缩放裁剪到 96x96。"""
    x1, y1, x2, y2 = [float(v) for v in bbox]
    w, h = (x2 - x1), (y2 - y1)
    center = ((x2 + x1) / 2.0, (y2 + y1) / 2.0)
    scale = _GENDERAGE_SIZE / (max(w, h) * 1.5 + 1e-6)
    # 等价于 SimilarityTransform(scale) + 平移到输出中心（无旋转）
    M = np.array(
        [
            [scale, 0.0, _GENDERAGE_SIZE / 2.0 - center[0] * scale],
            [0.0, scale, _GENDERAGE_SIZE / 2.0 - center[1] * scale],
        ],
        dtype=np.float64,
    )
    return cv2.warpAffine(
        img_bgr, M, (_GENDERAGE_SIZE, _GENDERAGE_SIZE), borderValue=0.0
    )


def _predict_gender_age(
    img_bgr: np.ndarray, bbox: List[int]
) -> Tuple[Optional[int], Optional[int], Optional[str]]:
    """返回 (gender 0女/1男, age, gender_zh)。失败时全为 None。"""
    if not _ensure_genderage_session() or _ga_sess is None or not _ga_input_name:
        return None, None, None
    try:
        aimg = _genderage_crop(img_bgr, bbox)
        blob = cv2.dnn.blobFromImage(
            aimg,
            1.0 / _GENDERAGE_STD,
            (_GENDERAGE_SIZE, _GENDERAGE_SIZE),
            (_GENDERAGE_MEAN, _GENDERAGE_MEAN, _GENDERAGE_MEAN),
            swapRB=True,
        )
        pred = _ga_sess.run(None, {_ga_input_name: blob})[0][0]
        if pred is None or len(pred) < 3:
            return None, None, None
        gender = int(np.argmax(pred[:2]))
        age = int(np.round(float(pred[2]) * 100))
        age = max(0, min(120, age))
        gender_zh = "男" if gender == 1 else "女"
        return gender, age, gender_zh
    except Exception as ex:  # noqa: BLE001
        logger.debug("性别年龄推理异常: %s", ex, exc_info=True)
        return None, None, None


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


def analyze_faces(
    frame_bgr: np.ndarray,
    *,
    max_faces: int = 5,
    rotate: int = 0,
    genderage: bool = False,
) -> List[Dict[str, Any]]:
    """检测人脸并提取特征。

    ``genderage=True`` 时额外跑性别/年龄（需全局开关与模型可用）。
    """
    if not _ensure_sessions() or frame_bgr is None or frame_bgr.size == 0:
        return []
    orig_h, orig_w = frame_bgr.shape[:2]
    src = _rotate_frame(frame_bgr, rotate) if rotate else frame_bgr
    det_size = FACE_RECOG_DET_SIZE[0]
    try:
        dets = _detect_faces_scrfd(
            src, det_size=det_size, conf_thresh=FACE_RECOG_DET_CONF
        )
    except Exception as ex:  # noqa: BLE001
        logger.debug("人脸检测异常: %s", ex, exc_info=True)
        return []

    want_ga = (
        bool(genderage)
        and FACE_RECOG_GENDERAGE_ENABLED
        and _ensure_genderage_session()
    )
    out: List[Dict[str, Any]] = []
    for i, det in enumerate(dets[: max(1, max_faces)]):
        kps = det.get("kps")
        aligned = None
        if kps is not None:
            aligned = _norm_crop(src, kps)
        if aligned is None:
            aligned = _crop_align(src, det["bbox"])
        emb = _embed_face(aligned)
        if emb is None:
            continue
        bbox = det["bbox"]
        gender = age = None
        gender_zh = None
        if want_ga:
            gender, age, gender_zh = _predict_gender_age(src, bbox)
        if rotate:
            bbox = _map_bbox_from_rotated(bbox, orig_w, orig_h, rotate)
        item: Dict[str, Any] = {
            "index": i,
            "bbox": bbox,
            "det_score": det["det_score"],
            "embedding": emb,
        }
        if gender is not None and age is not None:
            item["gender"] = gender
            item["age"] = age
            item["gender_zh"] = gender_zh
        out.append(item)
    return out


def extract_single_face_embedding(frame_bgr: np.ndarray) -> Optional[np.ndarray]:
    faces = analyze_faces(frame_bgr, max_faces=2)
    if len(faces) != 1:
        return None
    return faces[0]["embedding"]
