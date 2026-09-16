"""一轮检测：间隔到点后在短窗内抽多帧，按命中率聚合为本轮结论。

最小实现约定：
- 采样窗按墙钟 ``duration_ms``，最多 ``max_frames`` 张，先到先停。
- 先拷帧再推理（推理时间不计入采样窗）。
- 聚合按类型做命中率，代表帧选「覆盖已通过类型最多 + 置信度质量」的那一张。
- 不把其它帧的框叠到代表帧上（避免框与画面错位）。
- 疲劳驾驶不走本路径。
"""

from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, NamedTuple, Optional, Sequence, Set, Tuple

from visionai.config.detection_catalog import FATIGUE_KEY
from visionai.config.settings import (
    DETECT_BURST_DURATION_MS,
    DETECT_BURST_FRAMES,
    DETECT_BURST_HIT_RATIO,
    DETECT_BURST_MIN_FRAMES,
    DETECTION_INTERVAL,
    GATHER_MIN_PERSONS,
)

logger = logging.getLogger(__name__)


class BurstBatch(NamedTuple):
    frames: List[Any]
    capture_ms: float
    want: int


def burst_enabled() -> bool:
    return DETECT_BURST_FRAMES > 1 and DETECT_BURST_DURATION_MS > 0


class DetectBurstCollector:
    """到点开窗，按间隔尽量均匀抽帧，满窗或满帧后交出拷贝。"""

    def __init__(
        self,
        *,
        interval_sec: Optional[float] = None,
        duration_ms: Optional[int] = None,
        max_frames: Optional[int] = None,
        min_frames: Optional[int] = None,
    ) -> None:
        self.interval_sec = float(
            DETECTION_INTERVAL if interval_sec is None else interval_sec
        )
        self.duration_s = max(
            0.0,
            float(DETECT_BURST_DURATION_MS if duration_ms is None else duration_ms)
            / 1000.0,
        )
        self.max_frames = max(
            1, int(DETECT_BURST_FRAMES if max_frames is None else max_frames)
        )
        self.min_frames = max(
            1, int(DETECT_BURST_MIN_FRAMES if min_frames is None else min_frames)
        )
        self.min_frames = min(self.min_frames, self.max_frames)
        self._open = False
        self._t0 = 0.0
        self._last_keep = 0.0
        self._frames: List[Any] = []
        self._next_at = 0.0

    def reset_capture(self) -> None:
        """丢弃正在进行的采样窗（例如 DMS 突发断开拉流）。"""
        self._open = False
        self._frames = []

    def _spacing(self) -> float:
        if self.max_frames <= 1 or self.duration_s <= 0:
            return 0.0
        return self.duration_s / float(self.max_frames)

    def feed(self, frame, now: float) -> Optional[BurstBatch]:
        if frame is None:
            return None
        if not self._open:
            if now < self._next_at:
                return None
            self._open = True
            self._t0 = now
            self._last_keep = 0.0
            self._frames = []

        spacing = self._spacing()
        take = False
        if not self._frames:
            take = True
        elif len(self._frames) < self.max_frames:
            if spacing <= 0 or (now - self._last_keep) >= spacing * 0.75:
                take = True
        if take:
            copied = frame.copy() if hasattr(frame, "copy") else frame
            self._frames.append(copied)
            self._last_keep = now

        elapsed = now - self._t0
        done = len(self._frames) >= self.max_frames or elapsed >= self.duration_s
        if not done:
            return None

        got = self._frames
        capture_ms = max(0.0, elapsed) * 1000.0
        want = self.max_frames
        self._frames = []
        self._open = False
        nxt = self._t0 + self.interval_sec
        self._next_at = nxt if nxt > now else now
        if len(got) < self.min_frames:
            logger.info(
                "检测轮次采样不足 %d/%d（最少 %d），本轮跳过",
                len(got),
                want,
                self.min_frames,
            )
            return None
        return BurstBatch(frames=got, capture_ms=capture_ms, want=want)


def _conf_of(item: Any) -> float:
    if not isinstance(item, dict):
        return 0.0
    try:
        return float(item.get("confidence") or 0.0)
    except (TypeError, ValueError):
        return 0.0


def behavior_raw_hit(br: Any) -> bool:
    """窗内阳性：看检出信号，不看持续时长闸后的 alert。"""
    if not isinstance(br, dict):
        return False
    if br.get("alert"):
        return True
    if br.get("alert_matches") or br.get("matches"):
        return True
    if br.get("boxes") or br.get("event_boxes") or br.get("smoking_boxes"):
        return True
    try:
        if int(br.get("count") or 0) > 0:
            return True
    except (TypeError, ValueError):
        pass
    if br.get("person_indices") or br.get("alert_keys"):
        return True
    scores = br.get("scores") or {}
    if isinstance(scores, dict):
        for v in scores.values():
            try:
                if float(v) > 0:
                    return True
            except (TypeError, ValueError):
                continue
    return False


def _frame_hit_keys(det: Dict[str, Any]) -> Set[str]:
    hits: Set[str] = set()
    by_class = det.get("by_class") or {}
    if isinstance(by_class, dict):
        for cid, items in by_class.items():
            if items:
                hits.add(f"class:{int(cid)}")
    if det.get("calls"):
        hits.add("calls")
    if det.get("phone_play"):
        hits.add("phone_play")
    try:
        if int(det.get("gather_count") or 0) >= GATHER_MIN_PERSONS:
            hits.add("gather")
    except (TypeError, ValueError):
        pass
    behaviors = det.get("behaviors") or {}
    if isinstance(behaviors, dict):
        for key, br in behaviors.items():
            if key == FATIGUE_KEY:
                continue
            if behavior_raw_hit(br):
                hits.add(f"beh:{key}")
    return hits


def _confidence_mass(det: Dict[str, Any]) -> float:
    mass = 0.0
    by_class = det.get("by_class") or {}
    if isinstance(by_class, dict):
        for items in by_class.values():
            for it in items or []:
                mass += _conf_of(it)
    for key in ("calls", "phone_play"):
        for it in det.get(key) or []:
            mass += _conf_of(it)
    behaviors = det.get("behaviors") or {}
    if isinstance(behaviors, dict):
        for key, br in behaviors.items():
            if key == FATIGUE_KEY or not isinstance(br, dict):
                continue
            for box_key in ("boxes", "event_boxes", "smoking_boxes"):
                for it in br.get(box_key) or []:
                    mass += _conf_of(it)
            scores = br.get("scores") or {}
            if isinstance(scores, dict):
                for v in scores.values():
                    try:
                        mass += float(v)
                    except (TypeError, ValueError):
                        pass
    return mass


def _count_hits(samples: Sequence[Tuple[Any, Dict[str, Any]]]) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for _vis, det in samples:
        for key in _frame_hit_keys(det):
            counts[key] = counts.get(key, 0) + 1
    return counts


def _kept_keys(counts: Dict[str, int], n: int, hit_ratio: float) -> Set[str]:
    if n <= 0:
        return set()
    need = hit_ratio
    kept: Set[str] = set()
    for key, hits in counts.items():
        if (hits / float(n)) + 1e-9 >= need:
            kept.add(key)
    return kept


def _pick_index(
    samples: Sequence[Tuple[Any, Dict[str, Any]]], kept: Set[str]
) -> int:
    best_i = 0
    best_s = -1.0
    for i, (_vis, det) in enumerate(samples):
        hits = _frame_hit_keys(det)
        covered = len(hits & kept) if kept else len(hits)
        score = covered * 10.0 + _confidence_mass(det)
        if score > best_s:
            best_s = score
            best_i = i
    return best_i


def _filter_to_kept(det: Dict[str, Any], kept: Set[str]) -> Dict[str, Any]:
    """在代表帧结果上关掉未过命中率的类型；过线的则强制 alert。"""
    by_class = det.get("by_class")
    if isinstance(by_class, dict):
        for cid in list(by_class.keys()):
            if f"class:{int(cid)}" not in kept:
                by_class[cid] = []

    if "calls" not in kept:
        det["calls"] = []
    if "phone_play" not in kept:
        det["phone_play"] = []

    if "gather" in kept:
        det["gathering_alert"] = True
        if not det.get("gather_cluster_indices"):
            persons = det.get("persons") or []
            if persons:
                det["gather_cluster_indices"] = list(range(len(persons)))
    else:
        det["gathering_alert"] = False

    behaviors = det.get("behaviors")
    if isinstance(behaviors, dict):
        for key, br in behaviors.items():
            if key == FATIGUE_KEY or not isinstance(br, dict):
                continue
            sig = f"beh:{key}"
            if sig in kept and behavior_raw_hit(br):
                br["alert"] = True
            else:
                br["alert"] = False
    return det


def aggregate_burst_round(
    samples: Sequence[Tuple[Any, Dict[str, Any]]],
    *,
    hit_ratio: Optional[float] = None,
) -> Tuple[Any, Dict[str, Any], Dict[str, Any]]:
    """把多帧 (画框图, detections) 聚成一轮。"""
    ratio = float(
        DETECT_BURST_HIT_RATIO if hit_ratio is None else hit_ratio
    )
    ratio = min(1.0, max(0.0, ratio))
    n = len(samples)
    if n == 0:
        raise ValueError("aggregate_burst_round: empty samples")

    counts = _count_hits(samples)
    kept = _kept_keys(counts, n, ratio)
    idx = _pick_index(samples, kept)
    vis, det = samples[idx]
    det = _filter_to_kept(det, kept)

    gather_vals: List[int] = []
    for _v, d in samples:
        try:
            gather_vals.append(int(d.get("gather_count") or 0))
        except (TypeError, ValueError):
            gather_vals.append(0)
    gather_mean = (sum(gather_vals) / float(n)) if n else 0.0
    if "gather" in kept:
        det["gather_count"] = int(round(gather_mean))

    stats = {
        "n": n,
        "picked": idx,
        "hit_ratio": ratio,
        "hits": counts,
        "kept": sorted(kept),
        "gather_mean": round(gather_mean, 2),
    }
    return vis, det, stats


def run_burst_round(
    detector: Any,
    frames: Sequence[Any],
    *,
    hit_ratio: Optional[float] = None,
    now: Optional[float] = None,
) -> Tuple[Any, Dict[str, Any], Dict[str, Any]]:
    """对采样帧逐张 detect + process_results，再聚合。``now`` 冻结时长闸。"""
    ts = time.time() if now is None else float(now)
    t0 = time.time()
    samples: List[Tuple[Any, Dict[str, Any]]] = []
    for fr in frames:
        try:
            boxes = detector.detect(fr)
            vis, det = detector.process_results(fr, boxes, now=ts)
        except Exception:  # noqa: BLE001
            logger.warning("burst 单帧推理失败", exc_info=True)
            continue
        samples.append((vis, det))
    infer_ms = (time.time() - t0) * 1000.0
    if not samples:
        raise RuntimeError("burst 全部帧推理失败")
    vis, det, stats = aggregate_burst_round(samples, hit_ratio=hit_ratio)
    stats["infer_ms"] = round(infer_ms, 1)
    stats["got"] = len(samples)
    det["_burst"] = stats
    return vis, det, stats


def format_hit_summary(stats: Dict[str, Any]) -> str:
    n = int(stats.get("n") or stats.get("got") or 0)
    hits = stats.get("hits") or {}
    kept = set(stats.get("kept") or [])
    if not hits:
        return "无检出"
    parts = []
    for key in sorted(hits.keys()):
        mark = "✓" if key in kept else "×"
        parts.append(f"{key} {hits[key]}/{n}{mark}")
    return " ".join(parts)
