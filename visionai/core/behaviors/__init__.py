"""可插拔行为层：在固定 COCO YOLO 之上叠加规则 / 轻量分类 / ROI 检测。"""

from visionai.core.behaviors.context import BehaviorContext
from visionai.core.behaviors.registry import PLUGINS, run_behaviors

__all__ = ["BehaviorContext", "PLUGINS", "run_behaviors"]
