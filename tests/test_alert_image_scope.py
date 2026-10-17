"""同一秒多路告警时，截图必须按流读取，不能串到别的视频源。"""

import json
import unittest


class _FakeRedis:
    def __init__(self):
        self.store = {}

    def ping(self):
        return True

    def hget(self, key, field):
        return self.store.get(key, {}).get(field)

    def hdel(self, key, field):
        bucket = self.store.get(key) or {}
        if field not in bucket:
            return 0
        del bucket[field]
        return 1


class AlertImageScopeTests(unittest.TestCase):
    def setUp(self):
        from visionai.config.settings import REDIS_KEY_PREFIX
        from visionai.core.redis_manager import redis_manager

        self.mgr = redis_manager
        self.prefix = REDIS_KEY_PREFIX
        self._client = redis_manager._redis_client
        self._streams = redis_manager.get_streams
        fake = _FakeRedis()
        same_id = "1729154260_00"
        fake.store[f"{self.prefix}stream_119"] = {
            same_id: json.dumps(
                {"id": same_id, "stream_id": "stream_119", "image_path": "/snap/119.jpg"}
            )
        }
        fake.store[f"{self.prefix}stream_hik"] = {
            same_id: json.dumps(
                {"id": same_id, "stream_id": "stream_hik", "image_path": "/snap/hik.jpg"}
            )
        }
        redis_manager._redis_client = fake
        redis_manager.get_streams = lambda: [
            {"id": "stream_119"},
            {"id": "stream_hik"},
        ]

    def tearDown(self):
        self.mgr._redis_client = self._client
        self.mgr.get_streams = self._streams

    def test_unscoped_lookup_returns_first_stream(self):
        doc = self.mgr.get_detection_by_id("1729154260_00")
        self.assertEqual(doc["image_path"], "/snap/119.jpg")

    def test_scoped_lookup_returns_that_stream(self):
        doc = self.mgr.get_detection_by_id("1729154260_00", stream_id="stream_hik")
        self.assertEqual(doc["image_path"], "/snap/hik.jpg")

    def test_scoped_delete_leaves_the_other_stream(self):
        self.assertTrue(
            self.mgr.delete_detection_by_id("1729154260_00", stream_id="stream_hik")
        )
        self.assertIsNone(
            self.mgr.get_detection_by_id("1729154260_00", stream_id="stream_hik")
        )
        kept = self.mgr.get_detection_by_id("1729154260_00", stream_id="stream_119")
        self.assertEqual(kept["image_path"], "/snap/119.jpg")


if __name__ == "__main__":
    unittest.main()
