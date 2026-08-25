"""
车牌库：车牌号与备注存 Redis。

Redis Hash：``{prefix}plate_library:plates``（field = 规范化车牌号）。
"""

from __future__ import annotations

import logging
import threading
from datetime import datetime
from typing import Any, Dict, List, Optional

from visionai.core import plate_ocr
from visionai.core.redis_manager import redis_manager
from visionai.utils.timeutil import app_now

logger = logging.getLogger(__name__)

_lock = threading.Lock()
_index: Dict[str, Dict[str, Any]] = {}


def reload_index() -> None:
    global _index
    if not redis_manager or not redis_manager.is_connected():
        logger.warning("Redis 未连接，车牌库内存索引为空")
        with _lock:
            _index = {}
        return
    raw = redis_manager.get_all_plates()
    new_index: Dict[str, Dict[str, Any]] = {}
    for plate_no, meta in (raw or {}).items():
        key = plate_ocr.normalize_plate_text(str(plate_no or ""))
        if not key or not isinstance(meta, dict):
            continue
        meta = dict(meta)
        meta["plate_no"] = key
        new_index[key] = meta
    with _lock:
        _index = new_index
    logger.info("车牌库已从 Redis 加载: %d 条", len(_index))


def plate_count() -> int:
    with _lock:
        return len(_index)


def list_plates() -> List[Dict[str, Any]]:
    with _lock:
        out = [
            {
                "plate_no": m.get("plate_no", ""),
                "name": m.get("name", ""),
                "note": m.get("note", ""),
                "created_at": m.get("created_at", ""),
                "updated_at": m.get("updated_at", ""),
            }
            for m in _index.values()
        ]
    out.sort(key=lambda x: x.get("plate_no", ""))
    return out


def get_plate(plate_no: str) -> Optional[Dict[str, Any]]:
    key = plate_ocr.normalize_plate_text(plate_no)
    if not key:
        return None
    with _lock:
        meta = _index.get(key)
        return dict(meta) if meta else None


def lookup(plate_no: str) -> Optional[Dict[str, Any]]:
    """查库：命中返回元数据，否则 None。"""
    return get_plate(plate_no)


def add_plate(
    plate_no: str,
    *,
    name: str = "",
    note: str = "",
) -> Dict[str, Any]:
    key = plate_ocr.normalize_plate_text(plate_no)
    if not key:
        return {"success": False, "message": "车牌号无效"}
    if len(key) < 5:
        return {"success": False, "message": "车牌号过短"}
    if not redis_manager or not redis_manager.is_connected():
        return {"success": False, "message": "Redis 未连接"}

    now = app_now().isoformat(timespec="seconds")
    with _lock:
        existing = _index.get(key)
    created = (existing or {}).get("created_at") or now
    meta = {
        "plate_no": key,
        "name": (name or "").strip(),
        "note": (note or "").strip(),
        "created_at": created,
        "updated_at": now,
    }
    if not redis_manager.save_plate(key, meta):
        return {"success": False, "message": "写入 Redis 失败"}
    with _lock:
        _index[key] = meta
    return {"success": True, "plate": meta, "message": "已保存"}


def update_plate(
    plate_no: str,
    *,
    name: Optional[str] = None,
    note: Optional[str] = None,
) -> bool:
    key = plate_ocr.normalize_plate_text(plate_no)
    if not key:
        return False
    with _lock:
        meta = dict(_index.get(key) or {})
    if not meta:
        return False
    if name is not None:
        meta["name"] = str(name).strip()
    if note is not None:
        meta["note"] = str(note).strip()
    meta["updated_at"] = app_now().isoformat(timespec="seconds")
    if not redis_manager or not redis_manager.save_plate(key, meta):
        return False
    with _lock:
        _index[key] = meta
    return True


def delete_plate(plate_no: str) -> bool:
    key = plate_ocr.normalize_plate_text(plate_no)
    if not key:
        return False
    if not redis_manager or not redis_manager.delete_plate(key):
        return False
    with _lock:
        _index.pop(key, None)
    return True


# 进程导入时尝试加载
try:
    reload_index()
except Exception as ex:  # noqa: BLE001
    logger.warning("车牌库初始加载失败: %s", ex)
