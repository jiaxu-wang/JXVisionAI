"""专模扩展检测：场景目标、人物关联事件、合规类（未戴帽/未穿反光衣/未戴口罩）。"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union

from visionai.core.behaviors.common import (
    apply_duration_alert,
    apply_keyed_duration_alert,
    apply_scene_duration_alert,
    empty_person_result,
    empty_scene_result,
    overlap_boxes_for_persons,
    top_persons,
)
from visionai.core.behaviors.context import BehaviorContext
from visionai.core import dedicated_yolo as dyolo

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SceneSpec:
    key: str
    model_path: str
    conf: float
    min_duration_sec: float
    class_ids: Optional[Tuple[int, ...]] = None


@dataclass(frozen=True)
class PersonEventSpec:
    key: str
    model_path: str
    conf: float
    score_threshold: float
    min_duration_sec: float
    positive_class_ids: Tuple[int, ...]
    max_persons: int
    needs_persons: bool = True
    log_scores: bool = False
    log_label: str = ""


@dataclass(frozen=True)
class ViolationSpec:
    key: str
    model_path: str
    conf: float
    score_threshold: float
    min_duration_sec: float
    subject_class_ids: Tuple[int, ...]
    comply_class_ids: Tuple[int, ...]
    max_persons: int


class SceneDetectorPlugin:
    def __init__(self, spec: SceneSpec):
        self.key = spec.key
        self._spec = spec

    def evaluate(self, ctx: BehaviorContext, state: Dict[str, Any]) -> Dict[str, Any]:
        out = empty_scene_result()
        path = (self._spec.model_path or "").strip()
        if not path:
            return out
        dets = dyolo.infer_detections(
            path,
            ctx.frame_source,
            conf=self._spec.conf,
            class_ids=self._spec.class_ids,
        )
        out["boxes"] = [
            {
                "box": d["box"],
                "confidence": d["confidence"],
                "name": d.get("name", ""),
                "class_id": d.get("class_id"),
            }
            for d in dets
        ]
        out["count"] = len(dets)
        active = len(dets) > 0
        out["alert"] = apply_scene_duration_alert(
            active,
            state,
            ctx.now,
            min_duration_sec=self._spec.min_duration_sec,
        )
        return out


class PersonOverlapPlugin:
    def __init__(self, spec: PersonEventSpec):
        self.key = spec.key
        self._spec = spec

    def evaluate(self, ctx: BehaviorContext, state: Dict[str, Any]) -> Dict[str, Any]:
        out = empty_person_result()
        path = (self._spec.model_path or "").strip()
        if not path:
            return out
        if self._spec.needs_persons and not ctx.persons:
            return out

        event_boxes = dyolo.infer_detections(
            path,
            ctx.frame_source,
            conf=self._spec.conf,
            class_ids=self._spec.positive_class_ids,
        )
        indexed = top_persons(ctx.persons, self._spec.max_persons)
        scores: Dict[str, float] = {}
        if self._spec.needs_persons:
            for pi, person in indexed:
                pb = tuple(int(x) for x in person["box"][:4])
                sc = dyolo.best_overlap_conf(
                    pb,
                    event_boxes,
                    class_ids=self._spec.positive_class_ids,
                )
                if sc > 0:
                    scores[str(pi)] = round(sc, 4)
        else:
            for i, d in enumerate(event_boxes):
                scores[str(i)] = round(float(d.get("confidence", 0.0)), 4)

        alerting_keys: List[str] = []
        alerting: List[int] = []
        if self._spec.needs_persons:
            alerting, alert = apply_duration_alert(
                indexed,
                scores,
                state,
                ctx.now,
                score_threshold=self._spec.score_threshold,
                min_duration_sec=self._spec.min_duration_sec,
            )
            out["person_indices"] = alerting
            out["standalone"] = False
            if alert:
                out["event_boxes"] = overlap_boxes_for_persons(
                    indexed,
                    alerting,
                    event_boxes,
                    class_ids=self._spec.positive_class_ids,
                )
        else:
            alerting_keys, alert = apply_keyed_duration_alert(
                scores,
                state,
                ctx.now,
                score_threshold=self._spec.score_threshold,
                min_duration_sec=self._spec.min_duration_sec,
            )
            out["person_indices"] = []
            out["standalone"] = True
            out["alert_keys"] = alerting_keys
            if alert:
                want = set(alerting_keys)
                out["event_boxes"] = [
                    {
                        "box": d["box"],
                        "confidence": d["confidence"],
                        "name": d.get("name", ""),
                        "class_id": d.get("class_id"),
                    }
                    for i, d in enumerate(event_boxes)
                    if str(i) in want
                ]

        out["scores"] = scores
        out["alert"] = alert

        if self._spec.log_scores and scores:
            tag = self._spec.log_label or self.key
            parts = [
                f"{'evt' if not self._spec.needs_persons else 'pid'}{k}={scores[k]:.4f}"
                for k in sorted(scores.keys(), key=lambda x: int(x))
            ]
            hits: Any = alerting_keys if not self._spec.needs_persons else alerting
            logger.info(
                "[%s] %s thr=%.3f dur>=%.2fs | %s | alert=%s hits=%s | n_evt=%d",
                ctx.stream_name,
                tag,
                self._spec.score_threshold,
                self._spec.min_duration_sec,
                ", ".join(parts),
                alert,
                hits,
                len(event_boxes),
            )
        return out


class ViolationDetectorPlugin:
    """subject 检出且与人物关联，但同区域内无 comply 类 → 违规。"""

    def __init__(self, spec: ViolationSpec):
        self.key = spec.key
        self._spec = spec

    def evaluate(self, ctx: BehaviorContext, state: Dict[str, Any]) -> Dict[str, Any]:
        out = empty_person_result()
        path = (self._spec.model_path or "").strip()
        if not path or not ctx.persons:
            return out

        all_boxes = dyolo.infer_detections(path, ctx.frame_source, conf=self._spec.conf)
        subjects = dyolo.filter_class(all_boxes, self._spec.subject_class_ids)
        complies = dyolo.filter_class(all_boxes, self._spec.comply_class_ids)
        indexed = top_persons(ctx.persons, self._spec.max_persons)

        scores: Dict[str, float] = {}
        for pi, person in indexed:
            pb = tuple(int(x) for x in person["box"][:4])
            best = 0.0
            for subj in subjects:
                sb = subj.get("box")
                if not sb or len(sb) < 4:
                    continue
                sb_t = tuple(int(x) for x in sb[:4])
                if not dyolo.boxes_associated(pb, sb_t):
                    continue
                ok = False
                for comp in complies:
                    cb = comp.get("box")
                    if not cb or len(cb) < 4:
                        continue
                    if dyolo.boxes_associated(sb_t, tuple(int(x) for x in cb[:4])):
                        ok = True
                        break
                if not ok:
                    best = max(best, float(subj.get("confidence", 0.0)))
            if best > 0:
                scores[str(pi)] = round(best, 4)

        alerting, alert = apply_duration_alert(
            indexed,
            scores,
            state,
            ctx.now,
            score_threshold=self._spec.score_threshold,
            min_duration_sec=self._spec.min_duration_sec,
        )
        out["scores"] = scores
        out["person_indices"] = alerting
        out["alert"] = alert
        if alert:
            out["event_boxes"] = overlap_boxes_for_persons(
                indexed,
                alerting,
                subjects,
                class_ids=self._spec.subject_class_ids,
            )
        return out


def build_extension_plugins(specs: Sequence[Any]) -> List[Any]:
    plugins: List[Any] = []
    for spec in specs:
        if isinstance(spec, SceneSpec):
            plugins.append(SceneDetectorPlugin(spec))
        elif isinstance(spec, PersonEventSpec):
            plugins.append(PersonOverlapPlugin(spec))
        elif isinstance(spec, ViolationSpec):
            plugins.append(ViolationDetectorPlugin(spec))
    return plugins
