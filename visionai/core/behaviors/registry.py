"""
行为插件注册表。

主检 YOLO 之后由 ``run_behaviors`` 按流上开启的扩展键调度插件
（人脸识别、训练实验室专模等）。
"""

from __future__ import annotations

from typing import Any, Dict, List, MutableMapping

from visionai.config.detection_catalog import (
    EXTENSION_KEYS,
    FACE_RECOG_KEY,
    PLATE_RECOG_KEY,
)
from visionai.config.specialists import specs_from_specialists
from visionai.core.behaviors.context import BehaviorContext
from visionai.core.behaviors.extensions import build_extension_plugins
from visionai.core.behaviors.face_recognition import FaceRecognitionBehaviorPlugin
from visionai.core.behaviors.plate_recognition import PlateRecognitionBehaviorPlugin

# 内置 make_call / 打电话专模已下线；需要时用训练实验室「自定义」部署专模
_BUILTIN_SPECS: List[Any] = []

PLUGINS: List[Any] = []


def reload_plugins() -> List[Any]:
    """重建插件列表（部署/删除专模后调用）。"""
    global PLUGINS
    specs = list(_BUILTIN_SPECS) + specs_from_specialists()
    PLUGINS = [
        FaceRecognitionBehaviorPlugin(),
        PlateRecognitionBehaviorPlugin(),
    ] + build_extension_plugins(specs)
    return PLUGINS


reload_plugins()


def behavior_keys() -> frozenset:
    return frozenset(
        {FACE_RECOG_KEY, PLATE_RECOG_KEY, *EXTENSION_KEYS, *(p.key for p in PLUGINS)}
    )


def run_behaviors(
    ctx: BehaviorContext,
    state: MutableMapping[str, Any],
    detection_flags: Dict[str, bool],
) -> Dict[str, Any]:
    """仅运行 detection_flags 中为 True 的插件；各插件状态在 state[plugin.key]。"""
    out: Dict[str, Any] = {}
    plate_recog_on = bool(detection_flags.get(PLATE_RECOG_KEY, False))
    for plugin in PLUGINS:
        key = plugin.key
        if not detection_flags.get(key, False):
            continue
        # 开启车牌识别（OCR+库）时跳过仅颜色专模 plate，避免重复告警
        if plate_recog_on and key == "plate":
            continue
        sub = state.setdefault(key, {})
        out[key] = plugin.evaluate(ctx, sub)
    return out
