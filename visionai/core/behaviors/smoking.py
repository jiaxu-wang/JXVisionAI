"""吸烟：person 裁剪 + ONNX 二分类；状态在 registry 传入的 state dict 中维护。"""

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

    def evaluate(self, ctx: BehaviorContext, state: Dict[str, Any]) -> Dict[str, Any]:
        out: Dict[str, Any] = {
            "alert": False,
            "person_indices": [],
            "scores": {},
        }
        path = (SMOKING_MODEL_PATH or "").strip()
        if not path:
            if not state.get("_warned_no_path"):
                logger.warning(
                    "[%s] 吸烟检测已开启但未配置 smoking_model_path（或环境变量 SMOKING_MODEL_PATH），"
                    "不会运行 ONNX 推理；请在 config.ini 的 [visionai] 中设置有效的 .onnx 路径后重启",
                    ctx.stream_name,
                )
                state["_warned_no_path"] = True
            return out
        if not ort_clf.ort_available():
            if not state.get("_warned_no_ort"):
                logger.warning(
                    "[%s] 未安装 onnxruntime，吸烟检测不可用：请使用 ./env/bin/pip install onnxruntime",
                    ctx.stream_name,
                )
                state["_warned_no_ort"] = True
            return out
        if not ort_clf.load_session(path):
            if not state.get("_warned_load_fail"):
                logger.error(
                    "[%s] 加载吸烟 ONNX 失败（路径不存在或格式错误）: %s",
                    ctx.stream_name,
                    path,
                )
                state["_warned_load_fail"] = True
            return out

        h0, w0 = ort_clf.get_resolved_input_hw(SMOKING_INPUT_SIZE)

        persons = ctx.persons
        indexed: List[Tuple[int, Dict[str, Any]]] = list(enumerate(persons))
        indexed.sort(key=lambda t: float(t[1].get("confidence", 0.0)), reverse=True)
        indexed = indexed[: max(1, SMOKING_MAX_PERSONS_PER_FRAME)]

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

        out["scores"] = scores
        since_map: Dict[str, float] = state.setdefault("person_since", {})

        alerting: List[int] = []
        now = ctx.now
        dur = SMOKING_MIN_DURATION_SEC
        active_keys = set()
        for pi, person in indexed:
            pk = str(pi)
            if pk not in scores:
                if pk in since_map:
                    del since_map[pk]
                continue
            active_keys.add(pk)
            if scores[pk] < SMOKING_CONF_THRESHOLD:
                if pk in since_map:
                    del since_map[pk]
                continue
            if pk not in since_map:
                since_map[pk] = now
            if now - since_map[pk] >= dur:
                alerting.append(pi)

        for pk in list(since_map.keys()):
            if pk not in active_keys:
                del since_map[pk]

        out["person_indices"] = alerting
        out["alert"] = len(alerting) > 0

        if SMOKING_LOG_SCORES:
            if not scores:
                if cigarette_boxes is not None:
                    logger.info(
                        "[%s] 吸烟推理: 无分数（香烟门控：本帧 %d 个候选烟框均未与任一待检人物重叠，"
                        "或人物裁剪过小；person=%d）",
                        ctx.stream_name,
                        len(cigarette_boxes),
                        len(persons),
                    )
                else:
                    logger.info(
                        "[%s] 吸烟推理: 无分数 (YOLO person=%d，可能无人/框过小未送 ONNX)",
                        ctx.stream_name,
                        len(persons),
                    )
            else:
                parts = [
                    f"pid{k}={scores[k]:.4f}"
                    for k in sorted(scores.keys(), key=lambda x: int(x))
                ]
                gate_info = ""
                if cigarette_boxes is not None:
                    gate_info = f" cigarette_gate=yes n_cig={len(cigarette_boxes)}"
                # logger.info(
                #     "[%s] 吸烟置信度 thr=%.3f dur>=%.2fs | %s | alert=%s pids=%s%s",
                #     ctx.stream_name,
                #     SMOKING_CONF_THRESHOLD,
                #     SMOKING_MIN_DURATION_SEC,
                #     ", ".join(parts),
                #     out["alert"],
                #     alerting,
                #     gate_info,
                # )
        return out
