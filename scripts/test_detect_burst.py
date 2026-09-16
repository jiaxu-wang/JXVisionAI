#!/usr/bin/env python3
"""一轮短窗抽帧：采集器与命中率聚合的无模型单测。"""

from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from visionai.core.detect_burst import (  # noqa: E402
    DetectBurstCollector,
    aggregate_burst_round,
    format_hit_summary,
)


class _Frame:
    def __init__(self, i: int) -> None:
        self.i = i

    def copy(self) -> "_Frame":
        return _Frame(self.i)


def _det(*, cls0=False, smoke=False, gather_n=0, smoke_alert=False):
    return {
        "persons": [{"box": (0, 0, 10, 10), "confidence": 0.9}] * int(gather_n),
        "cell_phones": [],
        "calls": [],
        "phone_play": [],
        "by_class": {0: [{"box": (0, 0, 10, 10), "confidence": 0.8}] if cls0 else []},
        "gathering_alert": False,
        "gather_cluster_indices": list(range(int(gather_n))) if gather_n else [],
        "gather_count": int(gather_n),
        "behaviors": {
            "smoking": {
                "alert": bool(smoke_alert),
                "boxes": [{"box": (1, 1, 2, 2), "confidence": 0.7}] if smoke else [],
                "scores": {"0": 0.7} if smoke else {},
            }
        },
    }


def test_collector_stops_on_duration() -> None:
    c = DetectBurstCollector(
        interval_sec=1, duration_ms=500, max_frames=15, min_frames=1
    )
    batch = None
    for i in range(30):
        batch = c.feed(_Frame(i), i * 0.04)
        if batch is not None:
            break
    assert batch is not None, "500ms 窗应交出一批帧"
    assert 8 <= len(batch.frames) <= 15, len(batch.frames)
    assert batch.want == 15
    assert batch.capture_ms >= 400


def test_collector_stops_on_max_frames() -> None:
    c = DetectBurstCollector(
        interval_sec=1, duration_ms=500, max_frames=3, min_frames=1
    )
    n_ready = 0
    got = None
    for i in range(20):
        got = c.feed(_Frame(i), i * 0.04)
        if got is not None:
            n_ready += 1
            break
    assert n_ready == 1
    assert got is not None and len(got.frames) == 3


def test_hit_ratio_drops_sparse_class() -> None:
    samples = []
    for i in range(10):
        samples.append((f"f{i}", _det(cls0=(i < 3), smoke=(i < 8))))
    vis, out, stats = aggregate_burst_round(samples, hit_ratio=0.4)
    assert vis == "f0" or "smoking" in str(out.get("behaviors"))
    assert "beh:smoking" in stats["kept"], stats
    assert "class:0" not in stats["kept"], stats["hits"]
    assert out["by_class"][0] == []
    assert out["behaviors"]["smoking"]["alert"] is True


def test_pick_frame_with_most_kept_types() -> None:
    samples = [
        ("a", _det(cls0=True, smoke=False)),
        ("b", _det(cls0=True, smoke=True)),
        ("c", _det(cls0=False, smoke=True)),
    ]
    vis, out, stats = aggregate_burst_round(samples, hit_ratio=0.3)
    assert vis == "b", (vis, stats)
    assert out["behaviors"]["smoking"]["alert"] is True
    assert out["by_class"][0]


def test_duration_gated_behavior_still_counts() -> None:
    """窗内有框但 alert=False（时长闸）仍算阳性，过命中率后强制 alert。"""
    samples = [("x", _det(smoke=True, smoke_alert=False))] * 5
    _vis, out, stats = aggregate_burst_round(samples, hit_ratio=0.4)
    assert "beh:smoking" in stats["kept"]
    assert out["behaviors"]["smoking"]["alert"] is True


def test_gather_uses_mean_count() -> None:
    samples = [
        ("a", _det(gather_n=2)),
        ("b", _det(gather_n=4)),
        ("c", _det(gather_n=6)),
    ]
    _vis, out, stats = aggregate_burst_round(samples, hit_ratio=0.4)
    # GATHER_MIN_PERSONS 默认 ≥3，2/4/6 中后两帧阳性 → 2/3 ≥ 0.4
    assert "gather" in stats["kept"], stats
    assert out["gathering_alert"] is True
    assert out["gather_count"] == 4, out["gather_count"]
    assert "无检出" not in format_hit_summary(stats)


def main() -> int:
    tests = [
        test_collector_stops_on_duration,
        test_collector_stops_on_max_frames,
        test_hit_ratio_drops_sparse_class,
        test_pick_frame_with_most_kept_types,
        test_duration_gated_behavior_still_counts,
        test_gather_uses_mean_count,
    ]
    for fn in tests:
        fn()
        print("ok", fn.__name__)
    print("all passed", len(tests))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
