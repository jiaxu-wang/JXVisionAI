"""
检测核心：YOLO26 主检 + 行为插件融合 + 画框截图。

每路流对应一个 Detector 实例。主循环由 ``__main__.run_video_processing`` 驱动：
按 ``detection_interval`` 取帧 → ``detect()`` → ``process_results()`` → ``save_snapshot()``。

多路并行加载同一权重文件时加锁，避免 torch.load 竞态。
"""

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
    GATHER_KEY,
    NUM_COCO_CLASSES,
    PHONE_PLAY_KEY,
    FACE_RECOG_KEY,
    all_extension_keys,
    normalize_detections,
    label_zh_for_class,
    label_zh_for_extension,
    person_behavior_keys,
    scene_behavior_keys,
)
from visionai.config.settings import (
    CONF_THRESHOLD,
    GATHER_MIN_DURATION_SEC,
    GATHER_MIN_PERSONS,
    INFER_BACKEND,
    INFER_ON_DAEMON_ERROR,
    INFER_PRIMARY_VERSION,
    MAKE_CALL_MODEL_PATH,
    MAKE_CALL_REQUIRE_PERSON_OVERLAP,
    MAKE_CALL_USE_DEDICATED,
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
from visionai.utils.frame_draw import draw_labeled_box, label_font_px, put_text

logger = logging.getLogger(__name__)

# 多路流并行创建 Detector 时，同一权重路径的 torch.load 需要串行化
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
    FACE_RECOG_KEY: (0, 200, 0),
}


def _color_for_behavior(key: str):
    if key in _BEHAVIOR_COLORS:
        return _BEHAVIOR_COLORS[key]
    h = (abs(hash(key)) % 1000) / 1000.0
    r, g, b = colorsys.hsv_to_rgb(h, 0.75, 0.95)
    return int(b * 255), int(g * 255), int(r * 255)


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
        self._cpp_session_ready = False
        self._load_model()

    def _load_model(self):
        if (INFER_BACKEND or "").strip().lower() == "cpp":
            logger.info(
                "infer.backend=cpp：主检走 visionai-inferd（stream_id=%s）",
                self.stream_id or "(pending)",
            )
            if INFER_ON_DAEMON_ERROR == "fallback_python":
                # 预加载 Ultralytics 以便 daemon 故障时回退
                self._load_yolo_python()
            return
        self._load_yolo_python()

    def _load_yolo_python(self):
        """加载 [models] yolo_model（YOLO26 n/s/m/l/x .pt）。多路并行加载时加锁。"""
        try:
            logger.info("正在加载YOLO模型: %s", YOLO_MODEL)
            with _yolo_model_load_lock:
                self.model = YOLO(YOLO_MODEL)
            dev = yolo_inference_device()
            logger.info(
                "YOLO模型加载完成 path=%s device=%s",
                YOLO_MODEL,
                dev if dev is not None else "auto",
            )
        except Exception as e:
            logger.error(f"加载模型失败: {e}")
            raise

    def _ensure_cpp_session(self):
        sid = (self.stream_id or "").strip()
        if not sid:
            raise RuntimeError("cpp backend requires stream id (session_id)")
        if self._cpp_session_ready:
            return
        from visionai.core.infer_client import get_infer_client

        client = get_infer_client()
        if not client.ready():
            client.load_primary(version=INFER_PRIMARY_VERSION)
        client.open_session(sid, conf=float(CONF_THRESHOLD), imgsz=640)
        self._cpp_session_ready = True

    def _detect_python(self, frame):
        from visionai.core.infer_types import boxes_from_ultralytics

        if self.model is None:
            self._load_yolo_python()
        dev = yolo_inference_device()
        kw = {"conf": CONF_THRESHOLD}
        if dev is not None:
            kw["device"] = dev
        return boxes_from_ultralytics(self.model(frame, **kw))

    def detect(self, frame):
        """返回 DetectionBox 列表（python / cpp 统一）。"""
        try:
            if (INFER_BACKEND or "").strip().lower() != "cpp":
                return self._detect_python(frame)

            from visionai.core.infer_client import get_infer_client

            try:
                self._ensure_cpp_session()
                client = get_infer_client()
                result = client.infer((self.stream_id or "").strip(), frame)
                if not result.ok:
                    raise RuntimeError(f"{result.error_code}: {result.message}")
                return result.boxes
            except Exception as e:
                if INFER_ON_DAEMON_ERROR == "fallback_python":
                    logger.warning("inferd 失败，fallback_python: %s", e)
                    return self._detect_python(frame)
                logger.error("cpp 检测失败: %s", e)
                return []
        except Exception as e:
            logger.error(f"检测失败: {e}")
            return []

    def process_results_from_boxes(self, frame, boxes):
        """处理已归一化的 DetectionBox 列表（主路径）。"""
        return self.process_results(frame, boxes)

    def process_results(self, frame, results):
        """处理检测结果（接受 Ultralytics Results 或 DetectionBox 列表）。

        「打电话」：人物框与手机框存在重叠（交集面积 > 0）即记为一次打电话配对。

        「人员聚集」：单帧检出人物数 ≥ GATHER_MIN_PERSONS 即满足条件；可选持续
        GATHER_MIN_DURATION_SEC 防抖（0 为立即告警）。仅依赖 person 框。

        「打电话 / 玩手机」：均需人物框与手机框交集。安装姿态模型时用 YOLO26-pose
        将手机中心与肩头耳根/手腕距离分为「打电话」与「玩手机」；无姿态或未加载则按
        手机竖直占比粗分。

        专模：训练实验室部署的 scene / person_event / violation 插件。

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
        face_recog_on = self.detections.get(FACE_RECOG_KEY, False)
        p_keys = person_behavior_keys()
        s_keys = scene_behavior_keys()
        person_behavior_on = any(self.detections.get(k, False) for k in p_keys)
        scene_behavior_on = any(self.detections.get(k, False) for k in s_keys)
        use_dedicated_call = (
            call_on
            and MAKE_CALL_USE_DEDICATED
            and bool((MAKE_CALL_MODEL_PATH or "").strip())
        )
        need_coco_for_call = call_on and (
            not use_dedicated_call or MAKE_CALL_REQUIRE_PERSON_OVERLAP
        )
        other_person_behaviors = any(
            self.detections.get(k, False) for k in p_keys if k != CALL_KEY
        )
        collect_person = (
            alarm_person
            or gather_on
            or phone_play_on
            or need_coco_for_call
            or other_person_behaviors
        )
        collect_phone = alarm_phone or (call_on and not use_dedicated_call) or phone_play_on
        behavior_needed = person_behavior_on or scene_behavior_on or face_recog_on
        behavior_src = frame.copy() if behavior_needed else None

        from visionai.core.infer_types import DetectionBox, boxes_from_ultralytics

        if isinstance(results, list) and (not results or isinstance(results[0], DetectionBox)):
            det_boxes = results
        else:
            det_boxes = boxes_from_ultralytics(results)

        for box in det_boxes:
            x1, y1, x2, y2 = map(int, (box.x1, box.y1, box.x2, box.y2))
            conf = float(box.conf)
            cls = int(box.class_id)

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
                label = f"{COCO_NAMES.get(cls, str(cls))}: {conf:.2f}"
                draw_labeled_box(frame, (x1, y1, x2, y2), label, color)

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

        person_behavior_alerts: dict[str, set[int]] = {}
        for bk in p_keys:
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
            for bk, pset in person_behavior_alerts.items():
                if idx in pset:
                    return True
            return False

        fs_px = label_font_px(frame)
        for i, person in enumerate(persons):
            if not _person_should_draw(i):
                continue
            x1, y1, x2, y2 = person["box"]
            conf = person["confidence"]
            color = _bgr_for_class(0)
            draw_labeled_box(
                frame,
                (x1, y1, x2, y2),
                f"{COCO_NAMES[0]}: {conf:.2f}",
                color,
                font_px=fs_px,
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
            draw_labeled_box(
                frame,
                (x1, y1, x2, y2),
                f"cell phone: {conf:.2f}",
                color,
                font_px=fs_px,
            )

        for c in calls:
            pb = c["person"]["box"]
            conf = c["confidence"]
            put_text(
                frame,
                f"CALLING: {conf:.2f}",
                (pb[0], max(pb[1] - 10, 20)),
                (0, 0, 255),
                font_px=fs_px,
            )

        for ph_ev in phone_play_matches:
            pb = ph_ev["person"]["box"]
            conf = ph_ev["confidence"]
            put_text(
                frame,
                f"PLAY_PHONE: {conf:.2f}",
                (pb[0], max(pb[1] - 28, 20)),
                (204, 120, 0),
                font_px=fs_px,
            )

        if use_dedicated_call and call_on and call_result.get("alert"):
            color_call = _color_for_behavior(CALL_KEY)
            for pi in call_result.get("person_indices") or []:
                pi = int(pi)
                if pi < 0 or pi >= len(persons):
                    continue
                pb = persons[pi]["box"]
                sc = float(call_result.get("scores", {}).get(str(pi), 0.0))
                put_text(
                    frame,
                    f"CALLING: {sc:.2f}",
                    (pb[0], max(pb[1] - 10, 20)),
                    color_call,
                    font_px=fs_px,
                )
            for eb in call_result.get("event_boxes") or []:
                nm = str(eb.get("name") or "phone")
                sconf = float(eb.get("confidence", 0.0))
                label = (
                    f"{label_zh_for_extension(CALL_KEY)}: {sconf:.2f}"
                    if call_result.get("standalone")
                    else f"{nm}: {sconf:.2f}"
                )
                draw_labeled_box(
                    frame, eb.get("box"), label, color_call, font_px=fs_px
                )

        for bk, pset in person_behavior_alerts.items():
            if bk == CALL_KEY:
                continue
            br = behaviors_out.get(bk, {})
            color = _color_for_behavior(bk)
            tag = label_zh_for_extension(bk)
            for pi in pset:
                if pi < 0 or pi >= len(persons):
                    continue
                pb = persons[pi]["box"]
                sc = float(br.get("scores", {}).get(str(pi), 0.0))
                put_text(
                    frame,
                    f"{tag}: {sc:.2f}",
                    (pb[0], max(pb[1] - 10, 20)),
                    color,
                    font_px=fs_px,
                )
            for eb in br.get("event_boxes") or []:
                nm = str(eb.get("name") or bk)
                sconf = float(eb.get("confidence", 0.0))
                draw_labeled_box(
                    frame, eb.get("box"), f"{nm}: {sconf:.2f}", color, font_px=fs_px
                )

        for sk in s_keys:
            if not self.detections.get(sk, False):
                continue
            sr = behaviors_out.get(sk, {})
            if not sr.get("alert"):
                continue
            color = _color_for_behavior(sk)
            tag = label_zh_for_extension(sk)
            for bx in sr.get("boxes") or []:
                nm = str(bx.get("name") or tag)
                sconf = float(bx.get("confidence", 0.0))
                draw_labeled_box(
                    frame, bx.get("box"), f"{nm}: {sconf:.2f}", color, font_px=fs_px
                )

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

        if gathering_alert and gather_on and gather_cluster_indices:
            pts = []
            for gi in gather_cluster_indices:
                cx, cy = _center_xyxy(persons[gi]["box"])
                pts.append((int(cx), int(cy)))
            pts_np = np.array(pts, dtype=np.int32)
            color_gather = (0, 165, 255)
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
                f"GATHERING: {len(gather_cluster_indices)}",
                (cx, max(cy - 10, 20)),
                color_gather,
                font_px=fs_px,
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

        fr_saved = behaviors_saved.get(FACE_RECOG_KEY, {})
        if self.detections.get(FACE_RECOG_KEY, False) and fr_saved.get("alert"):
            alert_matches = fr_saved.get("alert_matches") or []
            if alert_matches:
                should_save = True
                # 告警仍由 alert_matches 触发；检测类型与截图对齐，写入本帧全部 matches
                # （持续时长防抖会导致「框上已有库内人+陌生人，类型却只写其中一个」）
                frame_matches = fr_saved.get("matches") or alert_matches
                fr_extra_matches = []
                for m in frame_matches:
                    name = str(m.get("person_name") or "陌生人")
                    mt = m.get("match_type")
                    sim = float(m.get("similarity", 0.0))
                    gzh = m.get("gender_zh")
                    age = m.get("age")
                    attr = ""
                    if gzh and age is not None:
                        attr = f"{gzh}{age}岁"
                    elif gzh:
                        attr = str(gzh)
                    elif age is not None:
                        attr = f"{age}岁"
                    if mt == "known":
                        label = f"人脸识别: {name}"
                    else:
                        label = "人脸识别: 陌生人"
                    if attr:
                        label = f"{label}({attr})"
                    if label not in detection_types:
                        detection_types.append(label)
                    info.append(f"{label} ({sim:.2f})")
                    item = {
                        "person_id": m.get("person_id"),
                        "person_name": name,
                        "similarity": sim,
                        "match_type": mt,
                        "box": m.get("box"),
                    }
                    if m.get("gender") is not None:
                        item["gender"] = int(m["gender"])
                    if age is not None:
                        item["age"] = int(age)
                    if gzh:
                        item["gender_zh"] = str(gzh)
                    fr_extra_matches.append(item)
                detection_extra = {
                    "face_recognition": {
                        "trigger_types": fr_saved.get("trigger_types") or [],
                        "matches": fr_extra_matches,
                        "alert_matches": [
                            {
                                "person_id": m.get("person_id"),
                                "person_name": str(m.get("person_name") or "陌生人"),
                                "similarity": float(m.get("similarity", 0.0)),
                                "match_type": m.get("match_type"),
                            }
                            for m in alert_matches
                        ],
                    }
                }

        p_keys = person_behavior_keys()
        for ek in all_extension_keys():
            if ek in (FACE_RECOG_KEY, PHONE_PLAY_KEY, GATHER_KEY):
                continue
            if ek == CALL_KEY and detections.get("calls"):
                # 已在上方按 calls 记录
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
            elif ek in p_keys or ek == CALL_KEY:
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

            # 异步告警队列：检测线程只落盘并投递，由 alert_worker 上传/写库/发信
            from visionai.config.settings import ALERT_QUEUE_ENABLED
            from visionai.core.alert_queue import enqueue_alert_job

            if ALERT_QUEUE_ENABLED:
                job = {
                    "stream_name": self.stream_name,
                    "stream_id": (self.stream_id or "").strip(),
                    "detection_types": detection_types,
                    "image_path": save_path,
                    "timestamp": now.isoformat(timespec="seconds"),
                    "extra": detection_extra,
                    "alert_emails": list(self.alert_emails or []),
                    "alert_email_enabled": bool(self.alert_email_enabled),
                    "alert_webhook_urls": list(self.alert_webhook_urls or []),
                    "alert_webhook_enabled": bool(self.alert_webhook_enabled),
                }
                if enqueue_alert_job(job):
                    if info:
                        logger.info(
                            f"[{self.stream_name}] 检测到: {', '.join(info)}，已入告警队列"
                        )
                    return True
                logger.warning(
                    f"[{self.stream_name}] 告警入队失败，回退同步写库"
                )

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
