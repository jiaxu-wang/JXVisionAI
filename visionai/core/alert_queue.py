"""告警异步队列：检测线程投递，alert_worker 消费。"""

from __future__ import annotations

import json
import logging
import time
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


def _queue_key() -> str:
    from visionai.config.settings import REDIS_KEY_PREFIX

    return f"{REDIS_KEY_PREFIX}alert_queue"


def _dead_key() -> str:
    from visionai.config.settings import REDIS_KEY_PREFIX

    return f"{REDIS_KEY_PREFIX}alert_queue:dead"


def enqueue_alert_job(job: Dict[str, Any]) -> bool:
    """投递告警任务；失败返回 False（调用方可同步回退）。"""
    try:
        from visionai.config.settings import ALERT_QUEUE_ENABLED, ALERT_QUEUE_MAX_LEN
        from visionai.core.redis_manager import redis_manager
    except Exception:  # noqa: BLE001
        return False
    if not ALERT_QUEUE_ENABLED:
        return False
    if not redis_manager or not redis_manager.is_connected() or not redis_manager._redis_client:
        return False
    client = redis_manager._redis_client
    payload = dict(job)
    payload.setdefault("enqueued_at", time.time())
    payload.setdefault("attempts", 0)
    try:
        pipe = client.pipeline()
        pipe.rpush(_queue_key(), json.dumps(payload, ensure_ascii=False, default=str))
        pipe.ltrim(_queue_key(), -int(ALERT_QUEUE_MAX_LEN), -1)
        pipe.execute()
        return True
    except Exception as e:  # noqa: BLE001
        logger.warning("enqueue alert failed: %s", e)
        return False


def queue_depth() -> int:
    try:
        from visionai.core.redis_manager import redis_manager

        if not redis_manager or not redis_manager._redis_client:
            return 0
        return int(redis_manager._redis_client.llen(_queue_key()) or 0)
    except Exception:  # noqa: BLE001
        return 0


def brpop_alert_job(timeout: int = 5) -> Optional[Dict[str, Any]]:
    try:
        from visionai.core.redis_manager import redis_manager

        if not redis_manager or not redis_manager._redis_client:
            time.sleep(min(timeout, 2))
            return None
        item = redis_manager._redis_client.blpop(_queue_key(), timeout=timeout)
        if not item:
            return None
        _, raw = item
        return json.loads(raw)
    except Exception as e:  # noqa: BLE001
        logger.warning("brpop alert failed: %s", e)
        time.sleep(1)
        return None


def requeue_or_dead(job: Dict[str, Any], *, max_attempts: int = 3) -> None:
    attempts = int(job.get("attempts") or 0) + 1
    job["attempts"] = attempts
    job["last_error_at"] = time.time()
    try:
        from visionai.core.redis_manager import redis_manager

        if not redis_manager or not redis_manager._redis_client:
            return
        client = redis_manager._redis_client
        raw = json.dumps(job, ensure_ascii=False, default=str)
        if attempts >= max_attempts:
            client.rpush(_dead_key(), raw)
            client.ltrim(_dead_key(), -500, -1)
            logger.error("alert job moved to dead letter after %s attempts", attempts)
        else:
            client.rpush(_queue_key(), raw)
    except Exception as e:  # noqa: BLE001
        logger.error("requeue alert failed: %s", e)


def process_alert_job(job: Dict[str, Any]) -> None:
    """写检测记录、对象存储、邮件、Webhook。"""
    import os
    from datetime import datetime

    from visionai.config.settings import OBJECT_STORAGE_KEEP_LOCAL
    from visionai.core.object_storage import get_object_storage
    from visionai.core.redis_manager import redis_manager
    from visionai.utils.alert_email import notify_alert_by_email
    from visionai.utils.alert_webhook import (
        notify_alert_by_webhooks,
        resolved_alert_webhook_urls,
    )
    from visionai.utils.timeutil import app_now, app_tz

    stream_name = str(job.get("stream_name") or "")
    stream_id = str(job.get("stream_id") or "").strip()
    detection_types: List[str] = list(job.get("detection_types") or [])
    image_path = str(job.get("image_path") or "")
    ts_raw = job.get("timestamp")
    if isinstance(ts_raw, (int, float)):
        now = datetime.fromtimestamp(float(ts_raw), tz=app_tz())
    elif isinstance(ts_raw, str) and ts_raw:
        try:
            now = datetime.fromisoformat(ts_raw.replace("Z", "+00:00"))
            if now.tzinfo is None:
                now = now.replace(tzinfo=app_tz())
            else:
                now = now.astimezone(app_tz())
        except ValueError:
            now = app_now()
    else:
        now = app_now()
    extra = job.get("extra")
    record_id = str(job.get("record_id") or "").strip() or None
    alert_emails = list(job.get("alert_emails") or [])
    alert_email_enabled = bool(job.get("alert_email_enabled"))
    alert_webhook_urls = list(job.get("alert_webhook_urls") or [])
    alert_webhook_enabled = bool(job.get("alert_webhook_enabled"))

    object_key = None
    storage_kind = None
    store = get_object_storage()
    if store and image_path and os.path.isfile(image_path):
        rel_name = os.path.basename(image_path)
        sid = stream_id or "unknown"
        if not stream_id and redis_manager and redis_manager.is_connected():
            sid = redis_manager.get_stream_id_by_name(stream_name) or "unknown"
        s3_key = store.build_snapshot_key(sid, rel_name)
        try:
            ur = store.upload_file(image_path, s3_key, content_type="image/jpeg")
            object_key = ur.object_key
            storage_kind = ur.kind
        except Exception as ex:  # noqa: BLE001
            logger.error("[%s] 对象存储上传失败: %s", stream_name, ex, exc_info=True)

    path_for_redis = image_path
    if object_key and not OBJECT_STORAGE_KEEP_LOCAL:
        if image_path and os.path.isfile(image_path):
            try:
                os.remove(image_path)
            except OSError:
                pass
        path_for_redis = ""

    if not redis_manager:
        raise RuntimeError("redis unavailable")

    rec_id = redis_manager.save_detection(
        stream_name=stream_name,
        detection_types=detection_types,
        image_path=path_for_redis,
        timestamp=now,
        object_key=object_key,
        storage_kind=storage_kind,
        extra=extra if isinstance(extra, dict) else None,
        record_id=record_id,
    )
    if rec_id and alert_emails and alert_email_enabled:
        img_for_mail = (
            path_for_redis if path_for_redis and os.path.isfile(path_for_redis) else None
        )
        notify_alert_by_email(
            stream_name=stream_name,
            recipients=alert_emails,
            detection_types=detection_types,
            image_path=img_for_mail,
            timestamp=now,
        )
    webhook_dest = resolved_alert_webhook_urls(
        alert_webhook_urls, stream_enabled=alert_webhook_enabled
    )
    if rec_id and webhook_dest:
        notify_alert_by_webhooks(
            stream_name=stream_name,
            stream_id=stream_id or None,
            webhook_urls=webhook_dest,
            detection_types=detection_types,
            image_path=path_for_redis or None,
            object_key=object_key,
            storage_kind=storage_kind,
            detection_id=rec_id,
            timestamp=now,
            extra=extra if isinstance(extra, dict) else None,
        )
