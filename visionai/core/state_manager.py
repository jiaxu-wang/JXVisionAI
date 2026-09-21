"""流在线状态：本地缓存 + Redis，供 API / worker 跨进程共享。"""

from __future__ import annotations

import json
import logging
import threading
import time
from typing import Any, Dict

logger = logging.getLogger(__name__)

try:
    from visionai.core.redis_manager import redis_manager
except Exception:  # noqa: BLE001
    redis_manager = None

STATUS_ONLINE = "online"
STATUS_OFFLINE = "offline"

# 进程内缓存（同进程读写仍可用）
stream_status: Dict[str, str] = {}
stream_status_lock = threading.Lock()

# 「在线」心跳超时：超过则 API 视为离线（worker 崩溃后不会永久在线）
_ONLINE_STALE_SEC = 180.0


def normalize_stream_status(raw: Any, default: str = STATUS_OFFLINE) -> str:
    """写入与读取统一为 online/offline；兼容 Redis 遗留「在线/离线」。"""
    s = str(raw if raw is not None else "").strip()
    if not s:
        s = str(default or "").strip()
    if s == "在线" or s.lower() == STATUS_ONLINE:
        return STATUS_ONLINE
    if s == "离线" or s.lower() == STATUS_OFFLINE:
        return STATUS_OFFLINE
    ds = str(default or "").strip()
    if ds == "在线" or ds.lower() == STATUS_ONLINE:
        return STATUS_ONLINE
    return STATUS_OFFLINE


def is_stream_online(raw: Any) -> bool:
    return normalize_stream_status(raw) == STATUS_ONLINE


def _status_hash_key() -> str:
    from visionai.config.settings import REDIS_KEY_PREFIX

    return f"{REDIS_KEY_PREFIX}stream_runtime_status"


def _client():
    rm = redis_manager
    if not rm:
        return None
    return getattr(rm, "_redis_client", None)


def _persist_status(name: str, status: str) -> None:
    client = _client()
    if not name or not client:
        return
    try:
        payload = json.dumps(
            {"status": status, "updated_at": time.time()},
            ensure_ascii=False,
            separators=(",", ":"),
        )
        client.hset(_status_hash_key(), name, payload)
    except Exception as e:  # noqa: BLE001
        logger.debug("persist stream status failed: %s", e)


def _decode_status_entry(raw: str) -> tuple[str, float]:
    """返回 (status, updated_at)；兼容旧纯文本值。"""
    if not raw:
        return STATUS_OFFLINE, 0.0
    text = str(raw).strip()
    if text.startswith("{"):
        try:
            obj = json.loads(text)
            st = str(obj.get("status") or STATUS_OFFLINE).strip() or STATUS_OFFLINE
            ts = float(obj.get("updated_at") or 0.0)
            return st, ts
        except Exception:  # noqa: BLE001
            pass
    return text or STATUS_OFFLINE, time.time()


def _load_status_map_from_redis() -> Dict[str, str]:
    out: Dict[str, str] = {}
    client = _client()
    if not client:
        return out
    try:
        raw = client.hgetall(_status_hash_key()) or {}
    except Exception as e:  # noqa: BLE001
        logger.debug("load stream status failed: %s", e)
        return out
    now = time.time()
    for name, val in raw.items():
        if not name:
            continue
        status, updated_at = _decode_status_entry(val)
        st = normalize_stream_status(status)
        if st == STATUS_ONLINE and updated_at > 0 and (now - updated_at) > _ONLINE_STALE_SEC:
            st = STATUS_OFFLINE
        out[str(name)] = st
    return out


def set_stream_status(name: str, status: str) -> None:
    """更新本地 + Redis 中的流状态（worker 侧写入）。始终存 online/offline。"""
    nm = (name or "").strip()
    if not nm:
        return
    st = normalize_stream_status(status)
    with stream_status_lock:
        stream_status[nm] = st
    _persist_status(nm, st)


def get_stream_status(name: str, default: str = STATUS_OFFLINE) -> str:
    nm = (name or "").strip()
    if not nm:
        return normalize_stream_status(default)
    remote = _load_status_map_from_redis()
    if nm in remote:
        return remote[nm]
    with stream_status_lock:
        return normalize_stream_status(stream_status.get(nm, default), default)


def get_all_stream_statuses() -> Dict[str, str]:
    """合并 Redis（优先）与本地缓存，供 API /metrics 使用。"""
    merged: Dict[str, str] = {}
    with stream_status_lock:
        for k, v in stream_status.items():
            merged[k] = normalize_stream_status(v)
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
                stream_status[name] = normalize_stream_status(remote.get(name, STATUS_OFFLINE))


init_stream_status()
