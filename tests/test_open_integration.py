"""开放 API 鉴权、webhook 合并与 401 JSON（不 redirect）。"""

from __future__ import annotations

import unittest
from unittest.mock import patch

from flask import Flask


class OpenApiAuthTests(unittest.TestCase):
    def test_sign_and_verify_token(self):
        with patch("visionai.config.settings.OPEN_API_KEY", "test-key-abcdef"):
            from visionai.utils.open_api_auth import (
                sign_alert_image_token,
                verify_alert_image_token,
            )

            tok = sign_alert_image_token("det-1")
            self.assertTrue(tok)
            self.assertTrue(verify_alert_image_token("det-1", tok))
            self.assertFalse(verify_alert_image_token("det-1", "nope"))
            self.assertFalse(verify_alert_image_token("det-2", tok))

    def test_image_url_requires_base(self):
        with patch("visionai.config.settings.OPEN_API_KEY", "k"), patch(
            "visionai.config.settings.PUBLIC_BASE_URL", "http://jx:15000"
        ):
            from visionai.utils.open_api_auth import build_alert_image_url

            url = build_alert_image_url("abc")
            self.assertTrue(url.startswith("http://jx:15000/api/open/v1/alerts/abc/image?token="))


class WebhookMergeTests(unittest.TestCase):
    def test_global_url_without_per_stream(self):
        with patch(
            "visionai.config.settings.OUTBOUND_WEBHOOK_URL",
            "http://partner.example:8080/hooks/visionai-alert",
        ):
            from visionai.utils.alert_webhook import resolved_alert_webhook_urls

            urls = resolved_alert_webhook_urls([], stream_enabled=False)
            self.assertEqual(
                urls, ["http://partner.example:8080/hooks/visionai-alert"]
            )

    def test_merge_dedup(self):
        dest = "http://partner.example:8080/hooks/visionai-alert"
        with patch("visionai.config.settings.OUTBOUND_WEBHOOK_URL", dest):
            from visionai.utils.alert_webhook import resolved_alert_webhook_urls

            urls = resolved_alert_webhook_urls([dest, "http://other/hook"], stream_enabled=True)
            self.assertEqual(urls, [dest, "http://other/hook"])

    def test_payload_has_image_url(self):
        captured = {}

        def fake_thread(target, args, name, daemon):
            captured["payload"] = args[1]
            class _T:
                def start(self):
                    target(*args)
            return _T()

        with patch("visionai.config.settings.OPEN_API_KEY", "k"), patch(
            "visionai.config.settings.PUBLIC_BASE_URL", "http://jx:15000"
        ), patch("visionai.utils.alert_webhook.threading.Thread", side_effect=fake_thread), patch(
            "visionai.utils.alert_webhook._send_webhooks_sync"
        ):
            from datetime import datetime
            from visionai.utils.alert_webhook import notify_alert_by_webhooks

            notify_alert_by_webhooks(
                stream_name="cam1",
                stream_id="sid-1",
                webhook_urls=["http://127.0.0.1:9/hook"],
                detection_types=["入侵"],
                image_path="",
                object_key="",
                storage_kind="",
                detection_id="d1",
                timestamp=datetime(2026, 1, 2, 3, 4, 5),
            )
            self.assertEqual(captured["payload"]["event"], "visionai.alert")
            self.assertEqual(captured["payload"]["detection_types"], ["入侵"])
            self.assertIn("detection_type_labels", captured["payload"])
            self.assertIn("locale", captured["payload"])
            self.assertIn("image_url", captured["payload"])
            self.assertIn("/api/open/v1/alerts/d1/image", captured["payload"]["image_url"])


class IniIntegrationSectionTests(unittest.TestCase):
    def test_write_location(self):
        from visionai.config.ini_sections import write_location, canonicalize

        self.assertEqual(write_location("open_api_key"), ("integration", "open_api_key"))
        self.assertEqual(canonicalize("integration", "public_base_url"), "public_base_url")
        self.assertEqual(canonicalize("integration", "outbound_webhook_url"), "outbound_webhook_url")
        self.assertEqual(
            write_location("embed_frame_ancestors"),
            ("integration", "embed_frame_ancestors"),
        )
        self.assertEqual(
            write_location("platform_embed_url"),
            ("integration", "platform_embed_url"),
        )
        self.assertEqual(canonicalize("integration", "platform_embed_url"), "platform_embed_url")


class OpenApiHttpTests(unittest.TestCase):
    def setUp(self):
        from visionai.web.open_api import init_open_api

        self.app = Flask(__name__)
        init_open_api(self.app)
        self.client = self.app.test_client()

    def test_missing_key_is_401_json_not_redirect(self):
        with patch("visionai.web.open_api.configured_open_api_key", return_value=""):
            r = self.client.get("/api/open/v1/streams")
        self.assertEqual(r.status_code, 401)
        self.assertTrue(r.is_json)
        self.assertFalse(r.headers.get("Location"))
        self.assertIn("success", r.get_json())

    def test_wrong_key_401_json(self):
        with patch("visionai.web.open_api.configured_open_api_key", return_value="secret"), patch(
            "visionai.web.open_api.api_key_matches", return_value=False
        ):
            r = self.client.get("/api/open/v1/streams", headers={"X-Api-Key": "nope"})
        self.assertEqual(r.status_code, 401)
        self.assertTrue(r.is_json)
        body = r.get_json()
        self.assertFalse(body.get("success"))

    def test_streams_filters_analyze(self):
        streams = [
            {"id": "a", "name": "on", "analyze": True, "enabled": True, "access_method": "rtsp_url"},
            {"id": "b", "name": "off", "analyze": False, "enabled": True, "access_method": "rtsp_url"},
        ]

        class _RM:
            def get_streams(self):
                return streams

        with patch("visionai.web.open_api.configured_open_api_key", return_value="secret"), patch(
            "visionai.web.open_api.api_key_matches", return_value=True
        ), patch("visionai.config.settings.ZLM_ENABLED", False), patch(
            "visionai.core.redis_manager.redis_manager", _RM()
        ), patch(
            "visionai.web.open_api._status_label", return_value="离线"
        ):
            r = self.client.get("/api/open/v1/streams", headers={"X-Api-Key": "secret"})
        self.assertEqual(r.status_code, 200)
        data = r.get_json()["data"]
        self.assertEqual([x["id"] for x in data], ["a"])


class EmbedTokenTests(unittest.TestCase):
    def test_issue_and_consume_once(self):
        from visionai.utils.embed_token import consume_embed_token, issue_embed_token

        tok = issue_embed_token()
        self.assertTrue(tok)
        self.assertTrue(consume_embed_token(tok))
        self.assertFalse(consume_embed_token(tok))

    def test_parse_ancestors(self):
        from visionai.utils.embed_token import parse_frame_ancestors

        self.assertEqual(
            parse_frame_ancestors("http://a:1, https://b/  javascript:alert(1)"),
            ["http://a:1", "https://b"],
        )

    def test_embed_token_http(self):
        from visionai.web.open_api import init_open_api

        app = Flask(__name__)
        init_open_api(app)
        client = app.test_client()
        issued = []

        def fake_issue():
            issued.append("x")
            return "tok-1"

        with patch("visionai.web.open_api.configured_open_api_key", return_value="secret"), patch(
            "visionai.web.open_api.api_key_matches", return_value=True
        ), patch("visionai.web.open_api.issue_embed_token", side_effect=fake_issue), patch(
            "visionai.web.open_api.build_embed_url",
            return_value="http://jx:15000/embed?token=tok-1",
        ):
            r = client.post("/api/open/v1/embed-token", headers={"X-Api-Key": "secret"})
        self.assertEqual(r.status_code, 200)
        body = r.get_json()
        self.assertTrue(body.get("success"))
        self.assertEqual(body.get("embed_url"), "http://jx:15000/embed?token=tok-1")
        self.assertEqual(issued, ["x"])


if __name__ == "__main__":
    unittest.main()
