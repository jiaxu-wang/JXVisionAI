"""车牌识别：专模检测框 + OCR 读号 + 车牌库 known/unknown。"""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, List

from visionai.config.detection_catalog import PLATE_RECOG_KEY
from visionai.config.settings import (
    PLATE_DET_CONF,
    PLATE_DET_MODEL_PATH,
    PLATE_RECOGNITION_MAX_PLATES_PER_FRAME,
    PROJECT_ROOT,
)
from visionai.core import dedicated_yolo as dyolo
from visionai.core import plate_library, plate_ocr
from visionai.core.behaviors.common import apply_keyed_duration_alert
from visionai.core.behaviors.context import BehaviorContext
from visionai.core.plate_recognition_config import (
    effective_min_duration,
    effective_ocr_min_conf,
    normalize_plate_recognition_config,
)

logger = logging.getLogger(__name__)


def _resolve_det_model() -> str:
    path = (PLATE_DET_MODEL_PATH or "").strip()
    if path and not os.path.isabs(path):
        path = os.path.join(PROJECT_ROOT, path)
    if path and os.path.isfile(path):
        return path
    # 回退专模目录
    alt = os.path.join(PROJECT_ROOT, "models", "specialists", "plate", "model.onnx")
    if os.path.isfile(alt):
        return alt
    alt_pt = os.path.join(PROJECT_ROOT, "models", "specialists", "plate", "model.pt")
    if os.path.isfile(alt_pt):
        return alt_pt
    return path or ""


def _plate_key(box: List[int], text: str) -> str:
    if text:
        return f"p_{text}"
    cx = (box[0] + box[2]) // 2
    cy = (box[1] + box[3]) // 2
    return f"p_{cx // 40}_{cy // 40}"


class PlateRecognitionBehaviorPlugin:
    key = PLATE_RECOG_KEY

    def evaluate(self, ctx: BehaviorContext, state: Dict[str, Any]) -> Dict[str, Any]:
        out: Dict[str, Any] = {
            "alert": False,
            "boxes": [],
            "matches": [],
            "alert_matches": [],
            "count": 0,
        }

        cfg = normalize_plate_recognition_config(ctx.extra.get("plate_recognition_config"))
        trigger_types = set(cfg.get("trigger_types") or [])
        if not trigger_types:
            return out

        model_path = _resolve_det_model()
        if not model_path:
            if not state.get("_warned_no_det"):
                logger.warning(
                    "[%s] plate_recognition 已开启但未找到车牌检测模型 "
                    "(models/specialists/plate/model.onnx)",
                    ctx.stream_name,
                )
                state["_warned_no_det"] = True
            return out

        if not plate_ocr.is_available():
            if not state.get("_warned_no_ocr"):
                logger.warning(
                    "[%s] RapidOCR 不可用，请安装 rapidocr_onnxruntime",
                    ctx.stream_name,
                )
                state["_warned_no_ocr"] = True
            return out

        min_dur = effective_min_duration(cfg)
        ocr_min = effective_ocr_min_conf(cfg)
        lib_empty = plate_library.plate_count() == 0

        dets = dyolo.infer_detections(
            model_path,
            ctx.frame_source,
            conf=PLATE_DET_CONF,
            class_ids=None,
        )
        dets = dets[:PLATE_RECOGNITION_MAX_PLATES_PER_FRAME]
        out["count"] = len(dets)

        matches: List[Dict[str, Any]] = []
        scores_for_alert: Dict[str, float] = {}

        for d in dets:
            box = [int(v) for v in (d.get("box") or [])[:4]]
            if len(box) < 4:
                continue
            det_conf = float(d.get("confidence") or 0.0)
            color_name = str(d.get("name") or "")
            text, ocr_conf, used_box = plate_ocr.recognize_from_frame(
                ctx.frame_source, box
            )
            display_box = used_box if used_box else box

            out["boxes"].append(
                {
                    "box": display_box,
                    "confidence": det_conf,
                    "name": text or color_name or "plate",
                    "class_id": d.get("class_id"),
                }
            )

            if not text or ocr_conf < ocr_min:
                # 无可靠读号：仅展示检测框，不参与库比对告警
                continue

            meta = plate_library.lookup(text)
            if meta:
                match_type = "known"
                owner = str(meta.get("name") or "")
            else:
                match_type = "unknown"
                owner = ""

            pk = _plate_key(display_box, text)
            m = {
                "box": display_box,
                "plate_no": text,
                "owner_name": owner,
                "match_type": match_type,
                "ocr_confidence": round(float(ocr_conf), 4),
                "det_confidence": round(det_conf, 4),
                "color": color_name,
                "plate_key": pk,
            }
            matches.append(m)

            if match_type not in trigger_types:
                continue
            if match_type == "known" and lib_empty:
                continue

            alert_key = text if match_type == "known" else f"unknown_{pk}"
            scores_for_alert[alert_key] = max(
                scores_for_alert.get(alert_key, 0.0),
                float(ocr_conf),
            )

        out["matches"] = matches

        alerting_keys, alert = apply_keyed_duration_alert(
            scores_for_alert,
            state,
            ctx.now,
            score_threshold=ocr_min,
            min_duration_sec=min_dur,
            since_key="plate_recog_since",
        )

        alert_matches: List[Dict[str, Any]] = []
        if alert:
            key_set = set(alerting_keys)
            for m in matches:
                if m["match_type"] not in trigger_types:
                    continue
                ak = (
                    m["plate_no"]
                    if m["match_type"] == "known"
                    else f"unknown_{m['plate_key']}"
                )
                if ak in key_set:
                    alert_matches.append(m)

        out["alert_matches"] = alert_matches
        out["alert"] = len(alert_matches) > 0
        out["trigger_types"] = list(trigger_types)
        if matches and not state.get("_logged_match"):
            logger.info(
                "[%s] plate_recognition plates=%s",
                ctx.stream_name,
                [f"{m['plate_no']}:{m['match_type']}" for m in matches[:3]],
            )
            state["_logged_match"] = True
        return out
