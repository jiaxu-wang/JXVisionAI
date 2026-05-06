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
    GATHER_KEY,
    NUM_COCO_CLASSES,
    PHONE_PLAY_KEY,
    SMOKE_KEY,
    normalize_detections,
    label_zh_for_class,
)
from visionai.config.settings import (
    CONF_THRESHOLD,
    GATHER_MIN_DURATION_SEC,
    GATHER_MIN_PERSONS,
    OBJECT_STORAGE_KEEP_LOCAL,
    POSE_FOR_PHONE_ENABLED,
    SAVE_DIR,
    SAVE_FORMAT,
    SAVE_INTERVAL,
    YOLO_MODEL,
    yolo_inference_device,
)
from visionai.core.behaviors import BehaviorContext, run_behaviors
from visionai.core import pose_phone
from visionai.core.object_storage import get_object_storage
from visionai.core.redis_manager import redis_manager
from visionai.utils.alert_email import notify_alert_by_email

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
        collect_person = (
            alarm_person or call_on or gather_on or smoke_on or phone_play_on
        )
        collect_phone = alarm_phone or call_on or phone_play_on
        behavior_src = frame.copy() if smoke_on else None

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

        if (call_on or phone_play_on) and persons and cell_phones:
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
        if behavior_src is not None and smoke_on:
            ctx = BehaviorContext(
                frame_source=behavior_src,
                persons=persons,
                cell_phones=cell_phones,
                stream_name=self.stream_name,
                now=now,
            )
            behaviors_out = run_behaviors(ctx, self._behavior_state, self.detections)

        smoke_result = behaviors_out.get(SMOKE_KEY, {})
        smoking_alert = bool(smoke_result.get("alert"))
        smoking_indices = set(smoke_result.get("person_indices", []))

        gather_cluster_set = set(gather_cluster_indices)

        for i, person in enumerate(persons):
            if not (
                alarm_person
                or (call_on and i in persons_in_call)
                or (phone_play_on and i in persons_in_play)
                or (gather_on and gathering_alert and i in gather_cluster_set)
                or (smoke_on and smoking_alert and i in smoking_indices)
            ):
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

        if smoking_alert and smoke_on and smoking_indices:
            color_smoke = (60, 180, 255)
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
            info.append(f"打电话: {len(detections['calls'])}")
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

        if self.detections.get(SMOKE_KEY, False) and detections.get("behaviors", {}).get(
            SMOKE_KEY, {}
        ).get("alert"):
            should_save = True
            n_s = len(
                detections.get("behaviors", {}).get(SMOKE_KEY, {}).get("person_indices")
                or []
            )
            info.append(f"吸烟: {n_s}")
            detection_types.append("吸烟")

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
            return True
        except Exception as e:
            logger.error(f"[{self.stream_name}] 保存截图失败: {e}")
            return False
