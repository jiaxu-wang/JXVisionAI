"""按流人脸识别配置归一化。"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from jxvisionai.config.settings import (
    FACE_RECOG_GENDERAGE_ENABLED,
    FACE_RECOGNITION_MIN_DURATION_SEC,
    FACE_RECOGNITION_THRESHOLD,
    FACE_RECOG_ROTATE,
)

VALID_TRIGGER_TYPES = frozenset({"known", "unknown"})


def default_face_recognition_config() -> Dict[str, Any]:
    return {
        "trigger_types": ["known", "unknown"],
        "threshold": None,
        "min_duration_sec": None,
        "watchlist": [],
        "rotate": None,
        # 按流开关：是否跑 genderage（性别+年龄）；默认关，需在检测类型配置中勾选
        "genderage_enabled": False,
    }


def _as_bool(v: Any, default: bool = False) -> bool:
    if v is None:
        return default
    if isinstance(v, bool):
        return v
    s = str(v).strip().lower()
    if s in ("1", "true", "yes", "on"):
        return True
    if s in ("0", "false", "no", "off", ""):
        return False
    return default


def normalize_face_recognition_config(
    raw: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    base = default_face_recognition_config()
    if not raw or not isinstance(raw, dict):
        return base

    triggers: List[str] = []
    for t in raw.get("trigger_types") or []:
        key = str(t).strip().lower()
        if key in VALID_TRIGGER_TYPES and key not in triggers:
            triggers.append(key)
    if triggers:
        base["trigger_types"] = triggers

    thr = raw.get("threshold")
    if thr is not None and str(thr).strip() != "":
        try:
            base["threshold"] = max(0.05, min(0.99, float(thr)))
        except (TypeError, ValueError):
            pass

    dur = raw.get("min_duration_sec")
    if dur is not None and str(dur).strip() != "":
        try:
            base["min_duration_sec"] = max(0.0, float(dur))
        except (TypeError, ValueError):
            pass

    wl = raw.get("watchlist")
    if isinstance(wl, list):
        base["watchlist"] = [str(x).strip() for x in wl if str(x).strip()]

    rot = raw.get("rotate")
    if rot is not None and str(rot).strip() != "":
        try:
            r = int(float(rot)) % 360
            if r in (0, 90, 180, 270):
                base["rotate"] = r
        except (TypeError, ValueError):
            pass

    if "genderage_enabled" in raw:
        base["genderage_enabled"] = _as_bool(raw.get("genderage_enabled"), False)

    return base


def effective_rotate(cfg: Dict[str, Any]) -> int:
    r = cfg.get("rotate")
    if r is not None:
        try:
            v = int(r) % 360
            return v if v in (0, 90, 180, 270) else 0
        except (TypeError, ValueError):
            pass
    v = int(FACE_RECOG_ROTATE) % 360
    return v if v in (0, 90, 180, 270) else 0


def effective_threshold(cfg: Dict[str, Any]) -> float:
    t = cfg.get("threshold")
    if t is not None:
        return float(t)
    return float(FACE_RECOGNITION_THRESHOLD)


def effective_min_duration(cfg: Dict[str, Any]) -> float:
    d = cfg.get("min_duration_sec")
    if d is not None:
        return float(d)
    return float(FACE_RECOGNITION_MIN_DURATION_SEC)


def effective_genderage_enabled(cfg: Dict[str, Any]) -> bool:
    """按流勾选 且 全局未关闭 才启用性别/年龄。"""
    if not FACE_RECOG_GENDERAGE_ENABLED:
        return False
    return bool(cfg.get("genderage_enabled"))
