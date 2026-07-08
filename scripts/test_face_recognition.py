#!/usr/bin/env python3
"""人脸识别冒烟测试：模型加载、录入、比对。"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

import cv2
import numpy as np

from visionai.core import face_engine, face_library


def main() -> int:
    parser = argparse.ArgumentParser(description="VisionAI 人脸识别测试")
    parser.add_argument("--image", required=True, help="测试图片路径")
    parser.add_argument("--name", default="测试人员", help="录入姓名（--enroll 时）")
    parser.add_argument("--enroll", action="store_true", help="录入到人脸库")
    parser.add_argument("--list", action="store_true", help="列出人脸库")
    args = parser.parse_args()

    if not face_engine.is_available():
        print("ERROR: 人脸模型未就绪，请检查 models/buffalo_l/")
        return 1

    if args.list:
        for p in face_library.list_persons():
            print(p)
        return 0

    img = cv2.imread(args.image)
    if img is None:
        print(f"ERROR: 无法读取图片 {args.image}")
        return 1

    if args.enroll:
        try:
            r = face_library.enroll_person(img, name=args.name)
            print("录入成功:", r)
        except Exception as ex:  # noqa: BLE001
            print("录入失败:", ex)
            return 1
        return 0

    faces = face_engine.analyze_faces(img)
    print(f"检测到 {len(faces)} 张脸")
    for i, f in enumerate(faces):
        pid, sim = face_library.match_embedding(
            f["embedding"], threshold=0.45, watchlist=None
        )
        name = face_library.person_name(pid) if pid else "陌生人"
        print(f"  [{i}] bbox={f['bbox']} score={f['det_score']:.3f} -> {name} sim={sim:.3f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
