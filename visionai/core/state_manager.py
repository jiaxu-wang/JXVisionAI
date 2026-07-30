"""流在线状态：本地缓存 + Redis，供 API / worker 跨进程共享。"""

from __future__ import annotations

import json
import logging
import threading
import time
from typing import Dict

logger = logging.getLogger(__name__)

try:
    from visionai.core.redis_manager import redis_manager
except Exception:  # noqa: BLE001
    redis_manager = None

# 进程内缓存（同进程读写仍可用）
stream_status: Dict[str, str] = {}
stream_status_lock = threading.Lock()

# 「在线」心跳超时：超过则 API 视为离线（worker 崩溃后不会永久在线）
_ONLINE_STALE_SEC = 180.0


def _status_hash_key() -> str:
    from visionai.config.settings import REDIS_KEY_PREFIX

    return f"{REDIS_KEY_PREFIX}stream_runtime_status"


def _persist_status(name: str, status: str) -> None:
    if not name or not redis_manager or not redis_manager._redis_client:
        return
    try:
        payload = json.dumps(
            {"status": status, "updated_at": time.time()},
            ensure_ascii=False,
            separators=(",", ":"),
        )
        redis_manager._redis_client.hset(_status_hash_key(), name, payload)
    except Exception as e:  # noqa: BLE001
        logger.debug("persist stream status failed: %s", e)


def _decode_status_entry(raw: str) -> tuple[str, float]:
    """返回 (status, updated_at)；兼容旧纯文本值。"""
    if not raw:
        return "离线", 0.0
    text = str(raw).strip()
    if text.startswith("{"):
        try:
            obj = json.loads(text)
            st = str(obj.get("status") or "离线").strip() or "离线"
            ts = float(obj.get("updated_at") or 0.0)
            return st, ts
        except Exception:  # noqa: BLE001
            pass
    return text or "离线", time.time()


def _load_status_map_from_redis() -> Dict[str, str]:
    out: Dict[str, str] = {}
    if not redis_manager or not redis_manager._redis_client:
        return out
    try:
        raw = redis_manager._redis_client.hgetall(_status_hash_key()) or {}
    except Exception as e:  # noqa: BLE001
        logger.debug("load stream status failed: %s", e)
        return out
    now = time.time()
    for name, val in raw.items():
        if not name:
            continue
        status, updated_at = _decode_status_entry(val)
        if status == "在线" and updated_at > 0 and (now - updated_at) > _ONLINE_STALE_SEC:
            status = "离线"
        out[str(name)] = status
    return out


def set_stream_status(name: str, status: str) -> None:
    """更新本地 + Redis 中的流状态（worker 侧写入）。"""
    nm = (name or "").strip()
    if not nm:
        return
    st = (status or "离线").strip() or "离线"
    with stream_status_lock:
        stream_status[nm] = st
    _persist_status(nm, st)


def get_stream_status(name: str, default: str = "离线") -> str:
    nm = (name or "").strip()
    if not nm:
        return default
    remote = _load_status_map_from_redis()
    if nm in remote:
        return remote[nm]
    with stream_status_lock:
        return stream_status.get(nm, default)


def get_all_stream_statuses() -> Dict[str, str]:
    """合并 Redis（优先）与本地缓存，供 API /metrics 使用。"""
    merged: Dict[str, str] = {}
    with stream_status_lock:
        merged.update(stream_status)
    merged.update(_load_status_map_from_redis())
    return merged


def init_stream_status() -> None:
    """从流配置初始化本地状态；不覆盖 Redis 中已有的在线心跳。"""
    if not redis_manager:
        return
    try:
        streams = redis_manager.get_streams() or []
    except Exception:  # noqa: BLE001
        return
    remote = _load_status_map_from_redis()
    with stream_status_lock:
        for stream_info in streams:
            name = (stream_info.get("name") or "").strip()
            if not name:
                continue
            if name not in stream_status:
                stream_status[name] = remote.get(name, "离线")


init_stream_status()
