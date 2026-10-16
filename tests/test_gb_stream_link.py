"""国标分析流按设备 / 通道依附，删除时要能找全。"""

from __future__ import annotations

import unittest


class GbStreamLinkTests(unittest.TestCase):
    def test_streams_for_device_and_channel(self):
        from visionai.core.gb28181_store import streams_for_gb

        streams = [
            {
                "id": "s1",
                "name": "门口",
                "gb28181": {"device_id": "3401", "channel_id": "ch1"},
            },
            {
                "id": "s2",
                "name": "大厅",
                "gb28181": {"sip_user": "3401", "channel_id": "ch2"},
            },
            {
                "id": "s3",
                "name": "别的设备",
                "gb28181": {"device_id": "9999", "channel_id": "ch1"},
            },
            {"id": "s4", "name": "rtsp", "url": "rtsp://x"},
        ]
        names = [s["name"] for s in streams_for_gb(streams, "3401")]
        self.assertEqual(names, ["门口", "大厅"])
        one = streams_for_gb(streams, "3401", "ch2")
        self.assertEqual([s["id"] for s in one], ["s2"])
        self.assertEqual(streams_for_gb(streams, ""), [])


if __name__ == "__main__":
    unittest.main()
