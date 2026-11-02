"""告警短录像帧包、推理地址和专模版本回退。"""

import tempfile
import unittest
from pathlib import Path


class ClipAndPlanTest(unittest.TestCase):
    def test_jclip_roundtrip(self):
        from visionai.core.alert_clip import decode_jclip, encode_jclip

        blob = encode_jclip([b"jpeg-a", b"jpeg-b"], 4.5)
        parsed = decode_jclip(blob)
        self.assertIsNotNone(parsed)
        self.assertAlmostEqual(parsed["fps"], 4.5, places=3)
        self.assertEqual(parsed["frames"], [b"jpeg-a", b"jpeg-b"])

    def test_frame_ring_drops_old(self):
        from visionai.core.alert_clip import FrameRing

        class _Frame:
            shape = (8, 8, 3)

            def __getitem__(self, _item):
                return self

        ring = FrameRing(seconds=5, min_interval=0.2)
        frame = _Frame()
        ring.push(frame, now=0)
        ring.push(frame, now=1)
        ring.push(frame, now=2)
        ring.push(frame, now=10)
        self.assertEqual(len(ring.frames()), 2)

    def test_clip_enabled_defaults_on(self):
        from visionai.core.alert_clip import normalize_alert_clip_enabled

        self.assertTrue(normalize_alert_clip_enabled(None))
        self.assertTrue(normalize_alert_clip_enabled(True))
        self.assertFalse(normalize_alert_clip_enabled(False))
        self.assertFalse(normalize_alert_clip_enabled("off"))

    def test_analyze_url_plan(self):
        from visionai.core.inference_source import inference_plan, normalize_analyze_url

        self.assertEqual(normalize_analyze_url("http://example/a"), "")
        self.assertTrue(normalize_analyze_url("rtsp://cam/sub").startswith("rtsp://"))
        primary = inference_plan({"id": "stream_a", "url": "rtsp://cam/main"})
        self.assertEqual(primary["key"], "primary")
        self.assertFalse(primary["use_analyze"])
        sub = inference_plan(
            {"id": "stream_a", "url": "rtsp://cam/main", "analyze_url": "rtsp://cam/sub"}
        )
        self.assertTrue(sub["use_analyze"])
        self.assertEqual(sub["zlm_id"], "stream_a__an")
        self.assertIn("rtsp://cam/sub", sub["source"])


class SpecialistVersionTest(unittest.TestCase):
    def test_second_deploy_can_roll_back(self):
        from visionai.config.specialists import (
            activate_specialist_version,
            deploy_specialist,
            load_specialist,
        )

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            first = root / "a.pt"
            second = root / "b.pt"
            first.write_bytes(b"weights-v1")
            second.write_bytes(b"weights-v2")
            common = dict(
                repo_root=root,
                key="helmet_custom",
                kind="scene",
                name_zh="安全帽",
                classes=["hat"],
                backup=True,
            )
            one = deploy_specialist(weights_path=first, origin="trained", **common)
            self.assertTrue(one["success"], one)
            two = deploy_specialist(weights_path=second, origin="trained", **common)
            self.assertTrue(two["success"], two)
            active = root / "models" / "specialists" / "helmet_custom" / "model.pt"
            self.assertEqual(active.read_bytes(), b"weights-v2")
            meta = load_specialist("helmet_custom", root)
            versions = meta["versions"]
            self.assertGreaterEqual(len(versions), 2)
            previous = [v for v in versions if v["id"] != meta["active_version"]][0]
            rolled = activate_specialist_version("helmet_custom", previous["id"], root)
            self.assertTrue(rolled["success"], rolled)
            self.assertEqual(active.read_bytes(), b"weights-v1")
            again = load_specialist("helmet_custom", root)
            self.assertEqual(again["active_version"], previous["id"])


if __name__ == "__main__":
    unittest.main()
