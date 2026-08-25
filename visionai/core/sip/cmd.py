"""API ↔ SIP 进程命令队列（Redis List）。"""

from __future__ import annotations

import json
import logging
import time
import uuid
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


def enqueue_cmd(op: str, **fields: Any) -> str:
    from visionai.core.gb28181_store import cmd_key, cmd_result_key
    from visionai.core.redis_manager import redis_manager

    request_id = uuid.uuid4().hex
    if not redis_manager or not redis_manager.is_connected():
        raise RuntimeError("Redis未连接")
    payload = {"op": op, "request_id": request_id, **fields}
    redis_manager._redis_client.rpush(cmd_key(redis_manager), json.dumps(payload, ensure_ascii=False))
    redis_manager._redis_client.delete(cmd_result_key(redis_manager, request_id))
    return request_id


def wait_result(request_id: str, timeout_sec: float = 20.0) -> Dict[str, Any]:
    from visionai.core.gb28181_store import cmd_result_key
    from visionai.core.redis_manager import redis_manager

    if not redis_manager or not redis_manager.is_connected():
        return {"ok": False, "message": "Redis未连接"}
    key = cmd_result_key(redis_manager, request_id)
    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        raw = redis_manager._redis_client.get(key)
        if raw:
            try:
                return json.loads(raw)
            except Exception:  # noqa: BLE001
                return {"ok": False, "message": "invalid result"}
        time.sleep(0.2)
    return {"ok": False, "message": "SIP 点播超时（信令进程未响应）"}


def reply_cmd(request_id: str, result: Dict[str, Any]) -> None:
    from visionai.core.gb28181_store import cmd_result_key
    from visionai.core.redis_manager import redis_manager

    if not redis_manager or not redis_manager.is_connected() or not request_id:
        return
    redis_manager._redis_client.set(
        cmd_result_key(redis_manager, request_id),
        json.dumps(result, ensure_ascii=False),
        ex=120,
    )


def blpop_cmd(timeout_sec: int = 1) -> Optional[Dict[str, Any]]:
    from visionai.core.gb28181_store import cmd_key
    from visionai.core.redis_manager import redis_manager

    if not redis_manager or not redis_manager.is_connected():
        time.sleep(min(timeout_sec, 1))
        return None
    item = redis_manager._redis_client.blpop(cmd_key(redis_manager), timeout=timeout_sec)
    if not item:
        return None
    _, raw = item
    try:
        data = json.loads(raw)
        return data if isinstance(data, dict) else None
    except Exception:  # noqa: BLE001
        return None
