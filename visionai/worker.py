"""流处理 worker：拉流 + 检测（不含 Flask）。

启动：``python -m visionai.worker``
"""

from __future__ import annotations

import logging
import os
import threading
import time

from visionai import __main__ as core
from visionai.config.settings import SAVE_DIR, STREAM_LEASE_ENABLED
from visionai.config.stream_access import stream_should_analyze
from visionai.core import stream_sync
from visionai.core.state_manager import STATUS_OFFLINE, STATUS_ONLINE, set_stream_status
from visionai.core.stream_handler import StreamHandler
from visionai.core.stream_lease import resolve_worker_id, try_acquire_lease
from visionai.utils.logger import setup_logger


def _lease_gate(stream_info: dict) -> bool:
    if not STREAM_LEASE_ENABLED:
        return True
    wid = resolve_worker_id()
    sid = (stream_info.get("id") or stream_info.get("name") or "").strip()
    return try_acquire_lease(sid, wid)


def main() -> None:
    logger = setup_logger()
    logger.info("JXVisionAI stream worker 启动")
    try:
        from visionai.config.settings import describe_inference_backend

        logger.info("推理后端: %s", describe_inference_backend())
    except Exception as ex:  # noqa: BLE001
        logger.warning("无法打印推理后端信息: %s", ex)

    os.makedirs(SAVE_DIR, exist_ok=True)
    worker_id = resolve_worker_id()
    os.environ.setdefault("WORKER_ID", worker_id)
    logger.info("worker_id=%s lease=%s", worker_id, STREAM_LEASE_ENABLED)

    streams = core.get_streams()
    if not streams:
        logger.warning("未从Redis获取到流配置，请检查Redis连接")

    for stream_info in streams:
        set_stream_status(stream_info["name"], STATUS_OFFLINE)

    for stream_info in streams:
        if not stream_should_analyze(stream_info):
            logger.info("视频流未接入分析或已暂停，跳过: %s", stream_info["name"])
            continue
        if not _lease_gate(stream_info):
            logger.info("流租约在其他 worker，跳过: %s", stream_info["name"])
            continue
        t = threading.Thread(
            target=core.run_video_processing, args=(stream_info,), daemon=True
        )
        t.start()
        logger.info("已启动视频流处理线程: %s", stream_info["name"])

    def check_offline_with_lease():
        log = logging.getLogger(__name__)
        wait_sec = 0.0
        while True:
            try:
                kicked = stream_sync.wait_until_next_check(wait_sec)
                if kicked:
                    stream_sync.clear_kick()
                wait_sec = 60.0
                enabled = [s for s in core.get_streams() if stream_should_analyze(s)]
                for stream_info in enabled:
                    name = stream_info["name"]
                    key = core.stream_thread_key(stream_info)
                    with core.threads_lock:
                        if key in core.active_threads:
                            _lease_gate(stream_info)
                            continue
                    if not _lease_gate(stream_info):
                        continue
                    log.info("[离线检测] 尝试为流启动处理线程: %s", name)
                    start_info = stream_info
                    gb = False
                    try:
                        from visionai.core.gb_play import is_gb_stream, prepare_gb_stream

                        gb = is_gb_stream(stream_info)
                        if gb:
                            prepared, err = prepare_gb_stream(stream_info)
                            if err or not prepared:
                                log.warning("[离线检测] 国标点播失败 %s: %s", name, err)
                                set_stream_status(name, STATUS_OFFLINE)
                                continue
                            start_info = prepared
                    except Exception as e:  # noqa: BLE001
                        log.warning("[离线检测] 国标准备失败 %s: %s", name, e)
                        if gb:
                            set_stream_status(name, STATUS_OFFLINE)
                            continue
                    if not gb:
                        sh = StreamHandler(stream_info)
                        if not sh.connect():
                            continue
                        sh.disconnect()
                    with core.threads_lock:
                        if key in core.active_threads:
                            continue
                    if not gb:
                        set_stream_status(name, STATUS_ONLINE)
                    threading.Thread(
                        target=core.run_video_processing,
                        args=(start_info,),
                        daemon=True,
                    ).start()
                    log.info("[离线检测] 已启动流 %s 的处理线程", name)
            except Exception as e:  # noqa: BLE001
                log.error("[离线检测] 错误: %s", e)
                time.sleep(60)

    threading.Thread(target=check_offline_with_lease, daemon=True).start()
    threading.Thread(target=core.check_disabled_stream_status, daemon=True).start()
    threading.Thread(target=core.run_stream_watchdog, daemon=True).start()
    logger.info("stream worker 守护线程已启动，主线程保活")
    while True:
        time.sleep(3600)


if __name__ == "__main__":
    main()
