"""Compose 部署的页面重启：Redis 信号 + 进程退出，由 Docker restart 策略拉起容器。

- 管理端 ``POST /api/restart`` 在 ``VISIONAI_RESTART_MODE=exit`` 时写 Redis 时间戳。
- 各进程（api / worker / alert / sip）启动时调用 :func:`start_restart_watcher`：
  发现信号时间戳晚于本进程启动时间即 ``os._exit(0)``，容器 ``restart: unless-stopped`` 自动拉起。
- 不挂载 docker.sock，容器内无需 Docker CLI。
"""

from __future__ import annotations

import logging
import os
import threading
import time

logger = logging.getLogger(__name__)

_WATCH_INTERVAL_SEC = 2.0
_started = False
_lock = threading.Lock()


def restart_mode() -> str:
    from visionai.config import settings

    return (getattr(settings, "RESTART_MODE", "") or "").strip().lower()


def signal_compose_restart() -> bool:
    """写入重启信号（当前时间戳）。Redis 不可用返回 False。"""
    from visionai.core.redis_manager import redis_manager

    return redis_manager.set_restart_signal(time.time())


def start_restart_watcher(name: str) -> bool:
    """RESTART_MODE=exit 时启动守护线程监听重启信号；其它模式直接返回 False。"""
    global _started
    if restart_mode() != "exit":
        return False
    with _lock:
        if _started:
            return True
        _started = True
    boot_ts = time.time()

    def _watch() -> None:
        from visionai.core.redis_manager import redis_manager

        while True:
            try:
                ts = redis_manager.get_restart_signal()
                if ts > boot_ts:
                    logger.info(
                        "收到页面重启信号（%.3f > 启动 %.3f），进程退出等待容器重启", ts, boot_ts
                    )
                    os._exit(0)
            except Exception:  # noqa: BLE001
                pass
            time.sleep(_WATCH_INTERVAL_SEC)

    t = threading.Thread(target=_watch, name=f"restart-watch-{name}", daemon=True)
    t.start()
    logger.info("页面重启监听已启动（%s）", name)
    return True
