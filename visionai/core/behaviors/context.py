"""行为插件共享上下文（可随新行为扩展字段）。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List

import numpy as np


@dataclass
class BehaviorContext:
    """单帧输入；plugins 只读不写 frame_source。"""

    frame_source: np.ndarray
    persons: List[Dict[str, Any]]
    cell_phones: List[Dict[str, Any]]
    stream_name: str
    now: float
    extra: Dict[str, Any] = field(default_factory=dict)
