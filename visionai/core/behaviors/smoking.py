"""吸烟：YOLO 专模直连 或 person 裁剪 + ONNX 二分类。"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Tuple

import cv2
import numpy as np

from visionai.config.detection_catalog import SMOKE_KEY
from visionai.config.settings import (
    SMOKING_CONF_THRESHOLD,
    SMOKING_INPUT_SIZE,
    SMOKING_LOG_SCORES,
    SMOKING_MAX_PERSONS_PER_FRAME,
    SMOKING_MIN_DURATION_SEC,
    SMOKING_MODEL_PATH,
    SMOKING_PERSON_PAD_RATIO,
    SMOKING_POSITIVE_CLASS_INDEX,
    SMOKING_PREPROCESS,
    SMOKING_REQUIRE_PERSON_OVERLAP,
    SMOKING_YOLO_DIRECT,
)
from visionai.core.behaviors.common import (
    apply_duration_alert,
    apply_keyed_duration_alert,
    overlap_boxes_for_persons,
    top_persons,
)
from visionai.core.behaviors.context import BehaviorContext
from visionai.core.behaviors import onnx_person_clf as ort_clf
from visionai.core.behaviors import cigarette_yolo_gate as cig_gate

logger = logging.getLogger(__name__)


def _crop_person_bgr(
    frame: np.ndarray, box: Tuple[int, int, int, int], pad_ratio: float
) -> np.ndarray:
    x1, y1, x2, y2 = box
    w = max(1, x2 - x1)
    h = max(1, y2 - y1)
    px = int(w * pad_ratio)
    py = int(h * pad_ratio)
    H, W = frame.shape[:2]
    x1 = max(0, x1 - px)
    y1 = max(0, y1 - py)
    x2 = min(W, x2 + px)
    y2 = min(H, y2 + py)
    if x2 <= x1 or y2 <= y1:
        return np.zeros((0, 0, 3), dtype=np.uint8)
    return frame[y1:y2, x1:x2]


class SmokingBehaviorPlugin:
    key = SMOKE_KEY

    def _evaluate_yolo_direct(
        self, ctx: BehaviorContext, state: Dict[str, Any]
    ) -> Dict[str, Any]:
        out: Dict[str, Any] = {
            "alert": False,
            "person_indices": [],
            "scores": {},
            "smoking_boxes": [],
            "event_boxes": [],
            "standalone": not SMOKING_REQUIRE_PERSON_OVERLAP,
            "alert_keys": [],
        }
        alerting_keys: List[str] = []
        alerting: List[int] = []
        if not cig_gate.gate_enabled():
            if not state.get("_warned_yolo_direct_no_path"):
                logger.warning(
                    "[%s] smoking_yolo_direct=true 但未配置 smoking_cigarette_detector_path",
                    ctx.stream_name,
                )
                state["_warned_yolo_direct_no_path"] = True
            return out
        if cig_gate.ensure_model() is None:
            return out

        smoking_boxes = cig_gate.infer_cigarette_boxes(ctx.frame_source)
        scores: Dict[str, float] = {}
        if SMOKING_REQUIRE_PERSON_OVERLAP:
            indexed = top_persons(ctx.persons, SMOKING_MAX_PERSONS_PER_FRAME)
            for pi, person in indexed:
                box = tuple(int(x) for x in person["box"][:4])
                sc = cig_gate.best_overlap_conf(box, smoking_boxes)
                if sc > 0:
                    scores[str(pi)] = round(sc, 4)
            alerting, alert = apply_duration_alert(
                indexed,
                scores,
                state,
                ctx.now,
                score_threshold=SMOKING_CONF_THRESHOLD,
                min_duration_sec=SMOKING_MIN_DURATION_SEC,
            )
            out["person_indices"] = alerting
            out["standalone"] = False
            if alert:
                ev = overlap_boxes_for_persons(indexed, alerting, smoking_boxes)
                out["smoking_boxes"] = ev
                out["event_boxes"] = ev
        else:
            indexed = []
            for i, d in enumerate(smoking_boxes):
                scores[str(i)] = round(float(d.get("confidence", 0.0)), 4)
            alerting_keys, alert = apply_keyed_duration_alert(
                scores,
                state,
                ctx.now,
                score_threshold=SMOKING_CONF_THRESHOLD,
                min_duration_sec=SMOKING_MIN_DURATION_SEC,
            )
            out["person_indices"] = []
            out["standalone"] = True
            out["alert_keys"] = alerting_keys
            if alert:
                want = set(alerting_keys)
                ev = [
                    {
                        "box": d["box"],
                        "confidence": d["confidence"],
                        "name": d.get("name", "smoking"),
                        "class_id": d.get("class_id"),
                    }
                    for i, d in enumerate(smoking_boxes)
                    if str(i) in want
                ]
                out["smoking_boxes"] = ev
                out["event_boxes"] = ev

        out["scores"] = scores
        out["alert"] = alert

        if SMOKING_LOG_SCORES:
            if not scores:
                logger.info(
                    "[%s] 吸烟 YOLO 直连: 本帧 smoking 框 %d 个%s",
                    ctx.stream_name,
                    len(smoking_boxes),
                    "，与人物均无重叠" if SMOKING_REQUIRE_PERSON_OVERLAP else "，未达阈值",
                )
            else:
                prefix = "pid" if SMOKING_REQUIRE_PERSON_OVERLAP else "evt"
                parts = [
                    f"{prefix}{k}={scores[k]:.4f}"
                    for k in sorted(scores.keys(), key=lambda x: int(x))
                ]
                hits = alerting if SMOKING_REQUIRE_PERSON_OVERLAP else alerting_keys
                logger.info(
                    "[%s] 吸烟 YOLO 直连 thr=%.3f dur>=%.2fs | %s | alert=%s hits=%s | n_smoking=%d",
                    ctx.stream_name,
                    SMOKING_CONF_THRESHOLD,
                    SMOKING_MIN_DURATION_SEC,
                    ", ".join(parts),
                    alert,
                    hits,
                    len(smoking_boxes),
                )
        return out

    def _evaluate_onnx(
        self, ctx: BehaviorContext, state: Dict[str, Any]
    ) -> Dict[str, Any]:
        out: Dict[str, Any] = {
            "alert": False,
            "person_indices": [],
            "scores": {},
            "smoking_boxes": [],
            "event_boxes": [],
        }
        path = (SMOKING_MODEL_PATH or "").strip()
        if not path:
            if not state.get("_warned_no_path"):
                logger.warning(
                    "[%s] 吸烟检测已开启但未配置 smoking_model_path；"
                    "可配置 smoking_yolo_direct=true + smoking_cigarette_detector_path 使用专训 YOLO",
                    ctx.stream_name,
                )
                state["_warned_no_path"] = True
            return out
        if not ort_clf.ort_available():
            if not state.get("_warned_no_ort"):
                logger.warning(
                    "[%s] 未安装 onnxruntime，吸烟检测不可用",
                    ctx.stream_name,
                )
                state["_warned_no_ort"] = True
            return out
        if not ort_clf.load_session(path):
            if not state.get("_warned_load_fail"):
                logger.error(
                    "[%s] 加载吸烟 ONNX 失败: %s",
                    ctx.stream_name,
                    path,
                )
                state["_warned_load_fail"] = True
            return out

        h0, w0 = ort_clf.get_resolved_input_hw(SMOKING_INPUT_SIZE)
        indexed = top_persons(ctx.persons, SMOKING_MAX_PERSONS_PER_FRAME)

        cigarette_boxes: Optional[List[Dict[str, Any]]] = None
        if cig_gate.gate_enabled() and cig_gate.ensure_model() is not None:
            cigarette_boxes = cig_gate.infer_cigarette_boxes(ctx.frame_source)

        scores: Dict[str, float] = {}
        for pi, person in indexed:
            box = person["box"]
            if cigarette_boxes is not None:
                if not cig_gate.person_has_overlapping_cigarette(
                    tuple(int(x) for x in box[:4]), cigarette_boxes
                ):
                    continue
            crop = _crop_person_bgr(ctx.frame_source, box, SMOKING_PERSON_PAD_RATIO)
            if crop.size < 300:
                continue
            try:
                batch = ort_clf.preprocess_bgr_crop(
                    crop, h0, w0, style=SMOKING_PREPROCESS
                )
            except ValueError:
                continue
            try:
                outs = ort_clf.run_inference(batch)
            except Exception as ex:
                if not state.get("_warned_infer"):
                    logger.error(
                        "[%s] 吸烟 ONNX 推理异常: %s", ctx.stream_name, ex, exc_info=True
                    )
                    state["_warned_infer"] = True
                continue
            if not outs:
                continue
            prob = ort_clf.positive_prob_from_logits(outs[0], SMOKING_POSITIVE_CLASS_INDEX)
            scores[str(pi)] = round(prob, 4)

        alerting, alert = apply_duration_alert(
            indexed,
            scores,
            state,
            ctx.now,
            score_threshold=SMOKING_CONF_THRESHOLD,
            min_duration_sec=SMOKING_MIN_DURATION_SEC,
        )
        out["scores"] = scores
        out["person_indices"] = alerting
        out["alert"] = alert
        if alert and cigarette_boxes:
            ev = overlap_boxes_for_persons(indexed, alerting, cigarette_boxes)
            out["smoking_boxes"] = ev
            out["event_boxes"] = ev

        if SMOKING_LOG_SCORES and not scores and cigarette_boxes is not None:
            logger.info(
                "[%s] 吸烟 ONNX: 门控本帧 %d 个候选框均未与人物重叠",
                ctx.stream_name,
                len(cigarette_boxes),
            )
        return out

    def evaluate(self, ctx: BehaviorContext, state: Dict[str, Any]) -> Dict[str, Any]:
        if SMOKING_YOLO_DIRECT and cig_gate.gate_enabled():
            return self._evaluate_yolo_direct(ctx, state)
        return self._evaluate_onnx(ctx, state)
