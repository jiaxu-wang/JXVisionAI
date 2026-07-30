"""Types aligned with visionai.infer.v1 Detection / Status."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional, Sequence, Tuple


@dataclass
class DetectionBox:
    x1: float
    y1: float
    x2: float
    y2: float
    class_id: int
    conf: float
    label: str = ""
    model_name: str = "primary"

    @property
    def box(self) -> Tuple[int, int, int, int]:
        return int(self.x1), int(self.y1), int(self.x2), int(self.y2)


@dataclass
class InferResult:
    ok: bool
    boxes: List[DetectionBox] = field(default_factory=list)
    infer_ms: int = 0
    error_code: str = "OK"
    message: str = ""
    frame_id: int = 0


def boxes_from_ultralytics(results) -> List[DetectionBox]:
    """Convert Ultralytics Results to DetectionBox list."""
    out: List[DetectionBox] = []
    if not results:
        return out
    for result in results:
        if getattr(result, "boxes", None) is None:
            continue
        for box in result.boxes:
            x1, y1, x2, y2 = map(float, box.xyxy[0])
            out.append(
                DetectionBox(
                    x1=x1,
                    y1=y1,
                    x2=x2,
                    y2=y2,
                    class_id=int(box.cls),
                    conf=float(box.conf),
                )
            )
    return out


def filter_class_ids(enabled_detections: dict) -> Sequence[int]:
    """Optional class filter from stream detections flags (COCO numeric keys)."""
    ids = []
    for k, on in (enabled_detections or {}).items():
        if not on:
            continue
        if isinstance(k, int) or (isinstance(k, str) and k.isdigit()):
            ids.append(int(k))
    return ids
