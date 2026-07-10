#!/usr/bin/env python3
"""训练实验室行业级自测（无需启动 Flask）。"""
from __future__ import annotations

import json
import shutil
import sys
import tempfile
import uuid
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))


def _mk_project(
    n_images: int = 60,
    n_boxes_per: int = 2,
    template_id: str = "smoking",
) -> Path:
    from jxvisionai.web.training_lab_core import TRAINING_TEMPLATES

    base = REPO / "training_lab_data" / "projects"
    base.mkdir(parents=True, exist_ok=True)
    pid = uuid.uuid4().hex[:12]
    pdir = base / pid
    (pdir / "images").mkdir(parents=True)
    (pdir / "labels").mkdir(parents=True)
    (pdir / "labels_draft").mkdir(parents=True)
    tpl = TRAINING_TEMPLATES[template_id]
    meta = {
        "title": "自测",
        "classes": list(tpl["classes"]),
        "template_id": template_id,
        "deploy_target": tpl.get("deploy_target"),
        "created_at": 0,
    }
    (pdir / "meta.json").write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
    try:
        import cv2
        import numpy as np
    except ImportError:
        raise SystemExit("需要 opencv-python") from None

    n_cls = max(1, len(meta["classes"]))
    for i in range(n_images):
        name = f"test_{i:03d}.jpg"
        img = np.zeros((320, 320, 3), dtype=np.uint8)
        img[:] = (40 + (i % 50), 60, 80)
        cv2.imwrite(str(pdir / "images" / name), img)
        lines = []
        for bi in range(n_boxes_per):
            ci = bi % n_cls
            lines.append(f"{ci} 0.5 0.5 0.2 0.2")
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


def test_helmet_class_contract():
    from jxvisionai.web.training_lab_core import TRAINING_TEMPLATES, DEPLOY_TARGETS

    assert TRAINING_TEMPLATES["safety_helmet"]["classes"] == ["no_helmet", "helmet"]
    assert TRAINING_TEMPLATES["no_glasses"]["classes"] == ["no_glasses", "glasses"]
    assert TRAINING_TEMPLATES["no_glasses"]["deploy_target"] == "no_glasses"
    assert DEPLOY_TARGETS["no_glasses"]["model_filename"] == "glasses_detection.pt"
    assert DEPLOY_TARGETS["no_glasses"]["required_classes"] == ["no_glasses", "glasses"]
    assert TRAINING_TEMPLATES["smoking"]["default_pretrained"] == "yolov8s.pt"
    print("helmet/glasses class order + yolov8s default: OK")


def test_no_glasses_catalog():
    from jxvisionai.config.detection_catalog import (
        EXTENSION_KEYS,
        EXTENSION_LABELS_ZH,
        NO_GLASSES_KEY,
        PERSON_BEHAVIOR_KEYS,
    )
    from jxvisionai.config.settings import GLASSES_MODEL_PATH

    assert NO_GLASSES_KEY in EXTENSION_KEYS
    assert NO_GLASSES_KEY in PERSON_BEHAVIOR_KEYS
    assert EXTENSION_LABELS_ZH[NO_GLASSES_KEY] == "未戴眼镜"
    assert "glasses_detection.pt" in GLASSES_MODEL_PATH.replace("\\", "/")
    print("no_glasses catalog + settings: OK")


def test_dataset_health_gate():
    from jxvisionai.web.training_lab_core import check_dataset_health

    pdir = _mk_project(60, 2)
    meta = json.loads((pdir / "meta.json").read_text(encoding="utf-8"))
    h = check_dataset_health(pdir, meta)
    assert h.labeled_images == 60
    assert h.can_train, h.errors
    assert h.test_images_estimated >= 10
    print("dataset health can_train (60 imgs): OK")
    shutil.rmtree(pdir)


def test_health_blocks_small():
    from jxvisionai.web.training_lab_core import check_dataset_health

    pdir = _mk_project(12, 2)
    meta = json.loads((pdir / "meta.json").read_text(encoding="utf-8"))
    h = check_dataset_health(pdir, meta)
    assert not h.can_train
    assert h.errors
    print("gate blocks small dataset: OK")
    shutil.rmtree(pdir)


def test_split_no_leakage():
    from jxvisionai.web.training_lab_core import materialize_yolo_split

    pdir = _mk_project(60, 2)
    meta = json.loads((pdir / "meta.json").read_text(encoding="utf-8"))
    yaml_path = materialize_yolo_split(pdir, meta)
    assert yaml_path.is_file()
    split = json.loads((pdir / "_yolo_staging" / "split_meta.json").read_text(encoding="utf-8"))
    tr, va, te = set(split["train"]), set(split["val"]), set(split["test"])
    assert not (tr & va) and not (tr & te) and not (va & te)
    assert split["n_val"] >= 10 and split["n_test"] >= 10
    text = yaml_path.read_text(encoding="utf-8")
    assert "test: images/test" in text
    print("split train/val/test no leakage: OK")
    shutil.rmtree(pdir)


def test_draft_prelabel_and_approve():
    from jxvisionai.web.training_lab_core import (
        approve_draft_labels,
        list_draft_stems,
        list_reviewed_stems,
        sample_label_status,
    )

    pdir = _mk_project(5, 1)
    # 清空正式标注，写入草稿
    for lp in (pdir / "labels").glob("*.txt"):
        lp.unlink()
    stem = "test_000"
    (pdir / "labels_draft" / f"{stem}.txt").write_text("0 0.5 0.5 0.2 0.2\n")
    assert sample_label_status(pdir, stem) == "draft"
    assert stem in list_draft_stems(pdir)
    assert stem not in list_reviewed_stems(pdir)
    r = approve_draft_labels(pdir, stems=[stem])
    assert r["count"] == 1
    assert sample_label_status(pdir, stem) == "reviewed"
    print("draft → approve: OK")
    shutil.rmtree(pdir)


def test_deploy_gate_blocks_without_metrics():
    from jxvisionai.web.training_lab_core import deploy_weights_to_production

    models = REPO / "models"
    src = models / "smoking_detection.pt"
    if not src.is_file():
        print("deploy gate: SKIP (无 smoking_detection.pt)")
        return
    with tempfile.TemporaryDirectory() as td:
        fake = Path(td) / "best.pt"
        shutil.copy2(src, fake)
        result = deploy_weights_to_production(
            REPO,
            weights_path=fake,
            target="smoking",
            backup=False,
            patch_config=False,
            test_metrics=None,
            force=False,
        )
        assert not result.get("success"), result
        print("deploy gate blocks without test metrics: OK")


def test_deploy_with_good_metrics():
    from jxvisionai.web.training_lab_core import deploy_weights_to_production

    models = REPO / "models"
    src = models / "smoking_detection.pt"
    if not src.is_file():
        print("deploy good metrics: SKIP")
        return
    with tempfile.TemporaryDirectory() as td:
        fake = Path(td) / "best.pt"
        shutil.copy2(src, fake)
        metrics = {"ok": True, "map50": 0.55, "precision": 0.5, "recall": 0.5, "split": "test"}
        result = deploy_weights_to_production(
            REPO,
            weights_path=fake,
            target="smoking",
            backup=True,
            patch_config=False,
            test_metrics=metrics,
            force=False,
        )
        assert result.get("success"), result
        print("deploy with good test metrics: OK")


def test_p3_snapshot_list_import():
    from jxvisionai.config.settings import SAVE_DIR
    from jxvisionai.web.training_lab_core import import_snapshots_to_project, list_production_snapshots

    snaps = list_production_snapshots(Path(SAVE_DIR), limit=5)
    print(f"snapshot list: found {len(snaps)} under {SAVE_DIR}")
    pdir = _mk_project(5, 1)
    if snaps:
        r = import_snapshots_to_project(pdir, [snaps[0]["path"]], Path(SAVE_DIR))
        assert r["count"] >= 1
        print("snapshot import: OK")
    else:
        print("snapshot import: SKIP")
    shutil.rmtree(pdir)


def main():
    print("=== Training Lab production-ready self-test ===\n")
    test_p0_prepare_smoking_remap()
    test_p0_augment_disabled()
    test_helmet_class_contract()
    test_no_glasses_catalog()
    test_dataset_health_gate()
    test_health_blocks_small()
    test_split_no_leakage()
    test_draft_prelabel_and_approve()
    test_deploy_gate_blocks_without_metrics()
    test_deploy_with_good_metrics()
    test_p3_snapshot_list_import()
    print("\n=== ALL TESTS PASSED ===")


if __name__ == "__main__":
    main()
