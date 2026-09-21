"""一轮检测按类型拆成独立告警：每类一条记录、一张只含该类框的截图。"""

from __future__ import annotations

import colorsys
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Sequence

import cv2
import numpy as np

from visionai.config.detection_catalog import (
    CALL_KEY,
    COCO_NAMES,
    FACE_RECOG_KEY,
    FATIGUE_KEY,
    GATHER_KEY,
    PHONE_PLAY_KEY,
    PLATE_RECOG_KEY,
    all_extension_keys,
    label_zh_for_class,
    label_zh_for_extension,
    person_behavior_keys,
)
from visionai.utils.frame_draw import draw_labeled_box, label_font_px, put_text
from visionai.core.face_library import UNKNOWN_PERSON_ID, resolve_person_id


def _bgr_for_class(class_id: int):
    h = (class_id * 0.618033988749895) % 1.0
    r, g, b = colorsys.hsv_to_rgb(h, 0.82, 0.96)
    return int(b * 255), int(g * 255), int(r * 255)


_BEHAVIOR_COLORS = {
    CALL_KEY: (0, 0, 255),
    FACE_RECOG_KEY: (0, 200, 0),
    PLATE_RECOG_KEY: (255, 140, 0),
    FATIGUE_KEY: (0, 90, 255),
}


def _color_for_behavior(key: str):
    if key in _BEHAVIOR_COLORS:
        return _BEHAVIOR_COLORS[key]
    h = (abs(hash(key)) % 1000) / 1000.0
    r, g, b = colorsys.hsv_to_rgb(h, 0.75, 0.95)
    return int(b * 255), int(g * 255), int(r * 255)


def _center_xyxy(box) -> tuple[float, float]:
    x1, y1, x2, y2 = box
    return (x1 + x2) * 0.5, (y1 + y2) * 0.5


def filename_slug(label: str) -> str:
    s = re.sub(r'[\\/:*?"<>|\s]+', "_", (label or "").strip())
    s = s.strip("._") or "alert"
    return s[:48]


def _public_face_match(m: Mapping[str, Any]) -> Dict[str, Any]:
    pid = resolve_person_id(m.get("person_id"))
    ident = str(m.get("identity_id") or "").strip() or pid
    if ident == "":
        ident = UNKNOWN_PERSON_ID
    return {
        "person_id": pid,
        "identity_id": ident,
        "person_name": str(m.get("person_name") or "陌生人"),
        "department": str(m.get("department") or ""),
        "similarity": float(m.get("similarity") or 0.0),
        "match_type": str(m.get("match_type") or "unknown"),
        "box": m.get("box"),
    }


def plate_type_label(match: Mapping[str, Any]) -> str:
    if match.get("match_type") == "known":
        return "车牌识别: 库内"
    return "车牌识别: 陌生车牌"


@dataclass
class AlertUnit:
    kind: str
    label: str
    info: str
    extra: Optional[Dict[str, Any]] = None
    cid: Optional[int] = None
    ext_key: Optional[str] = None
    matches: List[Dict[str, Any]] = field(default_factory=list)


def _enabled(flags: Mapping[str, Any], key: str) -> bool:
    return bool(flags.get(key, False))


def collect_alert_units(flags: Mapping[str, Any], detections: Mapping[str, Any]) -> List[AlertUnit]:
    """从一轮 detections 收集各自独立的告警类型（不含画面）。"""
    units: List[AlertUnit] = []
    by_class = detections.get("by_class") or {}
    for cid, items in by_class.items():
        if not items:
            continue
        key = str(int(cid))
        if not _enabled(flags, key):
            continue
        zh = label_zh_for_class(int(cid))
        units.append(
            AlertUnit(
                kind="coco",
                label=zh,
                info=f"{zh}: {len(items)}",
                cid=int(cid),
            )
        )

    if _enabled(flags, CALL_KEY) and detections.get("calls"):
        n = len(detections["calls"])
        units.append(AlertUnit(kind="call", label="打电话", info=f"打电话: {n}"))

    if _enabled(flags, PHONE_PLAY_KEY) and detections.get("phone_play"):
        n = len(detections["phone_play"])
        units.append(AlertUnit(kind="phone_play", label="玩手机", info=f"玩手机: {n}"))

    if _enabled(flags, GATHER_KEY) and detections.get("gathering_alert"):
        n = len(detections.get("gather_cluster_indices") or [])
        units.append(AlertUnit(kind="gather", label="人员聚集", info=f"人员聚集: {n}"))

    behaviors = detections.get("behaviors") or {}

    fr = behaviors.get(FACE_RECOG_KEY) or {}
    if _enabled(flags, FACE_RECOG_KEY) and fr.get("alert"):
        matches = [dict(m) for m in (fr.get("alert_matches") or [])]
        if matches:
            extra_matches = [_public_face_match(m) for m in matches]
            info_names = []
            for m in extra_matches:
                name = m["person_name"]
                if name not in info_names:
                    info_names.append(name)
            zh = label_zh_for_extension(FACE_RECOG_KEY)
            units.append(
                AlertUnit(
                    kind="face",
                    label=zh,
                    info=f"{zh}: {', '.join(info_names)}",
                    extra={
                        "face_recognition": {
                            "trigger_types": fr.get("trigger_types") or [],
                            "matches": extra_matches,
                            "alert_matches": extra_matches,
                        }
                    },
                    matches=matches,
                )
            )

    pr = behaviors.get(PLATE_RECOG_KEY) or {}
    if _enabled(flags, PLATE_RECOG_KEY) and pr.get("alert"):
        grouped_p: Dict[str, List[Dict[str, Any]]] = {}
        for m in pr.get("alert_matches") or []:
            label = plate_type_label(m)
            grouped_p.setdefault(label, []).append(dict(m))
        for label, matches in grouped_p.items():
            extra_matches = [
                {
                    "plate_no": str(m.get("plate_no") or ""),
                    "owner_name": str(m.get("owner_name") or ""),
                    "match_type": m.get("match_type"),
                    "ocr_confidence": float(m.get("ocr_confidence", 0.0)),
                    "box": m.get("box"),
                }
                for m in matches
            ]
            units.append(
                AlertUnit(
                    kind="plate",
                    label=label,
                    info=f"{label} x{len(matches)}",
                    extra={
                        "plate_recognition": {
                            "trigger_types": pr.get("trigger_types") or [],
                            "matches": extra_matches,
                            "alert_matches": [
                                {
                                    "plate_no": str(m.get("plate_no") or ""),
                                    "owner_name": str(m.get("owner_name") or ""),
                                    "match_type": m.get("match_type"),
                                    "ocr_confidence": float(m.get("ocr_confidence", 0.0)),
                                }
                                for m in matches
                            ],
                        }
                    },
                    matches=matches,
                )
            )

    fg = behaviors.get(FATIGUE_KEY) or {}
    if _enabled(flags, FATIGUE_KEY) and fg.get("alert"):
        zh = label_zh_for_extension(FATIGUE_KEY)
        reasons = fg.get("reasons") or []
        label = zh + ((" · " + "/".join(reasons)) if reasons else "")
        units.append(
            AlertUnit(
                kind="fatigue",
                label=label,
                info=f"{label} PERCLOS={float(fg.get('perclos') or 0):.0%}",
                extra={
                    "fatigue_driving": {
                        "perclos": fg.get("perclos"),
                        "reasons": reasons,
                        "metrics": fg.get("metrics"),
                    }
                },
            )
        )

    p_keys = person_behavior_keys()
    skip_ext = {FACE_RECOG_KEY, PLATE_RECOG_KEY, PHONE_PLAY_KEY, GATHER_KEY, FATIGUE_KEY}
    for ek in all_extension_keys():
        if ek in skip_ext:
            continue
        if ek == CALL_KEY and detections.get("calls"):
            continue
        if not _enabled(flags, ek):
            continue
        br = behaviors.get(ek) or {}
        if not br.get("alert"):
            continue
        zh = label_zh_for_extension(ek)
        if br.get("standalone"):
            n = len(br.get("event_boxes") or [])
        elif ek in p_keys or ek == CALL_KEY:
            n = len(br.get("person_indices") or [])
        else:
            n = int(br.get("count") or len(br.get("boxes") or []))
        units.append(
            AlertUnit(
                kind="ext",
                label=zh,
                info=f"{zh}: {n}",
                ext_key=ek,
            )
        )
    return units


def _draw_box_item(frame, item, color, prefix: str, fs_px: int) -> None:
    box = item.get("box") if isinstance(item, dict) else None
    if not box:
        return
    conf = float(item.get("confidence", 0.0)) if isinstance(item, dict) else 0.0
    nm = prefix
    if isinstance(item, dict) and item.get("name"):
        nm = str(item.get("name"))
    label = f"{nm}: {conf:.2f}" if conf else nm
    draw_labeled_box(frame, box, label, color, font_px=fs_px)


def _draw_gather(frame, detections: Mapping[str, Any], fs_px: int) -> None:
    persons = detections.get("persons") or []
    idxs = list(detections.get("gather_cluster_indices") or [])
    color_gather = (0, 165, 255)
    pts = []
    for gi in idxs:
        if gi < 0 or gi >= len(persons):
            continue
        person = persons[gi]
        box = person.get("box")
        if not box:
            continue
        conf = float(person.get("confidence", 0.0))
        draw_labeled_box(
            frame,
            box,
            f"{COCO_NAMES[0]}: {conf:.2f}",
            _bgr_for_class(0),
            font_px=fs_px,
        )
        cx, cy = _center_xyxy(box)
        pts.append((int(cx), int(cy)))
    if not pts:
        return
    pts_np = np.array(pts, dtype=np.int32)
    thick = 3 if fs_px >= 48 else 2
    if len(pts_np) >= 3:
        hull = cv2.convexHull(pts_np)
        cv2.polylines(frame, [hull], True, color_gather, thick)
    elif len(pts_np) == 2:
        cv2.line(frame, tuple(pts_np[0]), tuple(pts_np[1]), color_gather, thick)
    cx = int(sum(p[0] for p in pts) / len(pts))
    cy = int(sum(p[1] for p in pts) / len(pts))
    put_text(
        frame,
        f"GATHERING: {len(pts)}",
        (cx, max(cy - 10, 20)),
        color_gather,
        font_px=fs_px,
    )


def _draw_call(frame, detections: Mapping[str, Any], fs_px: int) -> None:
    persons = detections.get("persons") or []
    color_call = _color_for_behavior(CALL_KEY)
    for c in detections.get("calls") or []:
        person = c.get("person") if isinstance(c, dict) else None
        phone = c.get("phone") if isinstance(c, dict) else None
        conf = float(c.get("confidence", 0.0)) if isinstance(c, dict) else 0.0
        if person and person.get("box"):
            pb = person["box"]
            pconf = float(person.get("confidence", conf))
            draw_labeled_box(
                frame, pb, f"{COCO_NAMES[0]}: {pconf:.2f}", _bgr_for_class(0), font_px=fs_px
            )
            put_text(
                frame,
                f"CALLING: {conf:.2f}",
                (pb[0], max(pb[1] - 10, 20)),
                color_call,
                font_px=fs_px,
            )
        if isinstance(phone, dict) and phone.get("box"):
            _draw_box_item(frame, phone, _bgr_for_class(67), "cell phone", fs_px)
    br = (detections.get("behaviors") or {}).get(CALL_KEY) or {}
    for eb in br.get("event_boxes") or []:
        sconf = float(eb.get("confidence", 0.0))
        nm = str(eb.get("name") or "phone")
        label = (
            f"{label_zh_for_extension(CALL_KEY)}: {sconf:.2f}"
            if br.get("standalone")
            else f"{nm}: {sconf:.2f}"
        )
        draw_labeled_box(frame, eb.get("box"), label, color_call, font_px=fs_px)
    if br.get("alert") and not (detections.get("calls") or []):
        for pi in br.get("person_indices") or []:
            pi = int(pi)
            if pi < 0 or pi >= len(persons):
                continue
            pb = persons[pi]["box"]
            sc = float(br.get("scores", {}).get(str(pi), 0.0))
            put_text(
                frame,
                f"CALLING: {sc:.2f}",
                (pb[0], max(pb[1] - 10, 20)),
                color_call,
                font_px=fs_px,
            )


def _draw_phone_play(frame, detections: Mapping[str, Any], fs_px: int) -> None:
    color = (204, 120, 0)
    for ev in detections.get("phone_play") or []:
        person = ev.get("person") if isinstance(ev, dict) else None
        phone = ev.get("phone") if isinstance(ev, dict) else None
        conf = float(ev.get("confidence", 0.0)) if isinstance(ev, dict) else 0.0
        if person and person.get("box"):
            pb = person["box"]
            pconf = float(person.get("confidence", conf))
            draw_labeled_box(
                frame, pb, f"{COCO_NAMES[0]}: {pconf:.2f}", _bgr_for_class(0), font_px=fs_px
            )
            put_text(
                frame,
                f"PLAY_PHONE: {conf:.2f}",
                (pb[0], max(pb[1] - 28, 20)),
                color,
                font_px=fs_px,
            )
        if isinstance(phone, dict) and phone.get("box"):
            _draw_box_item(frame, phone, _bgr_for_class(67), "cell phone", fs_px)


def _draw_face_matches(frame, matches: Sequence[Mapping[str, Any]], fs_px: int) -> None:
    for m in matches:
        box = m.get("box")
        if not box:
            continue
        name = str(m.get("person_name") or "陌生人")
        sim = float(m.get("similarity", 0.0))
        mt = m.get("match_type")
        color = (0, 220, 0) if mt == "known" else (0, 0, 230)
        label = f"{name} {sim:.2f}"
        gzh = m.get("gender_zh")
        age = m.get("age")
        if gzh and age is not None:
            label = f"{name} {gzh}{age}岁 {sim:.2f}"
        elif gzh:
            label = f"{name} {gzh} {sim:.2f}"
        elif age is not None:
            label = f"{name} {age}岁 {sim:.2f}"
        draw_labeled_box(frame, box, label, color, font_px=fs_px)


def _draw_plate_matches(frame, matches: Sequence[Mapping[str, Any]], fs_px: int) -> None:
    color_known = (0, 220, 0)
    color_unk = (0, 0, 230)
    for m in matches:
        box = m.get("box")
        if not box:
            continue
        plate_no = str(m.get("plate_no") or "")
        owner = str(m.get("owner_name") or "")
        mt = m.get("match_type")
        ocr_c = float(m.get("ocr_confidence", 0.0))
        if mt == "known":
            label = f"{plate_no}" + (f" {owner}" if owner else "")
            color = color_known
        else:
            label = plate_no
            color = color_unk
        label = f"{label} {ocr_c:.2f}"
        draw_labeled_box(frame, box, label, color, font_px=fs_px)


def _draw_fatigue(frame, detections: Mapping[str, Any], fs_px: int) -> None:
    fg = (detections.get("behaviors") or {}).get(FATIGUE_KEY) or {}
    color = _color_for_behavior(FATIGUE_KEY)
    for bx in fg.get("boxes") or []:
        nm = str(bx.get("name") or "疲劳驾驶")
        draw_labeled_box(frame, bx.get("box"), nm, color, font_px=fs_px)


def _draw_ext(frame, detections: Mapping[str, Any], ek: str, fs_px: int) -> None:
    persons = detections.get("persons") or []
    br = (detections.get("behaviors") or {}).get(ek) or {}
    color = _color_for_behavior(ek)
    tag = label_zh_for_extension(ek)
    event_boxes = list(br.get("event_boxes") or [])
    if event_boxes:
        for eb in event_boxes:
            nm = tag or str(eb.get("name") or ek)
            sconf = float(eb.get("confidence", 0.0))
            draw_labeled_box(frame, eb.get("box"), f"{nm}: {sconf:.2f}", color, font_px=fs_px)
        return
    boxes = list(br.get("boxes") or [])
    if boxes:
        for bx in boxes:
            nm = str(bx.get("name") or tag)
            sconf = float(bx.get("confidence", 0.0))
            draw_labeled_box(frame, bx.get("box"), f"{nm}: {sconf:.2f}", color, font_px=fs_px)
        return
    for pi in br.get("person_indices") or []:
        pi = int(pi)
        if pi < 0 or pi >= len(persons):
            continue
        pb = persons[pi]["box"]
        sc = float(br.get("scores", {}).get(str(pi), 0.0))
        draw_labeled_box(frame, pb, f"{tag}: {sc:.2f}", color, font_px=fs_px)


def render_alert_frame(source, detections: Mapping[str, Any], unit: AlertUnit):
    """在干净底图上只画 unit 对应类型的框。"""
    frame = source.copy()
    fs_px = label_font_px(frame)
    kind = unit.kind
    if kind == "coco" and unit.cid is not None:
        items = (detections.get("by_class") or {}).get(unit.cid) or (detections.get("by_class") or {}).get(
            str(unit.cid)
        ) or []
        color = _bgr_for_class(int(unit.cid))
        prefix = COCO_NAMES.get(int(unit.cid), str(unit.cid))
        for it in items:
            _draw_box_item(frame, it, color, prefix, fs_px)
    elif kind == "call":
        _draw_call(frame, detections, fs_px)
    elif kind == "phone_play":
        _draw_phone_play(frame, detections, fs_px)
    elif kind == "gather":
        _draw_gather(frame, detections, fs_px)
    elif kind == "face":
        _draw_face_matches(frame, unit.matches, fs_px)
    elif kind == "plate":
        _draw_plate_matches(frame, unit.matches, fs_px)
    elif kind == "fatigue":
        _draw_fatigue(frame, detections, fs_px)
    elif kind == "ext" and unit.ext_key:
        _draw_ext(frame, detections, unit.ext_key, fs_px)
    return frame
