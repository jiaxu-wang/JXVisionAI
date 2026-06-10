"""行为插件共用：持续时长防抖、人物关联框收集。"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence, Tuple

from visionai.core import dedicated_yolo as dyolo


def apply_duration_alert(
    indexed: List[Tuple[int, Dict[str, Any]]],
    scores: Dict[str, float],
    state: Dict[str, Any],
    now: float,
    *,
    score_threshold: float,
    min_duration_sec: float,
    since_key: str = "person_since",
) -> Tuple[List[int], bool]:
    since_map: Dict[str, float] = state.setdefault(since_key, {})
    alerting: List[int] = []
    dur = max(0.0, float(min_duration_sec))
    active_keys = set()
    for pi, _person in indexed:
        pk = str(pi)
        if pk not in scores:
            if pk in since_map:
                del since_map[pk]
            continue
        active_keys.add(pk)
        if scores[pk] < score_threshold:
            if pk in since_map:
                del since_map[pk]
            continue
        if pk not in since_map:
            since_map[pk] = now
        if dur <= 0 or now - since_map[pk] >= dur:
            alerting.append(pi)
    for pk in list(since_map.keys()):
        if pk not in active_keys:
            del since_map[pk]
    return alerting, len(alerting) > 0


def apply_keyed_duration_alert(
    scores: Dict[str, float],
    state: Dict[str, Any],
    now: float,
    *,
    score_threshold: float,
    min_duration_sec: float,
    since_key: str = "evt_since",
) -> Tuple[List[str], bool]:
    """专模独立检测：按 scores 的键（如事件框序号）做持续时长防抖。"""
    since_map: Dict[str, float] = state.setdefault(since_key, {})
    alerting: List[str] = []
    dur = max(0.0, float(min_duration_sec))
    active_keys = set()
    for pk, sc in scores.items():
        key = str(pk)
        if sc < score_threshold:
            if key in since_map:
                del since_map[key]
            continue
        active_keys.add(key)
        if key not in since_map:
            since_map[key] = now
        if dur <= 0 or now - since_map[key] >= dur:
            alerting.append(key)
    for pk in list(since_map.keys()):
        if pk not in active_keys:
            del since_map[pk]
    return alerting, len(alerting) > 0


def apply_scene_duration_alert(
    active: bool,
    state: Dict[str, Any],
    now: float,
    *,
    min_duration_sec: float,
    since_key: str = "scene_since",
) -> bool:
    since_map: Dict[str, float] = state.setdefault(since_key, {})
    dur = max(0.0, float(min_duration_sec))
    if not active:
        since_map.clear()
        return False
    if "t" not in since_map:
        since_map["t"] = now
    if dur <= 0 or now - since_map["t"] >= dur:
        return True
    return False


def top_persons(
    persons: Sequence[Dict[str, Any]], limit: int
) -> List[Tuple[int, Dict[str, Any]]]:
    indexed = list(enumerate(persons))
    indexed.sort(key=lambda t: float(t[1].get("confidence", 0.0)), reverse=True)
    return indexed[: max(1, limit)]


def overlap_boxes_for_persons(
    indexed: List[Tuple[int, Dict[str, Any]]],
    person_indices: List[int],
    detections: Sequence[Dict[str, Any]],
    *,
    class_ids: Optional[Sequence[int]] = None,
) -> List[Dict[str, Any]]:
    if not person_indices or not detections:
        return []
    want = {int(i) for i in person_indices}
    seen = set()
    out: List[Dict[str, Any]] = []
    for pi, person in indexed:
        if pi not in want:
            continue
        pb = tuple(int(x) for x in person["box"][:4])
        for d in detections:
            if class_ids is not None and int(d.get("class_id", -1)) not in class_ids:
                continue
            cb = d.get("box")
            if not cb or len(cb) < 4:
                continue
            if not dyolo.boxes_associated(pb, tuple(int(x) for x in cb[:4])):
                continue
            key = tuple(int(x) for x in cb[:4])
            if key in seen:
                continue
            seen.add(key)
            out.append(
                {
                    "box": key,
                    "confidence": float(d.get("confidence", 0.0)),
                    "name": str(d.get("name") or ""),
                    "class_id": int(d.get("class_id", -1)),
                }
            )
    return out


def empty_person_result() -> Dict[str, Any]:
    return {
        "alert": False,
        "person_indices": [],
        "scores": {},
        "event_boxes": [],
        "standalone": False,
        "alert_keys": [],
    }


def empty_scene_result() -> Dict[str, Any]:
    return {"alert": False, "boxes": [], "count": 0}
