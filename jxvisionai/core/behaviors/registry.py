"""
行为插件注册表。

主检 YOLO 之后由 ``run_behaviors`` 按流上开启的扩展键调度插件
（吸烟、打电话专模、人脸识别等）。插件实现见同目录各模块。
"""

from __future__ import annotations

from typing import Any, Dict, List, MutableMapping

from jxvisionai.config.settings import (
    DEDICATED_MAX_PERSONS_PER_FRAME,
    FACE_MIN_DURATION_SEC,
    FACE_MODEL_CONF,
    FACE_MODEL_PATH,
    FALL_MIN_DURATION_SEC,
    FALL_MODEL_CONF,
    FALL_MODEL_PATH,
    FALL_SCORE_THRESHOLD,
    FLAME_MIN_DURATION_SEC,
    FLAME_MODEL_CONF,
    FLAME_MODEL_PATH,
    LICENSE_PLATE_MIN_DURATION_SEC,
    LICENSE_PLATE_MODEL_CONF,
    LICENSE_PLATE_MODEL_PATH,
    MAKE_CALL_MIN_DURATION_SEC,
    MAKE_CALL_MODEL_CONF,
    MAKE_CALL_MODEL_PATH,
    MAKE_CALL_REQUIRE_PERSON_OVERLAP,
    MAKE_CALL_SCORE_THRESHOLD,
    MASK_MIN_DURATION_SEC,
    MASK_MODEL_CONF,
    MASK_MODEL_PATH,
    MASK_SCORE_THRESHOLD,
    REFLECTIVE_VEST_MIN_DURATION_SEC,
    REFLECTIVE_VEST_MODEL_CONF,
    REFLECTIVE_VEST_MODEL_PATH,
    REFLECTIVE_VEST_SCORE_THRESHOLD,
    ROAD_WATERLOGGING_MIN_DURATION_SEC,
    ROAD_WATERLOGGING_MODEL_CONF,
    ROAD_WATERLOGGING_MODEL_PATH,
    SAFETY_HELMET_MIN_DURATION_SEC,
    SAFETY_HELMET_MODEL_CONF,
    SAFETY_HELMET_MODEL_PATH,
    SAFETY_HELMET_SCORE_THRESHOLD,
    GLASSES_MIN_DURATION_SEC,
    GLASSES_MODEL_CONF,
    GLASSES_MODEL_PATH,
    GLASSES_SCORE_THRESHOLD,
    SLEEPING_MIN_DURATION_SEC,
    SLEEPING_MODEL_CONF,
    SLEEPING_MODEL_PATH,
    SLEEPING_SCORE_THRESHOLD,
)
from jxvisionai.config.detection_catalog import (
    CALL_KEY,
    EXTENSION_KEYS,
    FACE_KEY,
    SMOKE_KEY,
    FALL_KEY,
    FLAME_KEY,
    LICENSE_PLATE_KEY,
    MASK_KEY,
    NO_GLASSES_KEY,
    REFLECTIVE_VEST_KEY,
    ROAD_WATERLOGGING_KEY,
    SAFETY_HELMET_KEY,
    SLEEPING_KEY,
)
from jxvisionai.core.behaviors.context import BehaviorContext
from jxvisionai.core.behaviors.extensions import (
    PersonEventSpec,
    SceneSpec,
    ViolationSpec,
    build_extension_plugins,
)
from jxvisionai.core.behaviors.face_recognition import FaceRecognitionBehaviorPlugin
from jxvisionai.core.behaviors.smoking import SmokingBehaviorPlugin

_EXTENSION_SPECS = [
    SceneSpec(
        key=FACE_KEY,
        model_path=FACE_MODEL_PATH,
        conf=FACE_MODEL_CONF,
        min_duration_sec=FACE_MIN_DURATION_SEC,
    ),
    PersonEventSpec(
        key=FALL_KEY,
        model_path=FALL_MODEL_PATH,
        conf=FALL_MODEL_CONF,
        score_threshold=FALL_SCORE_THRESHOLD,
        min_duration_sec=FALL_MIN_DURATION_SEC,
        positive_class_ids=(1,),
        max_persons=DEDICATED_MAX_PERSONS_PER_FRAME,
    ),
    SceneSpec(
        key=FLAME_KEY,
        model_path=FLAME_MODEL_PATH,
        conf=FLAME_MODEL_CONF,
        min_duration_sec=FLAME_MIN_DURATION_SEC,
        class_ids=(0, 1),
    ),
    SceneSpec(
        key=LICENSE_PLATE_KEY,
        model_path=LICENSE_PLATE_MODEL_PATH,
        conf=LICENSE_PLATE_MODEL_CONF,
        min_duration_sec=LICENSE_PLATE_MIN_DURATION_SEC,
        class_ids=(0, 1, 2),
    ),
    PersonEventSpec(
        key=CALL_KEY,
        model_path=MAKE_CALL_MODEL_PATH,
        conf=MAKE_CALL_MODEL_CONF,
        score_threshold=MAKE_CALL_SCORE_THRESHOLD,
        min_duration_sec=MAKE_CALL_MIN_DURATION_SEC,
        positive_class_ids=(0,),
        max_persons=DEDICATED_MAX_PERSONS_PER_FRAME,
        needs_persons=MAKE_CALL_REQUIRE_PERSON_OVERLAP,
        log_scores=True,
        log_label="打电话 make_call.onnx",
    ),
    ViolationSpec(
        key=MASK_KEY,
        model_path=MASK_MODEL_PATH,
        conf=MASK_MODEL_CONF,
        score_threshold=MASK_SCORE_THRESHOLD,
        min_duration_sec=MASK_MIN_DURATION_SEC,
        subject_class_ids=(0,),
        comply_class_ids=(1,),
        max_persons=DEDICATED_MAX_PERSONS_PER_FRAME,
    ),
    ViolationSpec(
        key=REFLECTIVE_VEST_KEY,
        model_path=REFLECTIVE_VEST_MODEL_PATH,
        conf=REFLECTIVE_VEST_MODEL_CONF,
        score_threshold=REFLECTIVE_VEST_SCORE_THRESHOLD,
        min_duration_sec=REFLECTIVE_VEST_MIN_DURATION_SEC,
        subject_class_ids=(1,),
        comply_class_ids=(0,),
        max_persons=DEDICATED_MAX_PERSONS_PER_FRAME,
    ),
    SceneSpec(
        key=ROAD_WATERLOGGING_KEY,
        model_path=ROAD_WATERLOGGING_MODEL_PATH,
        conf=ROAD_WATERLOGGING_MODEL_CONF,
        min_duration_sec=ROAD_WATERLOGGING_MIN_DURATION_SEC,
        class_ids=(0,),
    ),
    ViolationSpec(
        key=SAFETY_HELMET_KEY,
        model_path=SAFETY_HELMET_MODEL_PATH,
        conf=SAFETY_HELMET_MODEL_CONF,
        score_threshold=SAFETY_HELMET_SCORE_THRESHOLD,
        min_duration_sec=SAFETY_HELMET_MIN_DURATION_SEC,
        subject_class_ids=(0,),
        comply_class_ids=(1,),
        max_persons=DEDICATED_MAX_PERSONS_PER_FRAME,
    ),
    ViolationSpec(
        key=NO_GLASSES_KEY,
        model_path=GLASSES_MODEL_PATH,
        conf=GLASSES_MODEL_CONF,
        score_threshold=GLASSES_SCORE_THRESHOLD,
        min_duration_sec=GLASSES_MIN_DURATION_SEC,
        # 与训练模板一致：0=no_glasses（违规），1=glasses（合规）
        subject_class_ids=(0,),
        comply_class_ids=(1,),
        max_persons=DEDICATED_MAX_PERSONS_PER_FRAME,
    ),
    PersonEventSpec(
        key=SLEEPING_KEY,
        model_path=SLEEPING_MODEL_PATH,
        conf=SLEEPING_MODEL_CONF,
        score_threshold=SLEEPING_SCORE_THRESHOLD,
        min_duration_sec=SLEEPING_MIN_DURATION_SEC,
        positive_class_ids=(0,),
        max_persons=DEDICATED_MAX_PERSONS_PER_FRAME,
        log_scores=True,
        log_label="睡觉 sleeping.pt",
    ),
]

PLUGINS: List[Any] = (
    [SmokingBehaviorPlugin(), FaceRecognitionBehaviorPlugin()]
    + build_extension_plugins(_EXTENSION_SPECS)
)

from jxvisionai.config.detection_catalog import FACE_RECOG_KEY

_BEHAVIOR_KEYS = frozenset({SMOKE_KEY, FACE_RECOG_KEY, *EXTENSION_KEYS})


def behavior_keys() -> frozenset:
    return _BEHAVIOR_KEYS


def run_behaviors(
    ctx: BehaviorContext,
    state: MutableMapping[str, Any],
    detection_flags: Dict[str, bool],
) -> Dict[str, Any]:
    """仅运行 detection_flags 中为 True 的插件；各插件状态在 state[plugin.key]。"""
    out: Dict[str, Any] = {}
    for plugin in PLUGINS:
        key = plugin.key
        if not detection_flags.get(key, False):
            continue
        sub = state.setdefault(key, {})
        out[key] = plugin.evaluate(ctx, sub)
    return out
