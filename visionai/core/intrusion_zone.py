"""人物入侵区域与布防时段。

区域坐标是画面宽高的 0–1。没画区域时，人物告警仍按原来的方式保存，
平台事件码不填。画了区域之后，只有人物框中心落在任一多边形内、
且当前小时处于布防时段，才保留这条人物告警并带上 platform_event_type=190。
人脸、车牌、专模不受影响。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, List, Optional, Sequence, Tuple

PERSON_LABEL = "人物"
PLATFORM_EVENT_INTRUSION = 190
_MAX_REGIONS = 8
_MAX_POINTS = 32


def normalize_intrusion_zone(raw: Any) -> dict:
    """整理成可写入 Redis 的结构。损坏的时段表按全时段布防处理。"""
    if not isinstance(raw, dict):
        return {"regions": [], "schedule_all": True, "schedule": None}
    regions = []
    for reg in raw.get("regions") or []:
        pts_raw = reg.get("points") if isinstance(reg, dict) else None
        pts = []
        for p in pts_raw or []:
            if not isinstance(p, (list, tuple)) or len(p) < 2:
                continue
            try:
                x = float(p[0])
                y = float(p[1])
            except (TypeError, ValueError):
                continue
            if x < 0 or x > 1 or y < 0 or y > 1:
                continue
            pts.append([round(x, 4), round(y, 4)])
            if len(pts) >= _MAX_POINTS:
                break
        if len(pts) >= 3:
            regions.append({"points": pts})
        if len(regions) >= _MAX_REGIONS:
            break
    schedule_all = raw.get("schedule_all", True)
    schedule_all = False if schedule_all is False else True
    schedule = None
    if not schedule_all:
        schedule = _parse_schedule(raw.get("schedule"))
        if schedule is None:
            schedule_all = True
    return {
        "regions": regions,
        "schedule_all": schedule_all,
        "schedule": schedule,
    }


def _parse_schedule(raw: Any) -> Optional[List[List[bool]]]:
    if not isinstance(raw, list) or len(raw) != 7:
        return None
    out: List[List[bool]] = []
    for row in raw:
        if not isinstance(row, list) or len(row) != 24:
            return None
        out.append([bool(x) for x in row])
    return out


def schedule_armed(zone: Any, when: datetime) -> bool:
    """周一为 0，与 datetime.weekday() 一致。缺省全时段布防。"""
    z = zone if isinstance(zone, dict) else {}
    if z.get("schedule_all", True) is not False:
        return True
    schedule = z.get("schedule")
    if not isinstance(schedule, list) or len(schedule) != 7:
        return True
    day = int(when.weekday())
    hour = int(when.hour)
    row = schedule[day]
    if not isinstance(row, list) or hour < 0 or hour >= len(row):
        return True
    return bool(row[hour])


def point_in_polygon(x: float, y: float, points: Sequence[Sequence[float]]) -> bool:
    n = len(points)
    if n < 3:
        return False
    inside = False
    j = n - 1
    for i in range(n):
        xi, yi = float(points[i][0]), float(points[i][1])
        xj, yj = float(points[j][0]), float(points[j][1])
        if (yi > y) != (yj > y):
            denom = (yj - yi) or 1e-12
            if x < (xj - xi) * (y - yi) / denom + xi:
                inside = not inside
        j = i
    return inside


def _person_boxes(detections: Any) -> List[Tuple[float, float, float, float]]:
    if not isinstance(detections, dict):
        return []
    by = detections.get("by_class") or {}
    items = by.get(0) or by.get("0") or []
    boxes = []
    for it in items:
        box = it.get("box") if isinstance(it, dict) else None
        if box and len(box) >= 4:
            boxes.append(tuple(float(v) for v in box[:4]))
    if boxes:
        return boxes
    for it in detections.get("persons") or []:
        box = it.get("box") if isinstance(it, dict) else None
        if box and len(box) >= 4:
            boxes.append(tuple(float(v) for v in box[:4]))
    return boxes


def _hits_regions(boxes, width: float, height: float, regions) -> bool:
    if width <= 0 or height <= 0:
        return False
    for x1, y1, x2, y2 in boxes:
        cx = ((x1 + x2) / 2.0) / width
        cy = ((y1 + y2) / 2.0) / height
        for reg in regions:
            pts = reg.get("points") if isinstance(reg, dict) else None
            if pts and point_in_polygon(cx, cy, pts):
                return True
    return False


def filter_person_zone(units, detections, frame_shape, zone, when: datetime):
    """返回 [(unit, platform_event_type or None)]。区域外或撤防的人物告警被丢掉。"""
    z = normalize_intrusion_zone(zone)
    regions = z.get("regions") or []
    height = 0
    width = 0
    if frame_shape is not None and len(frame_shape) >= 2:
        height = float(frame_shape[0] or 0)
        width = float(frame_shape[1] or 0)
    armed = schedule_armed(z, when)
    boxes = _person_boxes(detections) if regions else []
    hit = _hits_regions(boxes, width, height, regions) if regions and armed else False
    out = []
    for unit in units or []:
        label = getattr(unit, "label", "")
        if label != PERSON_LABEL:
            out.append((unit, None))
            continue
        if not regions:
            out.append((unit, None))
            continue
        if not armed or not hit:
            continue
        out.append((unit, PLATFORM_EVENT_INTRUSION))
    return out
