"""Web 保存流配置后唤醒后台线程检查，避免最长等待一个轮询周期。"""

import threading

_kick = threading.Event()


def notify_streams_changed() -> None:
    _kick.set()


def wait_until_next_check(timeout_sec: float) -> bool:
    """阻塞直至 notify 或超时。返回 True 表示被唤醒（配置变更）。"""
    return _kick.wait(timeout_sec)


def clear_kick() -> None:
    _kick.clear()
