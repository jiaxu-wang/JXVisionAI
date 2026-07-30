#!/usr/bin/env python3
"""S5/S8/S9 gates against a running visionai-inferd."""

from __future__ import annotations

import os
import sys
import time

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, ".pip_target"))

import cv2  # noqa: E402
import numpy as np  # noqa: E402

from visionai.core.detector import Detector  # noqa: E402
from visionai.core.infer_client import InferClient  # noqa: E402
from visionai.core.infer_types import DetectionBox  # noqa: E402


def load_sample():
    p = os.path.join(ROOT, "native/inferd/testdata/bus.jpg")
    im = cv2.imread(p) if os.path.isfile(p) else None
    if im is None:
        im = np.zeros((480, 640, 3), np.uint8)
        cv2.rectangle(im, (100, 80), (280, 400), (0, 200, 255), -1)
    return im


def main() -> int:
    endpoint = os.environ.get("INFER_ENDPOINT", "unix:///tmp/visionai-inferd.sock")
    client = InferClient(endpoint=endpoint)
    assert client.live(), "Live failed"
    if not client.ready():
        client.load_primary()
    assert client.ready(), "Ready failed"
    print("S5 client Live/Ready OK")

    im = load_sample()
    sid = "py-s5"
    client.open_session(sid, conf=0.25)
    r = client.infer(sid, im)
    assert r.ok, r.message
    print(f"S5 Infer OK dets={len(r.boxes)} infer_ms={r.infer_ms}")

    # S6: process_results_from_boxes with fake + real boxes
    det = Detector(stream_name="s6", save_dir="/tmp/visionai-s6", detections={"0": True}, stream_id="s6")
    fake = [DetectionBox(10, 10, 100, 200, 0, 0.9)]
    frame, alarms = det.process_results_from_boxes(im.copy(), fake)
    assert frame is not None
    print("S6 process_results_from_boxes OK")

    # S9: 4 sessions share one engine
    t0 = time.time()
    ms = []
    for i in range(4):
        s = f"s9-{i}"
        client.open_session(s, conf=0.3)
        rr = client.infer(s, im)
        assert rr.ok, rr.message
        ms.append(rr.infer_ms)
    print(f"S9 multi-session OK n=4 infer_ms={ms} wall={time.time()-t0:.2f}s")
    print("S5/S6/S9 PYTHON GATES PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
