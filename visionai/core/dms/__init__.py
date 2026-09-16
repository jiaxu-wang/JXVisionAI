"""驾驶监测（DMS）：准入、密检窗、疲劳指标。"""

from visionai.core.dms.config import (
    FATIGUE_KEY,
    default_fatigue_config,
    normalize_fatigue_config,
    resolve_window,
    traffic_hint,
)
from visionai.core.dms.gate import get_dms_status, set_dms_status

__all__ = [
    "FATIGUE_KEY",
    "default_fatigue_config",
    "normalize_fatigue_config",
    "resolve_window",
    "traffic_hint",
    "get_dms_status",
    "set_dms_status",
]
