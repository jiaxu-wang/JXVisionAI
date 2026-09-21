"""人脸库身份ID 与告警 person_id 不允许为空。"""

from __future__ import annotations

import unittest


class FaceIdentityTests(unittest.TestCase):
    def test_resolve_empty_person_id(self):
        from visionai.core.face_library import UNKNOWN_PERSON_ID, resolve_person_id

        self.assertEqual(resolve_person_id(None), UNKNOWN_PERSON_ID)
        self.assertEqual(resolve_person_id(""), UNKNOWN_PERSON_ID)
        self.assertEqual(resolve_person_id("EMP001"), "EMP001")

    def test_normalize_identity_id(self):
        from visionai.core.face_library import normalize_identity_id

        self.assertEqual(normalize_identity_id(" EMP 001 "), "EMP001")
        self.assertEqual(normalize_identity_id(""), "")

    def test_validate_identity_id(self):
        from visionai.core.face_library import validate_identity_id

        self.assertEqual(validate_identity_id(" EMP001 "), "EMP001")
        with self.assertRaises(ValueError):
            validate_identity_id("")
        with self.assertRaises(ValueError):
            validate_identity_id("unknown")

    def test_alert_unit_fills_unknown_id(self):
        from visionai.config.detection_catalog import FACE_RECOG_KEY
        from visionai.core.alert_units import collect_alert_units

        flags = {FACE_RECOG_KEY: True}
        detections = {
            "by_class": {},
            "behaviors": {
                FACE_RECOG_KEY: {
                    "alert": True,
                    "trigger_types": ["unknown"],
                    "alert_matches": [
                        {
                            "person_id": None,
                            "person_name": "陌生人",
                            "similarity": 0.3293,
                            "match_type": "unknown",
                            "box": [1, 2, 3, 4],
                        }
                    ],
                }
            },
        }
        units = collect_alert_units(flags, detections)
        self.assertEqual(len(units), 1)
        hit = units[0].extra["face_recognition"]["alert_matches"][0]
        self.assertEqual(hit["person_id"], "unknown")
        self.assertEqual(hit["identity_id"], "unknown")
        self.assertEqual(hit["similarity"], 0.3293)
        self.assertEqual(hit["match_type"], "unknown")


if __name__ == "__main__":
    unittest.main()
