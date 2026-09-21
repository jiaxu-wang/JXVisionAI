"""告警截图读取：对象存储优先，回退本地路径。"""

from __future__ import annotations

import os
from typing import Optional, Tuple

from flask import Response, send_file


def detection_image_response(detection_id: str) -> Tuple[Optional[Response], int]:
    """返回 (response, status)。404/503 时 response 为 None。"""
    from visionai.core.object_storage import get_object_storage
    from visionai.core.redis_manager import redis_manager

    if not redis_manager:
        return None, 503
    doc = redis_manager.get_detection_by_id(detection_id)
    if not doc:
        return None, 404
    if doc.get("object_key"):
        st = get_object_storage()
        if st:
            try:
                body = st.get_object_bytes(doc["object_key"])
                return Response(body, mimetype="image/jpeg"), 200
            except Exception:  # noqa: BLE001
                pass
    ip = doc.get("image_path") or ""
    if ip and os.path.isfile(ip):
        return send_file(ip, mimetype="image/jpeg"), 200
    if ip:
        project_root = os.path.dirname(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        )
        candidates = [
            ip,
            os.path.join(project_root, ip.lstrip("./")),
            os.path.join(project_root, "snapshots", os.path.basename(ip)),
        ]
        for cand in candidates:
            if cand and os.path.isfile(cand):
                return send_file(cand, mimetype="image/jpeg"), 200
    return None, 404
