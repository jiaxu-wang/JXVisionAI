"""注册并调度行为插件。"""

from __future__ import annotations

from typing import Any, Dict, List, MutableMapping

from visionai.core.behaviors.context import BehaviorContext
from visionai.core.behaviors.smoking import SmokingBehaviorPlugin

PLUGINS: List[Any] = [SmokingBehaviorPlugin()]


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
