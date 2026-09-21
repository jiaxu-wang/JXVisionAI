"""告警类型展示名跟随 [ui] language。"""

from __future__ import annotations

import unittest


class TypeDisplayTests(unittest.TestCase):
    def test_zh_passthrough(self):
        from visionai.utils.type_display import display_detection_types

        raw = ["人脸识别", "人员聚集", "玩手机"]
        self.assertEqual(display_detection_types(raw, "zh"), raw)

    def test_en_builtin_and_suffix(self):
        from visionai.utils.type_display import display_type_label

        self.assertEqual(display_type_label("人脸识别", "en"), "Face recognition")
        self.assertEqual(display_type_label("人员聚集", "en"), "Crowd gathering")
        self.assertEqual(display_type_label("玩手机", "en"), "Using phone")
        self.assertEqual(display_type_label("车牌识别: 库内", "en"), "License plate: known")
        self.assertEqual(
            display_type_label("车牌识别: 陌生车牌", "en"),
            "License plate: unknown plate",
        )
        self.assertEqual(display_type_label("人脸识别:张三", "en"), "Face recognition: 张三")
        self.assertEqual(
            display_type_label("疲劳驾驶 · 闭眼占比高/打哈欠", "en"),
            "Fatigue driving · high PERCLOS/yawning",
        )

    def test_en_coco_person(self):
        from visionai.utils.type_display import display_type_label

        self.assertEqual(display_type_label("人物", "en"), "person")

    def test_unknown_stays(self):
        from visionai.utils.type_display import display_type_label

        self.assertEqual(display_type_label("入侵", "en"), "入侵")


class WebhookLocalePayloadTests(unittest.TestCase):
    def test_payload_has_localized_labels(self):
        from datetime import datetime
        from unittest.mock import patch

        captured = {}

        def fake_thread(target, args=(), kwargs=None, **_):
            captured["payload"] = args[1]

            class _T:
                def start(self):
                    pass

            return _T()

        with patch("visionai.utils.alert_webhook.threading.Thread", side_effect=fake_thread), patch(
            "visionai.utils.type_display.alert_ui_locale", return_value="en"
        ), patch("visionai.utils.alert_webhook._send_webhooks_sync"):
            from visionai.utils.alert_webhook import notify_alert_by_webhooks

            notify_alert_by_webhooks(
                stream_name="cam1",
                stream_id="sid-1",
                webhook_urls=["http://127.0.0.1:9/hook"],
                detection_types=["人脸识别", "人员聚集"],
                image_path="",
                object_key="",
                storage_kind="",
                detection_id="d1",
                timestamp=datetime(2026, 1, 2, 3, 4, 5),
            )
        payload = captured["payload"]
        self.assertEqual(payload["detection_types"], ["人脸识别", "人员聚集"])
        self.assertEqual(payload["detection_type_labels"], ["Face recognition", "Crowd gathering"])
        self.assertEqual(payload["locale"], "en")


if __name__ == "__main__":
    unittest.main()
