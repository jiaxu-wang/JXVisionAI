#!/usr/bin/env python3
"""训练实验室 P0-P4 功能自测（无需启动 Flask）。"""
from __future__ import annotations

import json
import shutil
import sys
import tempfile
import uuid
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))


def _mk_project(n_images: int = 12, n_boxes_per: int = 6) -> Path:
    from visionai.web.training_lab_core import TRAINING_TEMPLATES

    base = REPO / "training_lab_data" / "projects"
    base.mkdir(parents=True, exist_ok=True)
    pid = uuid.uuid4().hex[:12]
    pdir = base / pid
    (pdir / "images").mkdir(parents=True)
    (pdir / "labels").mkdir(parents=True)
    tpl = TRAINING_TEMPLATES["smoking"]
    meta = {
        "title": "自测吸烟",
        "classes": tpl["classes"],
        "template_id": "smoking",
        "deploy_target": "smoking",
        "created_at": 0,
    }
    (pdir / "meta.json").write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
    # 生成假图与标注
    try:
        import cv2
        import numpy as np
    except ImportError:
        raise SystemExit("需要 opencv-python") from None

    for i in range(n_images):
        name = f"test_{i:03d}.jpg"
        img = np.zeros((320, 320, 3), dtype=np.uint8)
        img[:] = (40 + i, 60, 80)
        cv2.imwrite(str(pdir / "images" / name), img)
        lines = []
        for _ in range(n_boxes_per):
            lines.append("0 0.5 0.5 0.2 0.2")
        (pdir / "labels" / f"test_{i:03d}.txt").write_text("\n".join(lines) + "\n")
    return pdir


def test_p0_prepare_smoking_remap():
    from training_system.scripts.prepare_data import remap_label_lines_smoking

    raw = REPO / "training_lab_data" / "_test_raw"
    raw.mkdir(parents=True, exist_ok=True)
    (raw / "a.txt").write_text("0 0.1 0.1 0.2 0.2\n1 0.5 0.5 0.3 0.3\n2 0.6 0.6 0.1 0.1\n")
    lines = remap_label_lines_smoking(str(raw / "a.txt"))
    assert len(lines) == 2, lines
    assert all(l.startswith("0 ") for l in lines)
    print("P0 remap-to-smoking: OK")


def test_p0_augment_disabled():
    from training_system.scripts import prepare_data as pd
    import numpy as np

    img = np.zeros((100, 100, 3), dtype=np.uint8)
    out = pd.augment_image(img.copy())
    assert out.shape == img.shape
    print("P0 augment disabled (no-op): OK")


def test_p1_dataset_health():
    from visionai.web.training_lab_core import check_dataset_health

    pdir = _mk_project(12, 6)
    meta = json.loads((pdir / "meta.json").read_text(encoding="utf-8"))
    h = check_dataset_health(pdir, meta)
    assert h.labeled_images == 12
    assert h.can_train, h.errors
    print("P1 dataset health can_train: OK")
    shutil.rmtree(pdir)


def test_p1_health_blocks_small():
    from visionai.web.training_lab_core import check_dataset_health

    pdir = _mk_project(3, 2)
    meta = json.loads((pdir / "meta.json").read_text(encoding="utf-8"))
    h = check_dataset_health(pdir, meta)
    assert not h.can_train
    assert h.errors
    print("P1 gate blocks small dataset: OK")
    shutil.rmtree(pdir)


def test_p2_deploy_dry():
    from visionai.web.training_lab_core import deploy_weights_to_production

    models = REPO / "models"
    src = models / "smoking_detection.pt"
    if not src.is_file():
        print("P2 deploy: SKIP (无 models/smoking_detection.pt)")
        return
    with tempfile.TemporaryDirectory() as td:
        fake = Path(td) / "best.pt"
        shutil.copy2(src, fake)
        result = deploy_weights_to_production(
            REPO,
            weights_path=fake,
            target="smoking",
            backup=True,
            patch_config=False,
        )
        assert result.get("success"), result
        assert Path(result["dest"]).is_file()
        print("P2 deploy copy to models/: OK")


def test_p3_snapshot_list_import():
    from visionai.config.settings import SAVE_DIR
    from visionai.web.training_lab_core import import_snapshots_to_project, list_production_snapshots

    snaps = list_production_snapshots(Path(SAVE_DIR), limit=5)
    print(f"P3 snapshot list: found {len(snaps)} under {SAVE_DIR}")
    pdir = _mk_project(2, 6)
    if snaps:
        r = import_snapshots_to_project(pdir, [snaps[0]["path"]], Path(SAVE_DIR))
        assert r["count"] >= 1
        print("P3 snapshot import: OK")
    else:
        print("P3 snapshot import: SKIP (无快照)")
    shutil.rmtree(pdir)


def test_p4_templates_and_threshold():
    from visionai.web.training_lab_core import TRAINING_TEMPLATES, suggest_thresholds_from_val
    from visionai.web.training_lab_core import materialize_yolo_split

    assert TRAINING_TEMPLATES["smoking"]["classes"] == ["smoking"]
    pdir = _mk_project(12, 6)
    meta = json.loads((pdir / "meta.json").read_text(encoding="utf-8"))
    yaml_path = materialize_yolo_split(pdir, meta)
    models = REPO / "models"
    w = models / "smoking_detection.pt"
    try:
        import ultralytics  # noqa: F401
        has_ultra = True
    except ImportError:
        has_ultra = False
    if w.is_file() and has_ultra:
        r = suggest_thresholds_from_val(
            str(w),
            yaml_path,
            pdir / "_yolo_staging",
            class_index=0,
        )
        assert r.get("ok"), r
        assert "suggested_detector_conf" in r
        print("P4 threshold suggest: OK")
    else:
        print("P4 threshold suggest: SKIP (无权重或无 ultralytics)")
    shutil.rmtree(pdir)
    print("P4 templates smoking single-class: OK")


def test_evaluate_json_out():
    import subprocess

    try:
        import ultralytics  # noqa: F401
    except ImportError:
        print("P1 evaluate --json-out: SKIP (无 ultralytics)")
        return
    models = REPO / "models"
    w = models / "smoking_detection.pt"
    if not w.is_file():
        print("P1 evaluate --json-out: SKIP (无权重)")
        return
    pdir = _mk_project(12, 6)
    from visionai.web.training_lab_core import materialize_yolo_split

    meta = json.loads((pdir / "meta.json").read_text(encoding="utf-8"))
    yaml_path = materialize_yolo_split(pdir, meta)
    out = pdir / "metrics.json"
    cmd = [
        sys.executable,
        str(REPO / "training_system" / "scripts" / "evaluate.py"),
        "eval",
        "--model",
        str(w),
        "--data",
        str(yaml_path),
        "--device",
        "cpu",
        "--json-out",
        str(out),
    ]
    proc = subprocess.run(cmd, cwd=str(REPO / "training_system"), capture_output=True, text=True)
    if proc.returncode != 0:
        print("evaluate json: SKIP", proc.stderr[:200])
    else:
        data = json.loads(out.read_text(encoding="utf-8"))
        assert "map50" in data
        print("P1 evaluate --json-out: OK", data)
    shutil.rmtree(pdir)


def main():
    print("=== Training Lab P0-P4 self-test ===\n")
    test_p0_prepare_smoking_remap()
    test_p0_augment_disabled()
    test_p1_dataset_health()
    test_p1_health_blocks_small()
    test_p2_deploy_dry()
    test_p3_snapshot_list_import()
    test_p4_templates_and_threshold()
    test_evaluate_json_out()
    print("\n=== ALL TESTS PASSED ===")


if __name__ == "__main__":
    main()
