"""人脸库手动比对：1:N 排序与截帧候选 URL。"""

from __future__ import annotations

import unittest

import numpy as np


class FaceCompareRankTests(unittest.TestCase):
    def setUp(self):
        from visionai.core import face_library

        self.fl = face_library
        with self.fl._lock:
            self._old_emb = list(self.fl._embeddings)
            self._old_idx = dict(self.fl._index)

    def tearDown(self):
        with self.fl._lock:
            self.fl._embeddings = self._old_emb
            self.fl._index = self._old_idx

    def _install(self, people):
        embs = []
        idx = {}
        for pid, vec, name in people:
            embs.append((pid, self.fl._normalize_embedding(np.asarray(vec, dtype=np.float32))))
            idx[pid] = {
                "id": pid,
                "identity_id": pid,
                "name": name,
                "department": "",
            }
        with self.fl._lock:
            self.fl._embeddings = embs
            self.fl._index = idx

    def test_rank_embedding_orders_by_similarity(self):
        self._install(
            [
                ("p1", [1.0, 0.0, 0.0], "A"),
                ("p2", [0.0, 1.0, 0.0], "B"),
                ("p3", [0.8, 0.6, 0.0], "C"),
            ]
        )
        ranked = self.fl.rank_embedding(np.array([1.0, 0.0, 0.0], dtype=np.float32), top_k=3)
        self.assertEqual([x["person_id"] for x in ranked], ["p1", "p3", "p2"])
        self.assertAlmostEqual(ranked[0]["similarity"], 1.0, places=4)
        self.assertEqual(ranked[0]["name"], "A")

    def test_rank_embedding_watchlist_and_empty(self):
        self._install(
            [
                ("p1", [1.0, 0.0], "A"),
                ("p2", [0.0, 1.0], "B"),
            ]
        )
        ranked = self.fl.rank_embedding(
            np.array([1.0, 0.0], dtype=np.float32), watchlist=["p2"], top_k=5
        )
        self.assertEqual([x["person_id"] for x in ranked], ["p2"])
        with self.fl._lock:
            self.fl._embeddings = []
            self.fl._index = {}
        self.assertEqual(
            self.fl.rank_embedding(np.array([1.0, 0.0], dtype=np.float32)), []
        )


class StreamFrameUrlTests(unittest.TestCase):
    def test_candidate_includes_source_rtsp(self):
        from visionai.core.stream_frame import candidate_rtsp_urls

        urls = candidate_rtsp_urls(
            {
                "id": "stream_abc",
                "url": "rtsp://192.168.1.8:554/live",
                "access_method": "rtsp_url",
            }
        )
        self.assertIn("rtsp://192.168.1.8:554/live", urls)


if __name__ == "__main__":
    unittest.main()
