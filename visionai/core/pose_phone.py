"""人+手机框重叠 → YOLOv8-pose：用手机中心与肩头/耳根/手腕距离区分「打电话」与「玩手机」。"""

from __future__ import annotations

import logging
import math
import threading
from typing import Any, Dict, List, Literal, Optional, Sequence, Tuple

import numpy as np
from ultralytics import YOLO

from visionai.config.settings import (
    PHONE_CALL_HEAD_RATIO,
    PHONE_PLAY_WRIST_RATIO,
    PHONE_POSE_KP_MIN_CONF,
    PHONE_VERTICAL_BOUNDARY,
    POSE_FOR_PHONE_ENABLED,
    POSE_MODEL,
    yolo_inference_device,
)

logger = logging.getLogger(__name__)

_pose_model = None  # Ultralytics pose
_pose_load_lock = threading.Lock()
_pose_load_attempted = False
_pose_load_fail_logged = False


def _iou_xyxy(
    a: Tuple[float, float, float, float], b: Tuple[float, float, float, float]
) -> float:
    ax1, ay1, ax2, ay2 = a
    bx1, by1, bx2, by2 = b
    iw = max(0.0, min(ax2, bx2) - max(ax1, bx1))
    ih = max(0.0, min(ay2, by2) - max(ay1, by1))
    inter = iw * ih
    if inter <= 0:
        return 0.0
    area_a = max(1.0, ax2 - ax1) * max(1.0, ay2 - ay1)
    area_b = max(1.0, bx2 - bx1) * max(1.0, by2 - by1)
    return float(inter / (area_a + area_b - inter + 1e-9))


def ensure_pose_model() -> Optional[Any]:
    """按需加载 Ultralytics pose；多流共用。失败则仅使用竖直带 fallback。"""
    global _pose_model, _pose_load_attempted, _pose_load_fail_logged
    if not POSE_FOR_PHONE_ENABLED:
        return None
    if _pose_model is not None:
        return _pose_model
    with _pose_load_lock:
        if _pose_model is not None:
            return _pose_model
        if _pose_load_attempted:
            return None
        _pose_load_attempted = True
        try:
            _pose_model = YOLO(POSE_MODEL)
            logger.info("姿态模型加载完成: %s", POSE_MODEL)
        except Exception as ex:  # noqa: BLE001
            _pose_model = None
            if not _pose_load_fail_logged:
                _pose_load_fail_logged = True
                logger.warning(
                    "姿态模型加载失败，「打电话/玩手机」仅用画面竖直比例粗分。"
                    "请将 yolov8n-pose.pt 下载到本机后把 config.ini 中 pose_model 设为绝对路径"
                    "（见 README / config.example.ini）。原因: %s",
                    ex,
                )
    return _pose_model


def infer_pose_skeletons(frame_bgr: Any) -> List[Dict[str, Any]]:
    """整图推理，返回每个人体实例bbox + keypoints。"""
    model = ensure_pose_model()
    if model is None:
        return []

    try:
        dev = yolo_inference_device()
        kw: dict[str, Any] = {"verbose": False}
        if dev is not None:
            kw["device"] = dev
        results = model(frame_bgr, **kw)
    except Exception as ex:  # noqa: BLE001
        logger.debug("pose 推理失败: %s", ex)
        return []

    outs: List[Dict[str, Any]] = []
    min_c = PHONE_POSE_KP_MIN_CONF
    for res in results:
        if res.boxes is None or len(res.boxes) == 0:
            continue
        kpv = getattr(res, "keypoints", None)
        if kpv is None:
            continue

        xyxy = res.boxes.xyxy.cpu().numpy()
        kp_xy_all = kpv.xy.cpu().numpy()

        nk = kp_xy_all.shape[1] if kp_xy_all.ndim >= 2 else 0
        n_inst = kp_xy_all.shape[0]

        kp_conf_np = getattr(kpv, "conf", None)
        if kp_conf_np is None and hasattr(kpv, "data"):
            kd = kpv.data.cpu().numpy()
            if kd.ndim == 3 and kd.shape[2] >= 3:
                kp_conf_np = kd[..., 2]
        if kp_conf_np is None:
            kconf = np.ones((n_inst, max(17, nk)), dtype=np.float64)
        else:
            kconf = kp_conf_np.cpu().numpy() if hasattr(kp_conf_np, "cpu") else np.asarray(kp_conf_np)

        ni = xyxy.shape[0]
        for ii in range(ni):
            if ii >= kp_xy_all.shape[0]:
                break
            kxy = kp_xy_all[ii]
            nrow = ii if kconf.shape[0] > ii else 0
            cf_slice = (
                kconf[nrow]
                if kconf.ndim >= 2 and nrow < kconf.shape[0]
                else np.ones(kxy.shape[0], dtype=np.float64)
            )
            if cf_slice.shape[0] < kxy.shape[0]:
                cf_slice = np.pad(
                    cf_slice,
                    (0, kxy.shape[0] - cf_slice.shape[0]),
                    constant_values=1.0,
                )
            box_t = tuple(float(x) for x in xyxy[ii][:4])
            outs.append(
                {
                    "xyxy": box_t,
                    "keypoints_xy": np.asarray(kxy, dtype=np.float64),
                    "kp_conf": np.asarray(cf_slice[: kxy.shape[0]], dtype=np.float64),
                    "_min_conf": min_c,
                }
            )

    return outs


def match_skeleton_for_person(
    person_box_xyxy: Tuple[Any, Any, Any, Any],
    skeletons: Sequence[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    """与 pose 人体框按 IoU 对齐到 YOLO person 框。"""
    if not skeletons:
        return None
    pb = tuple(float(v) for v in person_box_xyxy[:4])
    best_sk: Optional[Dict[str, Any]] = None
    best_i = 0.0
    for sk in skeletons:
        ov = _iou_xyxy(pb, tuple(sk["xyxy"]))
        if ov > best_i:
            best_i = ov
            best_sk = sk
    if best_sk is None or best_i < 0.12:
        return None
    return best_sk


def _vertical_fallback(
    person_xyxy: Tuple[float, float, float, float],
    phone_xyxy: Tuple[float, float, float, float],
    boundary: float,
) -> Literal["call", "play"]:
    px1, py1, px2, py2 = person_xyxy
    ph_h = float(max(1.0, py2 - py1))
    pcy = (float(phone_xyxy[1]) + float(phone_xyxy[3])) * 0.5
    ny = (pcy - py1) / ph_h
    return "call" if ny < boundary else "play"


_HEAD_IDX = (0, 1, 2, 3, 4)
_WRIST_IDX = (9, 10)


def classify_phone_overlap_mode(
    person_box_xyxy: Tuple[Any, Any, Any, Any],
    phone_box_xyxy: Tuple[Any, Any, Any, Any],
    skeleton_for_person: Optional[Dict[str, Any]],
) -> Literal["call", "play"]:
    """单对重叠：calling（贴头肩）或 playing（靠双手/身前）。"""
    boundary = PHONE_VERTICAL_BOUNDARY
    head_th = PHONE_CALL_HEAD_RATIO
    wrist_th = PHONE_PLAY_WRIST_RATIO
    min_cf = PHONE_POSE_KP_MIN_CONF

    pb = (
        float(person_box_xyxy[0]),
        float(person_box_xyxy[1]),
        float(person_box_xyxy[2]),
        float(person_box_xyxy[3]),
    )
    qb = (
        float(phone_box_xyxy[0]),
        float(phone_box_xyxy[1]),
        float(phone_box_xyxy[2]),
        float(phone_box_xyxy[3]),
    )
    px1, py1, px2, py2 = pb
    ph_box = float(max(1.0, py2 - py1))

    pcx = (qb[0] + qb[2]) * 0.5
    pcy = (qb[1] + qb[3]) * 0.5

    if skeleton_for_person is None:
        return _vertical_fallback(pb, qb, boundary)

    kp = np.asarray(skeleton_for_person["keypoints_xy"])
    cf_arr = np.asarray(skeleton_for_person.get("kp_conf", np.ones(kp.shape[0])))
    mc = float(skeleton_for_person.get("_min_conf", min_cf))

    def cf_ok(ii: int) -> bool:
        if ii >= len(cf_arr):
            return False
        return float(cf_arr[ii]) >= mc

    d_heads: List[float] = []
    for i in _HEAD_IDX:
        if kp.shape[0] > i and cf_ok(i):
            d_heads.append(
                math.hypot(float(pcx) - float(kp[i][0]), float(pcy) - float(kp[i][1]))
            )
    d_wrists: List[float] = []
    for i in _WRIST_IDX:
        if kp.shape[0] > i and cf_ok(i):
            d_wrists.append(
                math.hypot(float(pcx) - float(kp[i][0]), float(pcy) - float(kp[i][1]))
            )

    dh = min(d_heads) if d_heads else math.inf
    dw = min(d_wrists) if d_wrists else math.inf

    head_px = head_th * ph_box
    wrist_px = wrist_th * ph_box
    margin = max(16.0, ph_box * 0.036)

    # 手机明显靠近头部关键点
    if math.isfinite(dh) and dh <= head_px * 1.05:
        if not math.isfinite(dw) or dh + margin <= dw:
            return "call"

    # 手机明显挨着腕部且不靠头一侧
    if math.isfinite(dw) and dw <= wrist_px * 1.05:
        if not math.isfinite(dh):
            return "play"
        if dw + margin <= dh:
            return "play"

    if math.isfinite(dh) and math.isfinite(dw):
        if dh + margin < dw:
            return "call"
        if dw + margin < dh:
            return "play"
        # 两者都较近时，比谁更近手机中心
        return "call" if dh <= dw else "play"

    if math.isfinite(dh):
        return "call"

    if math.isfinite(dw):
        return "play"

    return _vertical_fallback(pb, qb, boundary)
