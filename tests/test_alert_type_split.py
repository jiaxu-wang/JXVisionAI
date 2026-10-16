"""一轮多类型告警拆成独立记录，截图只含该类框。"""

from __future__ import annotations

import unittest

import numpy as np

from visionai.config.detection_catalog import FACE_RECOG_KEY, GATHER_KEY
from visionai.core.alert_units import collect_alert_units, render_alert_frame


def _flags(**keys):
    d = {GATHER_KEY: False, FACE_RECOG_KEY: False, "0": False}
    d.update(keys)
    return d


class AlertTypeSplitTests(unittest.TestCase):
    def test_split_gather_and_two_face_types(self):
        flags = _flags(**{GATHER_KEY: True, FACE_RECOG_KEY: True})
        detections = {
            "persons": [
                {"box": (10, 10, 40, 40), "confidence": 0.9},
                {"box": (50, 50, 80, 80), "confidence": 0.8},
            ],
            "gathering_alert": True,
            "gather_cluster_indices": [0, 1],
            "by_class": {},
            "behaviors": {
                FACE_RECOG_KEY: {
                    "alert": True,
                    "trigger_types": ["known", "unknown"],
                    "alert_matches": [
                        {
                            "box": (12, 12, 30, 30),
                            "person_id": "p1",
                            "person_name": "jiaxu",
                            "similarity": 0.91,
                            "match_type": "known",
                        },
                        {
                            "box": (55, 55, 70, 70),
                            "person_id": None,
                            "person_name": "陌生人",
                            "similarity": 0.0,
                            "match_type": "unknown",
                        },
                    ],
                }
            },
        }
        units = collect_alert_units(flags, detections)
        labels = [u.label for u in units]
        self.assertEqual(labels, ["人员聚集", "人脸识别"])
        self.assertEqual(len(units[1].matches), 2)

    def test_known_and_stranger_same_face_type(self):
        flags = _flags(**{FACE_RECOG_KEY: True})
        detections = {
            "by_class": {},
            "behaviors": {
                FACE_RECOG_KEY: {
                    "alert": True,
                    "alert_matches": [
                        {
                            "box": (1, 1, 10, 10),
                            "person_name": "jiaxu",
                            "match_type": "known",
                            "similarity": 0.9,
                        },
                        {
                            "box": (20, 20, 30, 30),
                            "person_name": "lisi",
                            "match_type": "known",
                            "similarity": 0.88,
                        },
                    ],
                }
            },
        }
        labels = [u.label for u in collect_alert_units(flags, detections)]
        self.assertEqual(labels, ["人脸识别"])
        self.assertEqual(len(collect_alert_units(flags, detections)[0].matches), 2)

    def test_render_face_omits_gather_overlay(self):
        flags = _flags(**{GATHER_KEY: True, FACE_RECOG_KEY: True})
        detections = {
            "persons": [
                {"box": (10, 10, 60, 60), "confidence": 0.9},
                {"box": (70, 10, 120, 60), "confidence": 0.9},
            ],
            "gathering_alert": True,
            "gather_cluster_indices": [0, 1],
            "by_class": {},
            "behaviors": {
                FACE_RECOG_KEY: {
                    "alert": True,
                    "alert_matches": [
                        {
                            "box": (200, 200, 240, 240),
                            "person_name": "jiaxu",
                            "match_type": "known",
                            "similarity": 0.9,
                        }
                    ],
                }
            },
        }
        units = collect_alert_units(flags, detections)
        by_kind = {u.kind: u for u in units}
        src = np.zeros((280, 280, 3), dtype=np.uint8)
        gather = render_alert_frame(src, detections, by_kind["gather"])
        face = render_alert_frame(src, detections, by_kind["face"])
        self.assertGreater(int(gather.sum()), 0)
        self.assertGreater(int(face[200:240, 200:240].sum()), 0)
        # 人脸截图不含聚集人物框；聚集截图不含远处人脸框
        self.assertEqual(int(face[10:60, 10:60].sum()), 0)
        self.assertGreater(int(gather[10:60, 10:60].sum()), 0)
        self.assertEqual(int(gather[200:240, 200:240].sum()), 0)

    def test_alert_boxes_every_face_and_dedupes_stranger_name(self):
        flags = _flags(**{FACE_RECOG_KEY: True})
        detections = {
            "by_class": {},
            "behaviors": {
                FACE_RECOG_KEY: {
                    "alert": True,
                    "trigger_types": ["known", "unknown"],
                    # 时长闸只放行了其中一张，本帧其实有三张脸
                    "alert_matches": [
                        {
                            "box": (1, 1, 8, 8),
                            "person_name": "陌生人",
                            "match_type": "unknown",
                            "similarity": 0.0,
                        }
                    ],
                    "matches": [
                        {
                            "box": (1, 1, 8, 8),
                            "person_name": "陌生人",
                            "match_type": "unknown",
                            "similarity": 0.0,
                        },
                        {
                            "box": (20, 20, 40, 40),
                            "person_id": "p1",
                            "person_name": "wjx",
                            "match_type": "known",
                            "similarity": 0.91,
                        },
                        {
                            "box": (50, 50, 70, 70),
                            "person_name": "陌生人",
                            "match_type": "unknown",
                            "similarity": 0.0,
                        },
                    ],
                }
            },
        }
        units = collect_alert_units(flags, detections)
        self.assertEqual(len(units), 1)
        self.assertEqual(len(units[0].matches), 3)
        self.assertEqual(units[0].info, "人脸识别: wjx, 陌生人")
        names = units[0].extra["face_recognition"]["person_names"]
        self.assertEqual(names, ["wjx", "陌生人"])

    def test_two_known_names_keep_each_person(self):
        flags = _flags(**{FACE_RECOG_KEY: True})
        detections = {
            "by_class": {},
            "behaviors": {
                FACE_RECOG_KEY: {
                    "alert": True,
                    "trigger_types": ["known", "unknown"],
                    "alert_matches": [
                        {"box": (1, 1, 8, 8), "person_name": "wjx", "match_type": "known"},
                    ],
                    "matches": [
                        {"box": (1, 1, 8, 8), "person_name": "wjx", "match_type": "known"},
                        {"box": (20, 1, 28, 8), "person_name": "胡", "match_type": "known"},
                    ],
                }
            },
        }
        unit = collect_alert_units(flags, detections)[0]
        self.assertEqual(len(unit.matches), 2)
        self.assertEqual(unit.info, "人脸识别: wjx, 胡")

    def test_strangers_only_name_once(self):
        flags = _flags(**{FACE_RECOG_KEY: True})
        detections = {
            "by_class": {},
            "behaviors": {
                FACE_RECOG_KEY: {
                    "alert": True,
                    "trigger_types": ["unknown"],
                    "alert_matches": [
                        {"box": (1, 1, 8, 8), "person_name": "陌生人", "match_type": "unknown"},
                    ],
                    "matches": [
                        {"box": (1, 1, 8, 8), "person_name": "陌生人", "match_type": "unknown"},
                        {"box": (20, 1, 28, 8), "person_name": "陌生人", "match_type": "unknown"},
                        {"box": (40, 1, 48, 8), "person_name": "wjx", "match_type": "known"},
                    ],
                }
            },
        }
        unit = collect_alert_units(flags, detections)[0]
        self.assertEqual(len(unit.matches), 2)
        self.assertEqual(unit.info, "人脸识别: 陌生人")


if __name__ == "__main__":
    unittest.main()
