"""页面重启（Compose exit 模式）：Redis 信号读写、watcher 模式门槛、端点行为。"""

from __future__ import annotations

import unittest
from unittest.mock import patch


class _FakeRedis:
    def __init__(self):
        self.store = {}

    def set(self, k, v):
        self.store[k] = v

    def get(self, k):
        return self.store.get(k)


class RestartSignalRedisTests(unittest.TestCase):
    def test_set_get_roundtrip(self):
        from visionai.core.redis_manager import redis_manager

        fake = _FakeRedis()
        with patch.object(redis_manager, "_redis_client", fake):
            self.assertTrue(redis_manager.set_restart_signal(123.5))
            self.assertAlmostEqual(redis_manager.get_restart_signal(), 123.5)

    def test_get_returns_zero_when_no_client(self):
        from visionai.core.redis_manager import redis_manager

        with patch.object(redis_manager, "_redis_client", None):
            self.assertEqual(redis_manager.get_restart_signal(), 0.0)
            self.assertFalse(redis_manager.set_restart_signal(1.0))

    def test_get_returns_zero_when_key_missing(self):
        from visionai.core.redis_manager import redis_manager

        with patch.object(redis_manager, "_redis_client", _FakeRedis()):
            self.assertEqual(redis_manager.get_restart_signal(), 0.0)


class RestartWatcherTests(unittest.TestCase):
    def test_watcher_noop_unless_exit_mode(self):
        import visionai.utils.restart_watch as rw

        with patch("visionai.config.settings.RESTART_MODE", ""):
            self.assertFalse(rw.start_restart_watcher("t1"))
        with patch("visionai.config.settings.RESTART_MODE", "script"):
            self.assertFalse(rw.start_restart_watcher("t2"))

    def test_signal_uses_redis_manager(self):
        import visionai.utils.restart_watch as rw

        with patch("visionai.core.redis_manager.redis_manager") as mgr:
            mgr.set_restart_signal.return_value = True
            self.assertTrue(rw.signal_compose_restart())
            mgr.set_restart_signal.assert_called_once()


class RestartEndpointTests(unittest.TestCase):
    def setUp(self):
        from visionai.web.app import app

        app.config["TESTING"] = True
        self.app = app
        self.client = app.test_client()

    def _login(self):
        with self.client.session_transaction() as s:
            s["logged_in"] = True
            s["secret_fp"] = str(hash("test-secret"))

    def test_exit_mode_signals_and_succeeds(self):
        with patch("visionai.web.app.SECRET", "test-secret"), patch(
            "visionai.config.settings.RESTART_MODE", "exit"
        ), patch(
            "visionai.utils.restart_watch.signal_compose_restart", return_value=True
        ) as sig:
            self._login()
            resp = self.client.post("/api/restart")
            self.assertEqual(resp.status_code, 200)
            data = resp.get_json()
            self.assertTrue(data.get("success"))
            sig.assert_called_once()

    def test_exit_mode_redis_down_is_500(self):
        with patch("visionai.web.app.SECRET", "test-secret"), patch(
            "visionai.config.settings.RESTART_MODE", "exit"
        ), patch("visionai.utils.restart_watch.signal_compose_restart", return_value=False):
            self._login()
            resp = self.client.post("/api/restart")
            self.assertEqual(resp.status_code, 500)
            self.assertFalse(resp.get_json().get("success"))

    def test_default_mode_still_forbidden(self):
        with patch("visionai.web.app.SECRET", "test-secret"), patch(
            "visionai.config.settings.RESTART_MODE", ""
        ), patch("visionai.web.app.ALLOW_PROCESS_RESTART", False):
            self._login()
            resp = self.client.post("/api/restart")
            self.assertEqual(resp.status_code, 403)
            self.assertFalse(resp.get_json().get("success"))


if __name__ == "__main__":
    unittest.main()
