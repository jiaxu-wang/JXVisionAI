"""OSS remediation: auth 401, stream status mapping, secrets, HA lease, GB overlay."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch


class StreamStatusMappingTests(unittest.TestCase):
    def test_legacy_chinese_maps_to_english(self):
        from visionai.core.state_manager import (
            STATUS_OFFLINE,
            STATUS_ONLINE,
            is_stream_online,
            normalize_stream_status,
        )

        self.assertEqual(normalize_stream_status("在线"), STATUS_ONLINE)
        self.assertEqual(normalize_stream_status("离线"), STATUS_OFFLINE)
        self.assertEqual(normalize_stream_status("online"), STATUS_ONLINE)
        self.assertEqual(normalize_stream_status("OFFLINE"), STATUS_OFFLINE)
        self.assertTrue(is_stream_online("在线"))
        self.assertFalse(is_stream_online("离线"))
        self.assertTrue(is_stream_online("online"))


class SecretGuardTests(unittest.TestCase):
    def test_require_login_secret_rejects_empty(self):
        from visionai.utils.insecure_defaults import require_login_secret

        with self.assertRaises(SystemExit):
            require_login_secret("")
        with self.assertRaises(SystemExit):
            require_login_secret("   ")

    def test_known_public_secrets_are_flagged(self):
        from visionai.utils.insecure_defaults import is_insecure_secret

        self.assertTrue(is_insecure_secret("123456-bb6b-4889-a715-d9eb2d1925cc"))
        self.assertTrue(is_insecure_secret("VisionAI@2026"))
        self.assertTrue(is_insecure_secret("jxvisionai-zlm-a7f3c91e4b2d6e80"))
        self.assertFalse(is_insecure_secret("a-unique-production-secret"))


class LoginRequiredApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from visionai.web.app import app

        app.config["TESTING"] = True
        cls.client = app.test_client()

    def test_api_streams_unauthorized_json(self):
        resp = self.client.get("/api/streams", headers={"Accept": "application/json"})
        self.assertEqual(resp.status_code, 401)
        data = resp.get_json()
        self.assertIsInstance(data, dict)
        self.assertFalse(data.get("success"))
        self.assertNotIn("text/html", (resp.content_type or "").lower())

    def test_restart_unauthorized_is_json(self):
        resp = self.client.post("/api/restart", headers={"Accept": "application/json"})
        self.assertEqual(resp.status_code, 401)
        data = resp.get_json()
        self.assertFalse(data.get("success"))

    def test_index_redirects_to_login(self):
        resp = self.client.get("/", follow_redirects=False)
        self.assertEqual(resp.status_code, 302)


class StreamLeaseHaTests(unittest.TestCase):
    def test_lease_disabled_allows_processing(self):
        from visionai.core.stream_lease import try_acquire_lease

        with patch("visionai.config.settings.STREAM_LEASE_ENABLED", False):
            self.assertTrue(try_acquire_lease("s1", "w1"))

    def test_lease_enabled_redis_error_refuses(self):
        from visionai.core.stream_lease import try_acquire_lease

        client = MagicMock()
        client.set.side_effect = ConnectionError("redis down")
        rm = MagicMock()
        rm._redis_client = client
        with patch("visionai.config.settings.STREAM_LEASE_ENABLED", True), patch(
            "visionai.config.settings.STREAM_LEASE_TTL_SEC", 30
        ), patch("visionai.core.redis_manager.redis_manager", rm):
            self.assertFalse(try_acquire_lease("s1", "w1"))

    def test_lease_enabled_missing_client_refuses(self):
        from visionai.core.stream_lease import try_acquire_lease

        rm = MagicMock()
        rm._redis_client = None
        with patch("visionai.config.settings.STREAM_LEASE_ENABLED", True), patch(
            "visionai.core.redis_manager.redis_manager", rm
        ):
            self.assertFalse(try_acquire_lease("s1", "w1"))


class GbOverlayTests(unittest.TestCase):
    def test_missing_runtime_is_offline(self):
        from visionai.core.gb28181_store import overlay_sip_runtime

        devices = [
            {
                "sip_user": "34020000001320000001",
                "status": "online",
                "channels": [{"channel_id": "1", "status": "online"}],
            }
        ]
        out = overlay_sip_runtime(devices, {})
        self.assertEqual(out[0]["status"], "offline")
        self.assertEqual(out[0]["channels"][0]["status"], "offline")

    def test_boot_id_mismatch_is_offline(self):
        from visionai.core.gb28181_store import overlay_sip_runtime

        devices = [{"sip_user": "dev1", "status": "online", "channels": []}]
        runtime = {
            "dev1": {
                "status": "online",
                "sip_boot_id": "old",
                "last_keepalive_at": "2099-01-01 00:00:00",
                "last_register_at": "2099-01-01 00:00:00",
            }
        }
        out = overlay_sip_runtime(devices, runtime, sip_boot_id="new")
        self.assertEqual(out[0]["status"], "offline")

    def test_matching_boot_can_stay_online_if_fresh(self):
        from visionai.core.gb28181_store import overlay_sip_runtime
        from visionai.utils.timeutil import app_now

        now = app_now().strftime("%Y-%m-%d %H:%M:%S")
        devices = [{"sip_user": "dev1", "channels": [{"channel_id": "1"}]}]
        runtime = {
            "dev1": {
                "status": "online",
                "sip_boot_id": "boot-a",
                "last_keepalive_at": now,
                "last_register_at": now,
            }
        }
        out = overlay_sip_runtime(devices, runtime, sip_boot_id="boot-a")
        self.assertEqual(out[0]["status"], "online")


class TrainingFrameImportTests(unittest.TestCase):
    def test_training_routes_use_shared_snap_helper(self):
        import visionai.web.training_routes as tr
        from visionai.core.stream_frame import read_frame_bgr_prefer_snap

        self.assertIs(tr.read_frame_bgr_prefer_snap, read_frame_bgr_prefer_snap)
        self.assertFalse(hasattr(tr, "read_rtsp_frame_bgr"))


if __name__ == "__main__":
    unittest.main()
