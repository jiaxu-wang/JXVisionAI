"""突发拉流：窗结束断开；国标发 BYE。"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


def stop_gb_play(stream_info: Optional[Dict[str, Any]]) -> None:
    try:
        from visionai.core.gb_play import gb_ids_from_stream, is_gb_stream
        from visionai.core.sip import cmd as sip_cmd

        if not is_gb_stream(stream_info):
            return
        device_id, channel_id = gb_ids_from_stream(stream_info)
        if not device_id or not channel_id:
            return
        sip_cmd.enqueue_cmd("bye", device_id=device_id, channel_id=channel_id)
        logger.info(
            "DMS burst BYE %s/%s",
            device_id,
            channel_id,
        )
    except Exception as e:  # noqa: BLE001
        logger.warning("DMS burst BYE failed: %s", e)


def start_gb_play(stream_info: Dict[str, Any]) -> Dict[str, Any]:
    from visionai.core.gb_play import prepare_gb_stream

    prepared, err = prepare_gb_stream(stream_info, force=True)
    if err or not prepared:
        return {"ok": False, "message": err or "国标点播失败"}
    return {"ok": True, "stream_info": prepared}
