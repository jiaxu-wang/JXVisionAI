"""人脸识别：buffalo_l 检测 + 人脸库 1:N 比对 + 可配置触发类型。"""

from __future__ import annotations

import logging
from typing import Any, Dict, List

from visionai.config.detection_catalog import FACE_RECOG_KEY
from visionai.config.settings import FACE_RECOGNITION_MAX_FACES_PER_FRAME
from visionai.core import face_engine, face_library
from visionai.core.behaviors.common import apply_keyed_duration_alert
from visionai.core.behaviors.context import BehaviorContext
from visionai.core.face_recognition_config import (
    effective_genderage_enabled,
    effective_min_duration,
    effective_rotate,
    effective_threshold,
    normalize_face_recognition_config,
)

logger = logging.getLogger(__name__)


def _face_key(bbox: List[int]) -> str:
    cx = (bbox[0] + bbox[2]) // 2
    cy = (bbox[1] + bbox[3]) // 2
    return f"f_{cx // 40}_{cy // 40}"


class FaceRecognitionBehaviorPlugin:
    key = FACE_RECOG_KEY

    def evaluate(self, ctx: BehaviorContext, state: Dict[str, Any]) -> Dict[str, Any]:
        out: Dict[str, Any] = {
            "alert": False,
            "boxes": [],
            "matches": [],
            "alert_matches": [],
            "count": 0,
        }

        if not face_engine.is_available():
            if not state.get("_warned_no_engine"):
                logger.warning(
                    "[%s] face_recognition 已开启但 InsightFace 未加载，请检查 models/buffalo_l/",
                    ctx.stream_name,
                )
                state["_warned_no_engine"] = True
            return out

        cfg = normalize_face_recognition_config(ctx.extra.get("face_recognition_config"))
        trigger_types = set(cfg.get("trigger_types") or [])
        if not trigger_types:
            return out

        threshold = effective_threshold(cfg)
        min_dur = effective_min_duration(cfg)
        rotate = effective_rotate(cfg)
        want_genderage = effective_genderage_enabled(cfg)
        watchlist = cfg.get("watchlist") or []
        lib_empty = face_library.person_count() == 0

        faces = face_engine.analyze_faces(
            ctx.frame_source,
            max_faces=FACE_RECOGNITION_MAX_FACES_PER_FRAME,
            rotate=rotate,
            genderage=want_genderage,
        )
        out["count"] = len(faces)
        matches: List[Dict[str, Any]] = []
        scores_for_alert: Dict[str, float] = {}

        for face in faces:
            bbox = face["bbox"]
            box = [int(bbox[0]), int(bbox[1]), int(bbox[2]), int(bbox[3])]
            out["boxes"].append(
                {
                    "box": box,
                    "confidence": float(face.get("det_score", 0.0)),
                    "name": "face",
                }
            )
            emb = face["embedding"]
            fk = _face_key(box)

            if lib_empty:
                match_type = "unknown"
                person_id = None
                person_name = "陌生人"
                similarity = 0.0
            else:
                person_id, similarity = face_library.match_embedding(
                    emb,
                    threshold=threshold,
                    watchlist=watchlist if watchlist else None,
                )
                if person_id:
                    match_type = "known"
                    person_name = face_library.person_name(person_id)
                else:
                    match_type = "unknown"
                    person_name = "陌生人"

            m = {
                "box": box,
                "person_id": person_id,
                "person_name": person_name,
                "similarity": round(float(similarity), 4),
                "match_type": match_type,
                "face_key": fk,
            }
            if face.get("gender") is not None:
                m["gender"] = int(face["gender"])
            if face.get("age") is not None:
                m["age"] = int(face["age"])
            if face.get("gender_zh"):
                m["gender_zh"] = str(face["gender_zh"])
            matches.append(m)

            if match_type not in trigger_types:
                continue
            if match_type == "known" and lib_empty:
                continue

            alert_key = person_id if match_type == "known" else f"unknown_{fk}"
            scores_for_alert[alert_key] = max(
                scores_for_alert.get(alert_key, 0.0),
                float(similarity) if match_type == "known" else 1.0,
            )

        out["matches"] = matches

        alerting_keys, alert = apply_keyed_duration_alert(
            scores_for_alert,
            state,
            ctx.now,
            score_threshold=0.5 if lib_empty else 0.01,
            min_duration_sec=min_dur,
            since_key="face_recog_since",
        )

        alert_matches: List[Dict[str, Any]] = []
        if alert:
            key_set = set(alerting_keys)
            for m in matches:
                if m["match_type"] not in trigger_types:
                    continue
                if m["match_type"] == "known" and lib_empty:
                    continue
                ak = m["person_id"] if m["match_type"] == "known" else f"unknown_{m['face_key']}"
                if ak in key_set:
                    alert_matches.append(m)

        out["alert_matches"] = alert_matches
        out["alert"] = len(alert_matches) > 0
        out["trigger_types"] = list(trigger_types)
        if matches and not state.get("_logged_match"):
            logger.info(
                "[%s] face_recognition rotate=%s faces=%d matches=%s",
                ctx.stream_name,
                rotate,
                len(matches),
                [
                    f"{m['person_name']}:{m['similarity']:.2f}"
                    for m in matches[:3]
                ],
            )
            state["_logged_match"] = True
        return out
