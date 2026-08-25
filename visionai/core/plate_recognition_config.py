"""按流车牌识别配置归一化。"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from visionai.config.settings import (
    PLATE_RECOGNITION_MIN_DURATION_SEC,
    PLATE_RECOGNITION_OCR_MIN_CONF,
)

VALID_TRIGGER_TYPES = frozenset({"known", "unknown"})


def default_plate_recognition_config() -> Dict[str, Any]:
    return {
        "trigger_types": ["known", "unknown"],
        "min_duration_sec": None,
        "ocr_min_conf": None,
    }


def normalize_plate_recognition_config(
    raw: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    base = default_plate_recognition_config()
    if not raw or not isinstance(raw, dict):
        return base

    triggers: List[str] = []
    for t in raw.get("trigger_types") or []:
        key = str(t).strip().lower()
        if key in VALID_TRIGGER_TYPES and key not in triggers:
            triggers.append(key)
    if triggers:
        base["trigger_types"] = triggers

    dur = raw.get("min_duration_sec")
    if dur is not None and str(dur).strip() != "":
        try:
            base["min_duration_sec"] = max(0.0, float(dur))
        except (TypeError, ValueError):
            pass

    oc = raw.get("ocr_min_conf")
    if oc is not None and str(oc).strip() != "":
        try:
            base["ocr_min_conf"] = max(0.05, min(0.99, float(oc)))
        except (TypeError, ValueError):
            pass

    return base


def effective_min_duration(cfg: Dict[str, Any]) -> float:
    d = cfg.get("min_duration_sec")
    if d is not None:
        return float(d)
    return float(PLATE_RECOGNITION_MIN_DURATION_SEC)


def effective_ocr_min_conf(cfg: Dict[str, Any]) -> float:
    c = cfg.get("ocr_min_conf")
    if c is not None:
        return float(c)
    return float(PLATE_RECOGNITION_OCR_MIN_CONF)
