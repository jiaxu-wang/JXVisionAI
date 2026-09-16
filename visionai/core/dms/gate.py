"""DMS 准入状态：写入 Redis，供管理端展示。"""

from __future__ import annotations

import json
import logging
import time
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

_REASONS_ZH = {
    "ok": "机位合格",
    "pending": "评估中（需看清正脸）",
    "no_engine": "无人脸检测模型（models/buffalo_l/）",
    "no_face": "长时间未检出人脸",
    "face_small": "人脸过小，不像驾驶室正脸机位",
    "low_fps": "密检帧率不足",
    "off": "未开启疲劳驾驶",
}


def _hash_key() -> str:
    from visionai.config.settings import REDIS_KEY_PREFIX

    return f"{REDIS_KEY_PREFIX}dms_runtime"


def set_dms_status(stream_id: str, payload: Dict[str, Any]) -> None:
    sid = (stream_id or "").strip()
    if not sid:
        return
    try:
        from visionai.core.redis_manager import redis_manager

        if not redis_manager or not redis_manager._redis_client:
            return
        body = dict(payload)
        body["updated_at"] = time.time()
        redis_manager._redis_client.hset(
            _hash_key(), sid, json.dumps(body, ensure_ascii=False)
        )
    except Exception as e:  # noqa: BLE001
        logger.debug("persist dms status failed: %s", e)


def get_dms_status(stream_id: str) -> Optional[Dict[str, Any]]:
    sid = (stream_id or "").strip()
    if not sid:
        return None
    try:
        from visionai.core.redis_manager import redis_manager

        if not redis_manager or not redis_manager._redis_client:
            return None
        raw = redis_manager._redis_client.hget(_hash_key(), sid)
        if not raw:
            return None
        data = json.loads(raw)
        return data if isinstance(data, dict) else None
    except Exception:  # noqa: BLE001
        return None


def get_all_dms_status() -> Dict[str, Dict[str, Any]]:
    out: Dict[str, Dict[str, Any]] = {}
    try:
        from visionai.core.redis_manager import redis_manager

        if not redis_manager or not redis_manager._redis_client:
            return out
        raw = redis_manager._redis_client.hgetall(_hash_key()) or {}
        for k, v in raw.items():
            try:
                obj = json.loads(v)
            except Exception:  # noqa: BLE001
                continue
            if isinstance(obj, dict):
                out[str(k)] = obj
    except Exception:  # noqa: BLE001
        return out
    return out


def reason_zh(code: str) -> str:
    return _REASONS_ZH.get(str(code or ""), str(code or ""))


def evaluate_gate(
    *,
    samples: int,
    faces: int,
    max_face_px: int,
    min_face_px: int,
    achieved_fps: float,
    want_fps: float,
    has_engine: bool,
) -> Dict[str, Any]:
    if not has_engine:
        return {
            "supported": False,
            "reason": "no_engine",
            "reason_zh": reason_zh("no_engine"),
            "max_face_px": max_face_px,
            "samples": samples,
        }
    if samples < 8:
        return {
            "supported": None,
            "reason": "pending",
            "reason_zh": reason_zh("pending"),
            "max_face_px": max_face_px,
            "samples": samples,
        }
    if faces <= 0 or max_face_px <= 0:
        return {
            "supported": False,
            "reason": "no_face",
            "reason_zh": reason_zh("no_face"),
            "max_face_px": max_face_px,
            "samples": samples,
        }
    if max_face_px < int(min_face_px):
        return {
            "supported": False,
            "reason": "face_small",
            "reason_zh": f"{reason_zh('face_small')}（{max_face_px}px < {min_face_px}px）",
            "max_face_px": max_face_px,
            "samples": samples,
        }
    if want_fps >= 4 and achieved_fps < max(1.5, want_fps * 0.4):
        return {
            "supported": False,
            "reason": "low_fps",
            "reason_zh": f"{reason_zh('low_fps')}（{achieved_fps:.1f}/{want_fps:.0f}）",
            "max_face_px": max_face_px,
            "samples": samples,
        }
    return {
        "supported": True,
        "reason": "ok",
        "reason_zh": reason_zh("ok"),
        "max_face_px": max_face_px,
        "samples": samples,
    }
