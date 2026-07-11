"""行为插件约定：新增行为时实现本模块中的协议并注册到 registry。"""

from __future__ import annotations

from typing import Any, Dict, Protocol, runtime_checkable

from visionai.core.behaviors.context import BehaviorContext


@runtime_checkable
class BehaviorPlugin(Protocol):
    """与 detection_catalog 中的布尔开关 key 一一对应。"""

    key: str

    def evaluate(self, ctx: BehaviorContext, state: Dict[str, Any]) -> Dict[str, Any]:
        """读取 ctx，读写 state（仅本插件使用的命名空间），返回可 JSON 化的结果 dict。"""
