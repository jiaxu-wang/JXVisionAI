"""人物入侵区域：点在多边形内、布防时段、以及平台事件码只在区域内给出。"""

import unittest
from datetime import datetime
from unittest.mock import patch


class _Unit:
    def __init__(self, label):
        self.label = label


class IntrusionZoneTest(unittest.TestCase):
    def test_point_in_polygon(self):
        from visionai.core.intrusion_zone import point_in_polygon

        square = [[0.2, 0.2], [0.8, 0.2], [0.8, 0.8], [0.2, 0.8]]
        self.assertTrue(point_in_polygon(0.5, 0.5, square))
        self.assertFalse(point_in_polygon(0.1, 0.5, square))

    def test_no_region_keeps_person_without_event_code(self):
        from visionai.core.intrusion_zone import filter_person_zone

        person = _Unit("人物")
        face = _Unit("人脸识别")
        out = filter_person_zone(
            [person, face],
            {"by_class": {0: [{"box": (10, 10, 40, 80)}]}},
            (100, 100, 3),
            {"regions": [], "schedule_all": True},
            datetime(2026, 10, 28, 3, 0, 0),
        )
        self.assertEqual([u.label for u, _ in out], ["人物", "人脸识别"])
        self.assertTrue(all(code is None for _, code in out))

    def test_inside_armed_sets_190_outside_and_disarmed_drop(self):
        from visionai.core.intrusion_zone import (
            PLATFORM_EVENT_INTRUSION,
            filter_person_zone,
        )

        zone = {
            "regions": [{"points": [[0.0, 0.0], [0.5, 0.0], [0.5, 0.5], [0.0, 0.5]]}],
            "schedule_all": False,
            "schedule": [[h == 10 for h in range(24)] for _ in range(7)],
        }
        inside = {"by_class": {0: [{"box": (10, 10, 30, 30)}]}}
        outside = {"by_class": {0: [{"box": (60, 60, 90, 90)}]}}
        face = _Unit("人脸识别")
        person = _Unit("人物")
        armed = datetime(2026, 10, 28, 10, 0, 0)
        kept = filter_person_zone([person, face], inside, (100, 100, 3), zone, armed)
        self.assertEqual(
            [(u.label, code) for u, code in kept],
            [("人物", PLATFORM_EVENT_INTRUSION), ("人脸识别", None)],
        )
        dropped = filter_person_zone([person, face], outside, (100, 100, 3), zone, armed)
        self.assertEqual([u.label for u, _ in dropped], ["人脸识别"])
        night = datetime(2026, 10, 28, 3, 0, 0)
        disarmed = filter_person_zone([person, face], inside, (100, 100, 3), zone, night)
        self.assertEqual([u.label for u, _ in disarmed], ["人脸识别"])

    def test_webhook_includes_platform_event_type_only_when_set(self):
        captured = {}

        def fake_thread(target, args=(), kwargs=None, **_):
            captured["payload"] = args[1]

            class _T:
                def start(self):
                    pass

            return _T()

        with patch("visionai.utils.alert_webhook.threading.Thread", side_effect=fake_thread), patch(
            "visionai.utils.alert_webhook._send_webhooks_sync"
        ):
            from visionai.utils.alert_webhook import notify_alert_by_webhooks

            notify_alert_by_webhooks(
                stream_name="cam",
                stream_id="s1",
                webhook_urls=["http://127.0.0.1:9/hook"],
                detection_types=["人物"],
                image_path="",
                object_key="",
                storage_kind="",
                detection_id="d1",
                timestamp=datetime(2026, 10, 28, 10, 0, 0),
                platform_event_type=190,
            )
        self.assertEqual(captured["payload"]["platform_event_type"], 190)
        captured.clear()
        with patch("visionai.utils.alert_webhook.threading.Thread", side_effect=fake_thread), patch(
            "visionai.utils.alert_webhook._send_webhooks_sync"
        ):
            from visionai.utils.alert_webhook import notify_alert_by_webhooks

            notify_alert_by_webhooks(
                stream_name="cam",
                stream_id="s1",
                webhook_urls=["http://127.0.0.1:9/hook"],
                detection_types=["人物"],
                image_path="",
                object_key="",
                storage_kind="",
                detection_id="d1",
                timestamp=datetime(2026, 10, 28, 10, 0, 0),
            )
        self.assertNotIn("platform_event_type", captured["payload"])


if __name__ == "__main__":
    unittest.main()
