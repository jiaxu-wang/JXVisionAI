#!/usr/bin/env python3
"""Print Ultralytics class names for local YOLO26 weights (debug helper)."""

from ultralytics import YOLO


def _dump(path: str) -> None:
    print(f"=== 检查 {path} ===")
    model = YOLO(path)
    names = model.names
    print(f"类别数量: {len(names)}")
    for i, class_name in names.items():
        print(f"  {i}: {class_name}")
    print()


if __name__ == "__main__":
    _dump("yolo26n.pt")
    _dump("yolo26s.pt")
