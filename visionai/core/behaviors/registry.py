"""
行为插件注册表。

主检 YOLO 之后由 ``run_behaviors`` 按流上开启的扩展键调度插件
（打电话专模、人脸识别、训练实验室专模等）。
"""

from __future__ import annotations

from typing import Any, Dict, List, MutableMapping

from visionai.config.settings import (
    DEDICATED_MAX_PERSONS_PER_FRAME,
    MAKE_CALL_MIN_DURATION_SEC,
    MAKE_CALL_MODEL_CONF,
    MAKE_CALL_MODEL_PATH,
    MAKE_CALL_REQUIRE_PERSON_OVERLAP,
    MAKE_CALL_SCORE_THRESHOLD,
)
from visionai.config.detection_catalog import (
    CALL_KEY,
    EXTENSION_KEYS,
    FACE_RECOG_KEY,
)
from visionai.config.specialists import specs_from_specialists
from visionai.core.behaviors.context import BehaviorContext
from visionai.core.behaviors.extensions import (
    PersonEventSpec,
    build_extension_plugins,
)
from visionai.core.behaviors.face_recognition import FaceRecognitionBehaviorPlugin

_BUILTIN_SPECS = [
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
        log_label="打电话 make_call",
    ),
]

PLUGINS: List[Any] = []


def reload_plugins() -> List[Any]:
    """重建插件列表（部署/删除专模后调用）。"""
    global PLUGINS
    specs = list(_BUILTIN_SPECS) + specs_from_specialists()
    PLUGINS = [FaceRecognitionBehaviorPlugin()] + build_extension_plugins(specs)
    return PLUGINS


reload_plugins()


def behavior_keys() -> frozenset:
    return frozenset({FACE_RECOG_KEY, *EXTENSION_KEYS, *(p.key for p in PLUGINS)})


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
        # make_call 专模由 detector 在 MAKE_CALL_USE_DEDICATED 时调度；
        # 若未开专模，跳过 CALL 插件以免重复。
        if key == CALL_KEY:
            from visionai.config.settings import MAKE_CALL_USE_DEDICATED

            if not MAKE_CALL_USE_DEDICATED:
                continue
        sub = state.setdefault(key, {})
        out[key] = plugin.evaluate(ctx, sub)
    return out
