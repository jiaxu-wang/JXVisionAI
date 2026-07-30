"""流租约（多 worker HA）：持有租约的 worker 才处理该流。"""

from __future__ import annotations

import logging
import os
import socket
import time
import uuid
from typing import Optional

logger = logging.getLogger(__name__)


def resolve_worker_id() -> str:
    from visionai.config.settings import WORKER_ID

    if WORKER_ID:
        return WORKER_ID
    return f"{socket.gethostname()}-{os.getpid()}-{uuid.uuid4().hex[:6]}"


def _lease_key(stream_id: str) -> str:
    from visionai.config.settings import REDIS_KEY_PREFIX

    return f"{REDIS_KEY_PREFIX}stream_lease:{stream_id}"


def try_acquire_lease(stream_id: str, worker_id: str) -> bool:
    """尝试获取或续约租约。返回 True 表示本 worker 可处理该流。"""
    from visionai.config.settings import STREAM_LEASE_ENABLED, STREAM_LEASE_TTL_SEC
    from visionai.core.redis_manager import redis_manager

    if not STREAM_LEASE_ENABLED:
        return True
    if not stream_id or not redis_manager or not redis_manager._redis_client:
        return True
    client = redis_manager._redis_client
    key = _lease_key(stream_id)
    ttl = int(STREAM_LEASE_TTL_SEC)
    try:
        # SET NX EX：空闲时抢占
        if client.set(key, worker_id, nx=True, ex=ttl):
            return True
        cur = client.get(key)
        if cur == worker_id:
            client.expire(key, ttl)
            return True
        return False
    except Exception as e:  # noqa: BLE001
        logger.warning("lease acquire failed: %s", e)
        return True  # Redis 故障时降级为全量处理


def renew_lease(stream_id: str, worker_id: str) -> bool:
    return try_acquire_lease(stream_id, worker_id)


def release_lease(stream_id: str, worker_id: str) -> None:
    from visionai.config.settings import STREAM_LEASE_ENABLED
    from visionai.core.redis_manager import redis_manager

    if not STREAM_LEASE_ENABLED or not redis_manager or not redis_manager._redis_client:
        return
    try:
        key = _lease_key(stream_id)
        cur = redis_manager._redis_client.get(key)
        if cur == worker_id:
            redis_manager._redis_client.delete(key)
    except Exception as e:  # noqa: BLE001
        logger.debug("lease release failed: %s", e)
