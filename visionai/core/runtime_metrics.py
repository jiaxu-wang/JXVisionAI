"""运行时指标收集（JSON /metrics）。"""

from __future__ import annotations

import threading
import time
from typing import Any, Dict

_lock = threading.Lock()
_started = time.time()
_stream_stats: Dict[str, Dict[str, Any]] = {}
_detect_samples: Dict[str, list] = {}


def note_frame(stream_id: str) -> None:
    if not stream_id:
        return
    now = time.time()
    with _lock:
        row = _stream_stats.setdefault(
            stream_id, {"frames": 0, "detects": 0, "last_frame_at": 0.0, "last_detect_ms": 0.0}
        )
        row["frames"] = int(row.get("frames") or 0) + 1
        row["last_frame_at"] = now


def note_detect(stream_id: str, elapsed_ms: float) -> None:
    if not stream_id:
        return
    with _lock:
        row = _stream_stats.setdefault(
            stream_id, {"frames": 0, "detects": 0, "last_frame_at": 0.0, "last_detect_ms": 0.0}
        )
        row["detects"] = int(row.get("detects") or 0) + 1
        row["last_detect_ms"] = float(elapsed_ms)
        samples = _detect_samples.setdefault(stream_id, [])
        samples.append(float(elapsed_ms))
        if len(samples) > 50:
            del samples[:-50]


def snapshot_metrics() -> Dict[str, Any]:
    from visionai.core.alert_queue import queue_depth
    from visionai.core.state_manager import get_all_stream_statuses

    status_copy = get_all_stream_statuses()
    with _lock:
        streams = {k: dict(v) for k, v in _stream_stats.items()}
        for sid, samples in _detect_samples.items():
            if sid in streams and samples:
                streams[sid]["detect_ms_avg"] = sum(samples) / len(samples)
    return {
        "uptime_sec": round(time.time() - _started, 1),
        "alert_queue_depth": queue_depth(),
        "stream_status": status_copy,
        "streams": streams,
    }
