"""检测模块"""

import colorsys
import logging
import os
import threading
import time
from datetime import datetime
from typing import List

import cv2
import numpy as np
from ultralytics import YOLO

from visionai.config.detection_catalog import (
    CALL_KEY,
    COCO_NAMES,
    EXTENSION_KEYS,
    GATHER_KEY,
    NUM_COCO_CLASSES,
    PERSON_BEHAVIOR_KEYS,
    PHONE_PLAY_KEY,
    SCENE_BEHAVIOR_KEYS,
    SMOKE_KEY,
    FACE_RECOG_KEY,
    normalize_detections,
    label_zh_for_class,
    label_zh_for_extension,
)
from visionai.config.settings import (
    CONF_THRESHOLD,
    GATHER_MIN_DURATION_SEC,
    GATHER_MIN_PERSONS,
    MAKE_CALL_MODEL_PATH,
    MAKE_CALL_REQUIRE_PERSON_OVERLAP,
    MAKE_CALL_USE_DEDICATED,
    SMOKING_REQUIRE_PERSON_OVERLAP,
    OBJECT_STORAGE_KEEP_LOCAL,
    POSE_FOR_PHONE_ENABLED,
    SAVE_DIR,
    SAVE_FORMAT,
    SAVE_INTERVAL,
    YOLO_MODEL,
    yolo_inference_device,
)
from visionai.core.behaviors import BehaviorContext, run_behaviors
from visionai.core.face_recognition_config import (
    default_face_recognition_config,
    normalize_face_recognition_config,
)
from visionai.core import pose_phone
from visionai.core.object_storage import get_object_storage
from visionai.core.redis_manager import redis_manager
from visionai.utils.alert_email import notify_alert_by_email
from visionai.utils.alert_webhook import notify_alert_by_webhooks
from visionai.utils.frame_draw import draw_labeled_box, put_text

logger = logging.getLogger(__name__)

# 多路流会并行创建多个 Detector，若同时对同一路径做 torch.load，可能 OSError(22) Invalid argument
_yolo_model_load_lock = threading.Lock()


def _bgr_for_class(class_id: int):
    h = (class_id * 0.618033988749895) % 1.0
    r, g, b = colorsys.hsv_to_rgb(h, 0.82, 0.96)
    return int(b * 255), int(g * 255), int(r * 255)


def _center_xyxy(box: tuple[int, int, int, int]) -> tuple[float, float]:
    x1, y1, x2, y2 = box
    return (x1 + x2) * 0.5, (y1 + y2) * 0.5


_BEHAVIOR_COLORS = {
    CALL_KEY: (0, 0, 255),
    SMOKE_KEY: (60, 180, 255),
    "fall": (0, 140, 255),
    "mask": (180, 80, 255),
    "reflective_vest": (0, 200, 200),
    "safety_helmet": (0, 215, 255),
    "sleeping": (200, 160, 60),
    "face": (80, 200, 255),
    FACE_RECOG_KEY: (0, 200, 0),
    "flame": (0, 80, 255),
    "license_plate": (255, 180, 0),
    "road_waterlogging": (255, 120, 0),
}


def _boxes_overlap_xyxy(box_a, box_b) -> bool:
    """两轴对齐矩形是否有面积大于 0 的交集（人物框与手机框重叠即视为可能打电话）。"""
    ax1, ay1, ax2, ay2 = box_a
    bx1, by1, bx2, by2 = box_b
    ix1, iy1 = max(ax1, bx1), max(ay1, by1)
    ix2, iy2 = min(ax2, bx2), min(ay2, by2)
    return ix1 < ix2 and iy1 < iy2


class Detector:
    """检测器类"""

    def __init__(self, stream_name="default", save_dir=None, detections=None, stream_id=None):
        self.stream_name = stream_name
        self.stream_id = stream_id
        self.save_dir = save_dir
        self.detections = normalize_detections(detections)
        self.model = None
        self.last_save_time = 0
        self._gather_since = None
        self._behavior_state: dict = {}
        self.alert_emails: List[str] = []
        self.alert_email_enabled: bool = True
        self.alert_webhook_urls: List[str] = []
        self.alert_webhook_enabled: bool = False
        self.face_recognition_config = default_face_recognition_config()
        self._load_model()

    def _load_model(self):
        try:
            logger.info("正在加载YOLO模型…")
            with _yolo_model_load_lock:
                self.model = YOLO(YOLO_MODEL)
            dev = yolo_inference_device()
            logger.info(
                "YOLO模型加载完成；推理设备: %s",
                dev if dev is not None else "auto（Ultralytics 默认，通常有 GPU 则用 GPU）",
            )
        except Exception as e:
            logger.error(f"加载模型失败: {e}")
            raise

    def detect(self, frame):
        try:
            dev = yolo_inference_device()
            kw = {"conf": CONF_THRESHOLD}
            if dev is not None:
                kw["device"] = dev
            results = self.model(frame, **kw)
            return results
        except Exception as e:
            logger.error(f"检测失败: {e}")
            return []

    def process_results(self, frame, results):
        """处理检测结果。

        「打电话」：人物框与手机框存在重叠（交集面积 > 0）即记为一次打电话配对。

        「人员聚集」：单帧检出人物数 ≥ GATHER_MIN_PERSONS 即满足条件；可选持续
        GATHER_MIN_DURATION_SEC 防抖（0 为立即告警）。仅依赖 person 框。

        「吸烟」：行为层插件，YOLO person 框裁剪后经 ONNX 分类（见 SMOKING_* 配置）。

        「打电话 / 玩手机」：均需人物框与手机框交集。安装姿态模型时用 YOLOv8-pose
        将手机中心与肩头耳根/手腕距离分为「打电话」与「玩手机」；无姿态或未加载则按
        手机竖直占比粗分。

        绘制：
        - 仅开「人物/手机」告警：按开关绘制全部检出的人物或手机。
        - 仅开「打电话」：只绘制参与该类配对的人物框与手机框，并标注 CALLING。
        - 仅开「玩手机」：只绘制参与该类配对的人物与手机框，并标注 PLAY_PHONE。
        """
        persons = []
        cell_phones = []
        by_class = {i: [] for i in range(NUM_COCO_CLASSES)}

        alarm_person = self.detections.get("0", False)
        alarm_phone = self.detections.get("67", False)
        call_on = self.detections.get(CALL_KEY, False)
        phone_play_on = self.detections.get(PHONE_PLAY_KEY, False)
        gather_on = self.detections.get(GATHER_KEY, False)
        smoke_on = self.detections.get(SMOKE_KEY, False)
        face_recog_on = self.detections.get(FACE_RECOG_KEY, False)
        person_behavior_on = any(self.detections.get(k, False) for k in PERSON_BEHAVIOR_KEYS)
        scene_behavior_on = any(self.detections.get(k, False) for k in SCENE_BEHAVIOR_KEYS)
        use_dedicated_call = (
            call_on
            and MAKE_CALL_USE_DEDICATED
            and bool((MAKE_CALL_MODEL_PATH or "").strip())
        )
        need_coco_for_call = call_on and (
            not use_dedicated_call or MAKE_CALL_REQUIRE_PERSON_OVERLAP
        )
        need_coco_for_smoke = smoke_on and SMOKING_REQUIRE_PERSON_OVERLAP
        other_person_behaviors = any(
            self.detections.get(k, False)
            for k in PERSON_BEHAVIOR_KEYS
            if k not in (CALL_KEY, SMOKE_KEY)
        )
        collect_person = (
            alarm_person
            or gather_on
            or phone_play_on
            or need_coco_for_call
            or need_coco_for_smoke
            or other_person_behaviors
        )
        collect_phone = alarm_phone or (call_on and not use_dedicated_call) or phone_play_on
        behavior_needed = smoke_on or person_behavior_on or scene_behavior_on or face_recog_on
        behavior_src = frame.copy() if behavior_needed else None

        for result in results:
            if result.boxes is None:
                continue
            for box in result.boxes:
                x1, y1, x2, y2 = map(int, box.xyxy[0])
                conf = float(box.conf)
                cls = int(box.cls)

                if cls < 0 or cls >= NUM_COCO_CLASSES:
                    continue

                if cls == 0 and collect_person:
                    persons.append({"box": (x1, y1, x2, y2), "confidence": conf})
                elif cls == 67 and collect_phone:
                    cell_phones.append({"box": (x1, y1, x2, y2), "confidence": conf})
                elif self.detections.get(str(cls), False):
                    det = {"box": (x1, y1, x2, y2), "confidence": conf}
                    by_class[cls].append(det)
                    color = _bgr_for_class(cls)
                    cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)
                    label = COCO_NAMES.get(cls, str(cls))
                    cv2.putText(
                        frame,
                        f"{label}: {conf:.2f}",
                        (x1, y1 - 10),
                        cv2.FONT_HERSHEY_SIMPLEX,
                        0.5,
                        color,
                        2,
                    )

        if alarm_person:
            for p in persons:
                by_class[0].append(p)
        if alarm_phone:
            for ph in cell_phones:
                by_class[67].append(ph)

        calls = []
        phone_play_matches: list = []
        persons_in_call: set[int] = set()
        phones_in_call: set[int] = set()
        persons_in_play: set[int] = set()
        phones_in_play: set[int] = set()

        if (phone_play_on or (call_on and not use_dedicated_call)) and persons and cell_phones:
            raw_pairs = []
            for pi, person in enumerate(persons):
                pb = person["box"]
                for ti, phone in enumerate(cell_phones):
                    if _boxes_overlap_xyxy(pb, phone["box"]):
                        raw_pairs.append((pi, ti, person, phone))

            if raw_pairs:
                skels: list = []
                if POSE_FOR_PHONE_ENABLED:
                    skels = pose_phone.infer_pose_skeletons(frame)

                for pi, ti, person, phone in raw_pairs:
                    pb = person["box"]
                    ph_box = phone["box"]
                    sk_m = pose_phone.match_skeleton_for_person(pb, skels)
                    mode = pose_phone.classify_phone_overlap_mode(pb, ph_box, sk_m)
                    ev = {
                        "person": person,
                        "phone": phone,
                        "person_idx": pi,
                        "phone_idx": ti,
                        "confidence": min(person["confidence"], phone["confidence"]),
                    }
                    if mode == "call" and call_on:
                        calls.append(ev)
                        persons_in_call.add(pi)
                        phones_in_call.add(ti)
                    elif mode == "play" and phone_play_on:
                        phone_play_matches.append(ev)
                        persons_in_play.add(pi)
                        phones_in_play.add(ti)

        gathering_alert = False
        gather_cluster_indices: list[int] = []
        gather_count = len(persons)
        now = time.time()
        if gather_on:
            min_p = GATHER_MIN_PERSONS
            raw = len(persons) >= min_p
            if raw:
                gather_cluster_indices = list(range(len(persons)))
            if raw:
                if self._gather_since is None:
                    self._gather_since = now
                if now - self._gather_since >= GATHER_MIN_DURATION_SEC:
                    gathering_alert = True
            else:
                self._gather_since = None
        else:
            self._gather_since = None

        behaviors_out: dict = {}
        if behavior_src is not None:
            ctx = BehaviorContext(
                frame_source=behavior_src,
                persons=persons,
                cell_phones=cell_phones,
                stream_name=self.stream_name,
                now=now,
                extra={"face_recognition_config": self.face_recognition_config},
            )
            behaviors_out = run_behaviors(ctx, self._behavior_state, self.detections)

        call_result = behaviors_out.get(CALL_KEY, {})
        if use_dedicated_call and call_result.get("alert"):
            if call_result.get("standalone"):
                for eb in call_result.get("event_boxes") or []:
                    calls.append(
                        {
                            "person": None,
                            "phone": eb,
                            "person_idx": -1,
                            "phone_idx": -1,
                            "confidence": float(eb.get("confidence", 0.0)),
                        }
                    )
            else:
                for pi in call_result.get("person_indices") or []:
                    pi = int(pi)
                    if pi < 0 or pi >= len(persons):
                        continue
                    persons_in_call.add(pi)
                    sc = float(call_result.get("scores", {}).get(str(pi), 0.0))
                    calls.append(
                        {
                            "person": persons[pi],
                            "phone": None,
                            "person_idx": pi,
                            "phone_idx": -1,
                            "confidence": sc,
                        }
                    )

        smoke_result = behaviors_out.get(SMOKE_KEY, {})
        smoking_alert = bool(smoke_result.get("alert"))
        smoking_indices = (
            set()
            if smoke_result.get("standalone")
            else set(smoke_result.get("person_indices", []))
        )
        person_behavior_alerts: dict[str, set[int]] = {}
        for bk in PERSON_BEHAVIOR_KEYS:
            if bk == SMOKE_KEY:
                continue
            if bk == CALL_KEY and not use_dedicated_call:
                continue
            if not self.detections.get(bk, False):
                continue
            br = behaviors_out.get(bk, {})
            if br.get("alert"):
                person_behavior_alerts[bk] = set(int(i) for i in br.get("person_indices") or [])

        gather_cluster_set = set(gather_cluster_indices)

        def _person_should_draw(idx: int) -> bool:
            if alarm_person:
                return True
            if call_on and idx in persons_in_call:
                return True
            if phone_play_on and idx in persons_in_play:
                return True
            if gather_on and gathering_alert and idx in gather_cluster_set:
                return True
            if smoke_on and smoking_alert and idx in smoking_indices:
                return True
            for bk, pset in person_behavior_alerts.items():
                if idx in pset:
                    return True
            return False

        for i, person in enumerate(persons):
            if not _person_should_draw(i):
                continue
            x1, y1, x2, y2 = person["box"]
            conf = person["confidence"]
            color = _bgr_for_class(0)
            cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)
            cv2.putText(
                frame,
                f"{COCO_NAMES[0]}: {conf:.2f}",
                (x1, y1 - 10),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.5,
                color,
                2,
            )

        for i, phone in enumerate(cell_phones):
            if not (
                alarm_phone
                or (call_on and i in phones_in_call)
                or (phone_play_on and i in phones_in_play)
            ):
                continue
            x1, y1, x2, y2 = phone["box"]
            conf = phone["confidence"]
            color = _bgr_for_class(67)
            cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)
            cv2.putText(
                frame,
                f"cell phone: {conf:.2f}",
                (x1, y1 - 10),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.5,
                color,
                2,
            )

        for c in calls:
            pb = c["person"]["box"]
            conf = c["confidence"]
            cv2.putText(
                frame,
                f"CALLING: {conf:.2f}",
                (pb[0], pb[1] - 20),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.6,
                (0, 0, 255),
                2,
            )

        for ph_ev in phone_play_matches:
            pb = ph_ev["person"]["box"]
            conf = ph_ev["confidence"]
            cv2.putText(
                frame,
                f"PLAY_PHONE: {conf:.2f}",
                (pb[0], pb[1] - 35),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.6,
                (204, 120, 0),
                2,
            )

        if smoking_alert and smoke_on:
            color_smoke = _BEHAVIOR_COLORS[SMOKE_KEY]
            for si in smoking_indices:
                if si < 0 or si >= len(persons):
                    continue
                pb = persons[si]["box"]
                sc = float(smoke_result.get("scores", {}).get(str(si), 0.0))
                cv2.putText(
                    frame,
                    f"SMOKING: {sc:.2f}",
                    (pb[0], pb[1] - 20),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.6,
                    color_smoke,
                    2,
                )
            ev_boxes = smoke_result.get("event_boxes") or smoke_result.get("smoking_boxes") or []
            for sb in ev_boxes:
                nm = str(sb.get("name") or "smoking")
                sconf = float(sb.get("confidence", 0.0))
                label = (
                    f"{label_zh_for_extension(SMOKE_KEY)}: {sconf:.2f}"
                    if smoke_result.get("standalone")
                    else f"{nm}: {sconf:.2f}"
                )
                draw_labeled_box(frame, sb.get("box"), label, color_smoke)

        if use_dedicated_call and call_on and call_result.get("alert"):
            color_call = _BEHAVIOR_COLORS[CALL_KEY]
            for pi in call_result.get("person_indices") or []:
                pi = int(pi)
                if pi < 0 or pi >= len(persons):
                    continue
                pb = persons[pi]["box"]
                sc = float(call_result.get("scores", {}).get(str(pi), 0.0))
                cv2.putText(
                    frame,
                    f"CALLING: {sc:.2f}",
                    (pb[0], pb[1] - 20),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.6,
                    color_call,
                    2,
                )
            for eb in call_result.get("event_boxes") or []:
                nm = str(eb.get("name") or "phone")
                sconf = float(eb.get("confidence", 0.0))
                label = (
                    f"{label_zh_for_extension(CALL_KEY)}: {sconf:.2f}"
                    if call_result.get("standalone")
                    else f"{nm}: {sconf:.2f}"
                )
                draw_labeled_box(frame, eb.get("box"), label, color_call)

        for bk, pset in person_behavior_alerts.items():
            if bk == CALL_KEY:
                continue
            br = behaviors_out.get(bk, {})
            color = _BEHAVIOR_COLORS.get(bk, (200, 200, 0))
            tag = label_zh_for_extension(bk)
            for pi in pset:
                if pi < 0 or pi >= len(persons):
                    continue
                pb = persons[pi]["box"]
                sc = float(br.get("scores", {}).get(str(pi), 0.0))
                put_text(
                    frame,
                    f"{tag}: {sc:.2f}",
                    (pb[0], pb[1] - 20),
                    color,
                    font_scale=0.6,
                )
            for eb in br.get("event_boxes") or []:
                nm = str(eb.get("name") or bk)
                sconf = float(eb.get("confidence", 0.0))
                draw_labeled_box(frame, eb.get("box"), f"{nm}: {sconf:.2f}", color)

        for sk in SCENE_BEHAVIOR_KEYS:
            if not self.detections.get(sk, False):
                continue
            sr = behaviors_out.get(sk, {})
            if not sr.get("alert"):
                continue
            color = _BEHAVIOR_COLORS.get(sk, (180, 180, 0))
            tag = label_zh_for_extension(sk)
            for bx in sr.get("boxes") or []:
                nm = str(bx.get("name") or tag)
                sconf = float(bx.get("confidence", 0.0))
                draw_labeled_box(frame, bx.get("box"), f"{nm}: {sconf:.2f}", color)

        fr_result = behaviors_out.get(FACE_RECOG_KEY, {})
        if face_recog_on:
            alert_keys: set = set()
            if fr_result.get("alert"):
                for m in fr_result.get("alert_matches") or []:
                    if m.get("match_type") == "known":
                        alert_keys.add(str(m.get("person_id") or ""))
                    else:
                        alert_keys.add(f"unknown_{m.get('face_key')}")
            for m in fr_result.get("matches") or []:
                box = m.get("box")
                if not box:
                    continue
                name = str(m.get("person_name") or "陌生人")
                sim = float(m.get("similarity", 0.0))
                mt = m.get("match_type")
                if mt == "known":
                    ak = str(m.get("person_id") or "")
                else:
                    ak = f"unknown_{m.get('face_key')}"
                is_alert = ak in alert_keys
                if mt == "known":
                    color = (0, 220, 0) if is_alert else (0, 180, 180)
                else:
                    color = (0, 0, 230) if is_alert else (0, 140, 255)
                draw_labeled_box(frame, box, f"{name} {sim:.2f}", color)

        if gathering_alert and gather_on and gather_cluster_indices:
            pts = []
            for gi in gather_cluster_indices:
                cx, cy = _center_xyxy(persons[gi]["box"])
                pts.append((int(cx), int(cy)))
            pts_np = np.array(pts, dtype=np.int32)
            color_gather = (0, 165, 255)
            if len(pts_np) >= 3:
                hull = cv2.convexHull(pts_np)
                cv2.polylines(frame, [hull], True, color_gather, 2)
            elif len(pts_np) == 2:
                cv2.line(frame, tuple(pts_np[0]), tuple(pts_np[1]), color_gather, 2)
            cx = int(sum(p[0] for p in pts) / len(pts))
            cy = int(sum(p[1] for p in pts) / len(pts))
            cv2.putText(
                frame,
                f"GATHERING: {len(gather_cluster_indices)}",
                (cx, max(cy - 10, 20)),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.6,
                color_gather,
                2,
            )

        detections = {
            "persons": persons,
            "cell_phones": cell_phones,
            "calls": calls,
            "phone_play": phone_play_matches,
            "by_class": by_class,
            "gathering_alert": gathering_alert,
            "gather_cluster_indices": gather_cluster_indices,
            "gather_count": gather_count,
            "behaviors": behaviors_out,
        }
        return frame, detections

    def save_snapshot(self, frame, detections):
        current_time = time.time()
        if current_time - self.last_save_time < SAVE_INTERVAL:
            return False

        should_save = False
        info = []
        detection_types = []
        detection_extra = None

        by_class = detections.get("by_class", {})
        for cid, items in by_class.items():
            if not items:
                continue
            key = str(int(cid))
            if not self.detections.get(key, False):
                continue
            should_save = True
            zh = label_zh_for_class(int(cid))
            info.append(f"{zh}: {len(items)}")
            detection_types.append(zh)

        if self.detections.get(CALL_KEY, False) and detections.get("calls"):
            should_save = True
            n_call = len(detections["calls"])
            info.append(f"打电话: {n_call}")
            detection_types.append("打电话")

        if self.detections.get(PHONE_PLAY_KEY, False) and detections.get("phone_play"):
            should_save = True
            info.append(f"玩手机: {len(detections['phone_play'])}")
            detection_types.append("玩手机")

        if self.detections.get(GATHER_KEY, False) and detections.get("gathering_alert"):
            n_g = len(detections.get("gather_cluster_indices") or [])
            should_save = True
            info.append(f"人员聚集: {n_g}")
            detection_types.append("人员聚集")

        behaviors_saved = detections.get("behaviors", {}) or {}
        smoke_saved = behaviors_saved.get(SMOKE_KEY, {})
        if self.detections.get(SMOKE_KEY, False) and smoke_saved.get("alert"):
            should_save = True
            if smoke_saved.get("standalone"):
                n_s = len(smoke_saved.get("event_boxes") or [])
            else:
                n_s = len(smoke_saved.get("person_indices") or [])
            info.append(f"吸烟: {n_s}")
            detection_types.append("吸烟")

        fr_saved = behaviors_saved.get(FACE_RECOG_KEY, {})
        if self.detections.get(FACE_RECOG_KEY, False) and fr_saved.get("alert"):
            alert_matches = fr_saved.get("alert_matches") or []
            if alert_matches:
                should_save = True
                fr_extra_matches = []
                for m in alert_matches:
                    name = str(m.get("person_name") or "陌生人")
                    mt = m.get("match_type")
                    sim = float(m.get("similarity", 0.0))
                    if mt == "known":
                        label = f"人脸识别: {name}"
                    else:
                        label = "人脸识别: 陌生人"
                    detection_types.append(label)
                    info.append(f"{label} ({sim:.2f})")
                    fr_extra_matches.append(
                        {
                            "person_id": m.get("person_id"),
                            "person_name": name,
                            "similarity": sim,
                            "match_type": mt,
                            "box": m.get("box"),
                        }
                    )
                detection_extra = {
                    "face_recognition": {
                        "trigger_types": fr_saved.get("trigger_types") or [],
                        "matches": fr_extra_matches,
                    }
                }

        for ek in EXTENSION_KEYS:
            if ek in (SMOKE_KEY, FACE_RECOG_KEY):
                continue
            if not self.detections.get(ek, False):
                continue
            br = behaviors_saved.get(ek, {})
            if not br.get("alert"):
                continue
            should_save = True
            zh = label_zh_for_extension(ek)
            if br.get("standalone"):
                n = len(br.get("event_boxes") or [])
            elif ek in PERSON_BEHAVIOR_KEYS or ek == CALL_KEY:
                n = len(br.get("person_indices") or [])
            else:
                n = int(br.get("count") or len(br.get("boxes") or []))
            info.append(f"{zh}: {n}")
            detection_types.append(zh)

        if not should_save:
            return False

        now = datetime.now()
        timestamp = now.strftime(SAVE_FORMAT)
        save_dir = self.save_dir or SAVE_DIR
        save_path = os.path.join(save_dir, timestamp)

        try:
            cv2.imwrite(save_path, frame)
            self.last_save_time = current_time

            object_key = None
            storage_kind = None
            store = get_object_storage()
            if store:
                rel_name = os.path.basename(save_path)
                sid = (self.stream_id or "").strip()
                if not sid and redis_manager and redis_manager.is_connected():
                    sid = redis_manager.get_stream_id_by_name(self.stream_name) or ""
                sid = (sid or "").strip() or "unknown"
                s3_key = store.build_snapshot_key(sid, rel_name)
                try:
                    ur = store.upload_file(
                        save_path, s3_key, content_type="image/jpeg"
                    )
                    object_key = ur.object_key
                    storage_kind = ur.kind
                except Exception as ex:
                    logger.error(
                        f"[{self.stream_name}] 对象存储上传失败: {ex}",
                        exc_info=True,
                    )

            path_for_redis = save_path
            if object_key and not OBJECT_STORAGE_KEEP_LOCAL:
                if os.path.isfile(save_path):
                    try:
                        os.remove(save_path)
                    except OSError as ex:
                        logger.warning(
                            f"[{self.stream_name}] 仅对象存储时删除本地文件失败: {ex}"
                        )
                path_for_redis = ""
            if info:
                where = object_key or path_for_redis or "(无)"
                logger.info(
                    f"[{self.stream_name}] 检测到: {', '.join(info)}，存储: {where}"
                )

            rec_id = redis_manager.save_detection(
                stream_name=self.stream_name,
                detection_types=detection_types,
                image_path=path_for_redis,
                timestamp=now,
                object_key=object_key,
                storage_kind=storage_kind,
                extra=detection_extra,
            )
            if rec_id and self.alert_emails and self.alert_email_enabled:
                img_for_mail = (
                    path_for_redis
                    if path_for_redis and os.path.isfile(path_for_redis)
                    else None
                )
                notify_alert_by_email(
                    stream_name=self.stream_name,
                    recipients=self.alert_emails,
                    detection_types=detection_types,
                    image_path=img_for_mail,
                    timestamp=now,
                )
            if rec_id and self.alert_webhook_enabled and self.alert_webhook_urls:
                notify_alert_by_webhooks(
                    stream_name=self.stream_name,
                    stream_id=(self.stream_id or "").strip() or None,
                    webhook_urls=self.alert_webhook_urls,
                    detection_types=detection_types,
                    image_path=path_for_redis or None,
                    object_key=object_key,
                    storage_kind=storage_kind,
                    detection_id=rec_id,
                    timestamp=now,
                )
            return True
        except Exception as e:
            logger.error(f"[{self.stream_name}] 保存截图失败: {e}")
            return False
