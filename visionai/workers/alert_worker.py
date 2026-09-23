"""告警队列消费者：``python -m visionai.workers.alert_worker``。"""

from __future__ import annotations

import logging
import signal
import time

from visionai.config.settings import ALERT_QUEUE_BLOCK_SEC, LOG_DIR
from visionai.core.alert_queue import brpop_alert_job, process_alert_job, requeue_or_dead
from visionai.utils.logger import setup_logger

_stop = False


def _handle_sig(*_args):
    global _stop
    _stop = True


def main() -> None:
    setup_logger()
    logger = logging.getLogger("visionai.alert_worker")
    signal.signal(signal.SIGINT, _handle_sig)
    signal.signal(signal.SIGTERM, _handle_sig)
    from visionai.utils.restart_watch import start_restart_watcher

    start_restart_watcher("alert")
    logger.info("alert_worker started (log_dir=%s)", LOG_DIR)
    while not _stop:
        job = brpop_alert_job(timeout=ALERT_QUEUE_BLOCK_SEC)
        if not job:
            continue
        try:
            process_alert_job(job)
        except Exception as e:  # noqa: BLE001
            logger.error("alert job failed: %s", e, exc_info=True)
            requeue_or_dead(job)
            time.sleep(0.5)
    logger.info("alert_worker stopped")


if __name__ == "__main__":
    main()
