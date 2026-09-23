"""国标 SIP 信令进程：``python -m visionai.sip``。"""

from __future__ import annotations

import asyncio
import logging

from visionai.core.sip.server import SipStack
from visionai.utils.logger import setup_logger


def main() -> None:
    setup_logger()
    logger = logging.getLogger("visionai.sip")
    logger.info("JXVisionAI SIP 信令启动")
    from visionai.utils.restart_watch import start_restart_watcher

    start_restart_watcher("sip")
    try:
        asyncio.run(SipStack().run())
    except KeyboardInterrupt:
        logger.info("SIP 已停止")


if __name__ == "__main__":
    main()
