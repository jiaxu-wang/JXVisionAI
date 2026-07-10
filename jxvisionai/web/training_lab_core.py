"""训练实验室核心：场景模板、数据健康检查、评估、部署、快照回流、预标注、阈值建议。

面向「可上线专模」：人工审核标注、train/val/test 划分、部署质量门禁、类别契约校验。
"""

from __future__ import annotations

import json
import os
import random
import re
import shutil
import subprocess
import sys
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# ---------- 场景模板 ----------
# 安全帽类别顺序必须与线上 ViolationSpec 一致：
# subject_class_ids=(0,) = 违规（未戴帽），comply_class_ids=(1,) = 合规（戴帽）
TRAINING_TEMPLATES: Dict[str, Dict[str, Any]] = {
    "smoking": {
        "id": "smoking",
        "title": "吸烟检测",
        "description": "单类 smoking，部署为 models/smoking_detection.pt",
        "classes": ["smoking"],
        "deploy_target": "smoking",
        "default_epochs": 80,
        "default_batch": 8,
        "default_imgsz": 640,
        "default_pretrained": "yolov8s.pt",
        "recommended_labeled": 120,
    },
    "safety_helmet": {
        "id": "safety_helmet",
        "title": "安全帽",
        "description": "0=no_helmet（违规）1=helmet（合规），与线上 ViolationSpec 一致",
        "classes": ["no_helmet", "helmet"],
        "deploy_target": "safety_helmet",
        "default_epochs": 100,
        "default_batch": 8,
        "default_imgsz": 640,
        "default_pretrained": "yolov8s.pt",
        "recommended_labeled": 150,
    },
    "no_glasses": {
        "id": "no_glasses",
        "title": "未戴眼镜",
        "description": "0=no_glasses（违规）1=glasses（合规）；部署 models/glasses_detection.pt",
        "classes": ["no_glasses", "glasses"],
        "deploy_target": "no_glasses",
        "default_epochs": 80,
        "default_batch": 8,
        "default_imgsz": 640,
        "default_pretrained": "yolov8s.pt",
        "recommended_labeled": 120,
    },
    "make_call": {
        "id": "make_call",
        "title": "打电话",
        "description": "单类 make_call；部署时自动导出 ONNX → models/make_call.onnx",
        "classes": ["make_call"],
        "deploy_target": "make_call",
        "default_epochs": 80,
        "default_batch": 8,
        "default_imgsz": 640,
        "default_pretrained": "yolov8s.pt",
        "recommended_labeled": 120,
    },
    "custom": {
        "id": "custom",
        "title": "自定义",
        "description": "自行填写类别，不绑定部署目标（不可一键上线）",
        "classes": [],
        "deploy_target": None,
        "default_epochs": 60,
        "default_batch": 8,
        "default_imgsz": 640,
        "default_pretrained": "yolov8s.pt",
        "recommended_labeled": 100,
    },
}

# ---------- 开训门槛（行业级最小可用） ----------
TRAIN_GATE_HARD = {
    "min_labeled_images": 50,
    "min_boxes_per_class": 30,
    "min_val_images": 10,
    "min_test_images": 10,
    "min_train_images": 30,
}

TRAIN_GATE_RECOMMENDED_LABELED = 120

# 划分比例（固定种子）；禁止 train/val/test 交叉
SPLIT_VAL_RATIO = 0.15
SPLIT_TEST_RATIO = 0.15
SPLIT_SEED = 42

# ---------- 部署质量门禁 ----------
DEPLOY_GATE = {
    "min_map50": 0.40,
    "min_precision": 0.35,
    "min_recall": 0.35,
    "require_test_metrics": True,
}

# ---------- 部署目标 ----------
DEPLOY_TARGETS: Dict[str, Dict[str, Any]] = {
    "smoking": {
        "model_filename": "smoking_detection.pt",
        "config_updates": {
            "smoking_cigarette_detector_path": "models/smoking_detection.pt",
            "smoking_cigarette_class_ids": "0",
            "smoking_yolo_direct": "true",
        },
        "required_classes": ["smoking"],
        "single_class_index": 0,
        "export_onnx": False,
    },
    "safety_helmet": {
        "model_filename": "safety_helmet.pt",
        "config_updates": {
            "safety_helmet_model_path": "models/safety_helmet.pt",
        },
        # 顺序强制：0=违规未戴，1=合规已戴
        "required_classes": ["no_helmet", "helmet"],
        "export_onnx": False,
    },
    "no_glasses": {
        "model_filename": "glasses_detection.pt",
        "config_updates": {
            "glasses_model_path": "models/glasses_detection.pt",
        },
        "required_classes": ["no_glasses", "glasses"],
        "export_onnx": False,
    },
    "make_call": {
        "model_filename": "make_call.pt",
        "onnx_filename": "make_call.onnx",
        "config_updates": {
            "make_call_model_path": "models/make_call.onnx",
            "make_call_use_dedicated": "true",
        },
        "required_classes": ["make_call"],
        "single_class_index": 0,
        "export_onnx": True,
    },
}


def _label_file_nonempty(path: Path) -> bool:
    return path.is_file() and path.stat().st_size > 0


def list_image_stems(project_dir: Path) -> List[str]:
    img_dir = project_dir / "images"
    if not img_dir.is_dir():
        return []
    stems: List[str] = []
    for p in img_dir.iterdir():
        if p.suffix.lower() in (".jpg", ".jpeg", ".png"):
            stems.append(p.stem)
    return sorted(stems)


def list_reviewed_stems(project_dir: Path) -> List[str]:
    """人工确认后的标注（labels/），才可进入训练。"""
    lbl_dir = project_dir / "labels"
    stems: List[str] = []
    for stem in list_image_stems(project_dir):
        if _label_file_nonempty(lbl_dir / f"{stem}.txt"):
            stems.append(stem)
    return stems


def list_draft_stems(project_dir: Path) -> List[str]:
    """预标注草稿（labels_draft/），未审核不计入开训。"""
    draft_dir = project_dir / "labels_draft"
    reviewed = set(list_reviewed_stems(project_dir))
    stems: List[str] = []
    for stem in list_image_stems(project_dir):
        if stem in reviewed:
            continue
        if _label_file_nonempty(draft_dir / f"{stem}.txt"):
            stems.append(stem)
    return stems


def list_labeled_stems(project_dir: Path) -> List[str]:
    """兼容旧调用：等同于已审核标注。"""
    return list_reviewed_stems(project_dir)


def sample_label_status(project_dir: Path, stem: str) -> str:
    if _label_file_nonempty(project_dir / "labels" / f"{stem}.txt"):
        return "reviewed"
    if _label_file_nonempty(project_dir / "labels_draft" / f"{stem}.txt"):
        return "draft"
    return "unlabeled"


def approve_draft_labels(
    project_dir: Path,
    stems: Optional[List[str]] = None,
    *,
    approve_all: bool = False,
) -> Dict[str, Any]:
    """将草稿标注提升为已审核（写入 labels/ 并删除 draft）。"""
    draft_dir = project_dir / "labels_draft"
    lbl_dir = project_dir / "labels"
    lbl_dir.mkdir(parents=True, exist_ok=True)
    if approve_all:
        targets = list_draft_stems(project_dir)
    else:
        targets = [s for s in (stems or []) if s]
    approved: List[str] = []
    skipped: List[str] = []
    for stem in targets:
        src = draft_dir / f"{stem}.txt"
        if not _label_file_nonempty(src):
            skipped.append(stem)
            continue
        # 已有正式标注则不覆盖
        dst = lbl_dir / f"{stem}.txt"
        if _label_file_nonempty(dst):
            skipped.append(stem)
            continue
        shutil.copy2(src, dst)
        try:
            src.unlink()
        except OSError:
            pass
        approved.append(stem)
    return {
        "success": True,
        "approved": approved,
        "skipped": skipped,
        "count": len(approved),
        "message": f"已审核通过 {len(approved)} 张",
    }


def _estimate_split_counts(
    n: int, *, val_ratio: float, test_ratio: float
) -> Tuple[int, int, int]:
    """返回 (n_train, n_val, n_test)；保证互斥；尽量满足门禁最小 val/test。"""
    if n <= 0:
        return 0, 0, 0
    if n == 1:
        return 1, 0, 0
    if n == 2:
        return 1, 1, 0

    min_val = int(TRAIN_GATE_HARD.get("min_val_images") or 1)
    min_test = int(TRAIN_GATE_HARD.get("min_test_images") or 1)
    min_train = int(TRAIN_GATE_HARD.get("min_train_images") or 1)

    n_test = max(min_test, int(round(n * test_ratio)))
    n_val = max(min_val, int(round(n * val_ratio)))
    # 保证 train 至少 min_train（若总数不够则尽量留 train）
    while n_test + n_val + min_train > n and (n_test > 1 or n_val > 1):
        if n_test >= n_val and n_test > 1:
            n_test -= 1
        elif n_val > 1:
            n_val -= 1
        else:
            break
    n_train = n - n_test - n_val
    if n_train < 1:
        n_train = 1
        leftover = n - n_train
        n_test = max(0, leftover // 2)
        n_val = leftover - n_test
    return n_train, n_val, n_test


def materialize_yolo_split(
    project_dir: Path,
    meta: Dict[str, Any],
    *,
    val_ratio: float = SPLIT_VAL_RATIO,
    test_ratio: float = SPLIT_TEST_RATIO,
    seed: int = SPLIT_SEED,
    reviewed_only: bool = True,
) -> Path:
    """将已审核标注拆到 train/val/test（互斥），返回 data.yaml。"""
    stems = list_reviewed_stems(project_dir) if reviewed_only else list_labeled_stems(project_dir)
    if not stems:
        raise ValueError("没有已审核标注（请先保存或审核通过 labels，草稿不计入训练）")

    classes: List[str] = meta.get("classes") or []
    if not classes:
        raise ValueError("项目缺少类别列表")

    staging = project_dir / "_yolo_staging"
    if staging.is_dir():
        shutil.rmtree(staging)
    for sub in (
        "images/train",
        "images/val",
        "images/test",
        "labels/train",
        "labels/val",
        "labels/test",
    ):
        (staging / sub).mkdir(parents=True, exist_ok=True)

    rnd = random.Random(seed)
    shuffled = stems[:]
    rnd.shuffle(shuffled)
    n = len(shuffled)
    n_train, n_val, n_test = _estimate_split_counts(n, val_ratio=val_ratio, test_ratio=test_ratio)
    if n_val < 1 or n_test < 1:
        raise ValueError(
            f"已审核样本 {n} 张不足以划分独立 val/test（需要更多已审核图）"
        )

    test_stems = shuffled[:n_test]
    val_stems = shuffled[n_test : n_test + n_val]
    train_stems = shuffled[n_test + n_val :]
    if not train_stems:
        raise ValueError("训练集为空，请增加已审核样本")

    s_train, s_val, s_test = set(train_stems), set(val_stems), set(test_stems)
    if s_train & s_val or s_train & s_test or s_val & s_test:
        raise ValueError("划分出现交叉，请重试")

    def _copy(stem_list: List[str], split: str) -> None:
        for stem in stem_list:
            src_i = None
            for ext in (".jpg", ".jpeg", ".png"):
                cand = project_dir / "images" / f"{stem}{ext}"
                if cand.is_file():
                    src_i = cand
                    break
            if src_i is None:
                continue
            ext = src_i.suffix.lower()
            shutil.copy2(src_i, staging / "images" / split / f"{stem}{ext}")
            shutil.copy2(
                project_dir / "labels" / f"{stem}.txt",
                staging / "labels" / split / f"{stem}.txt",
            )

    _copy(train_stems, "train")
    _copy(val_stems, "val")
    _copy(test_stems, "test")

    root_abs = staging.resolve()
    yaml_path = staging / "data.yaml"
    names_lines = "\n".join(f"  {i}: {name}" for i, name in enumerate(classes))
    content = f"""path: {root_abs.as_posix()}
train: images/train
val: images/val
test: images/test

names:\n{names_lines}
"""
    yaml_path.write_text(content, encoding="utf-8")
    split_meta = {
        "seed": seed,
        "n_total": n,
        "n_train": len(train_stems),
        "n_val": len(val_stems),
        "n_test": len(test_stems),
        "train": train_stems,
        "val": val_stems,
        "test": test_stems,
    }
    (staging / "split_meta.json").write_text(
        json.dumps(split_meta, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return yaml_path


@dataclass
class DatasetHealth:
    labeled_images: int
    draft_images: int
    total_images: int
    boxes_per_class: Dict[int, int]
    class_names: List[str]
    train_images_estimated: int
    val_images_estimated: int
    test_images_estimated: int
    can_train: bool
    warnings: List[str]
    errors: List[str]
    recommended_labeled: int

    def to_dict(self) -> Dict[str, Any]:
        return {
            "labeled_images": self.labeled_images,
            "reviewed_images": self.labeled_images,
            "draft_images": self.draft_images,
            "total_images": self.total_images,
            "boxes_per_class": self.boxes_per_class,
            "class_names": self.class_names,
            "train_images_estimated": self.train_images_estimated,
            "val_images_estimated": self.val_images_estimated,
            "test_images_estimated": self.test_images_estimated,
            "can_train": self.can_train,
            "warnings": self.warnings,
            "errors": self.errors,
            "recommended_labeled": self.recommended_labeled,
            "gate": dict(TRAIN_GATE_HARD),
            "split": {
                "val_ratio": SPLIT_VAL_RATIO,
                "test_ratio": SPLIT_TEST_RATIO,
                "seed": SPLIT_SEED,
            },
            "deploy_gate": dict(DEPLOY_GATE),
        }


def _count_boxes(project_dir: Path, class_names: List[str]) -> Tuple[int, Dict[int, int]]:
    """仅统计已审核 labels/。"""
    lbl_dir = project_dir / "labels"
    img_dir = project_dir / "images"
    if not lbl_dir.is_dir() or not img_dir.is_dir():
        return 0, {}
    labeled = 0
    boxes: Dict[int, int] = {i: 0 for i in range(len(class_names))}
    for lp in lbl_dir.glob("*.txt"):
        if lp.stat().st_size == 0:
            continue
        stem = lp.stem
        has_img = any((img_dir / f"{stem}{ext}").is_file() for ext in (".jpg", ".jpeg", ".png"))
        if not has_img:
            continue
        labeled += 1
        for line in lp.read_text(encoding="utf-8").splitlines():
            parts = line.strip().split()
            if len(parts) < 5:
                continue
            try:
                ci = int(float(parts[0]))
            except ValueError:
                continue
            if 0 <= ci < len(class_names):
                boxes[ci] = boxes.get(ci, 0) + 1
    return labeled, boxes


def check_dataset_health(
    project_dir: Path,
    meta: Dict[str, Any],
    *,
    val_ratio: float = SPLIT_VAL_RATIO,
    test_ratio: float = SPLIT_TEST_RATIO,
) -> DatasetHealth:
    classes: List[str] = meta.get("classes") or []
    template_id = meta.get("template_id") or "custom"
    tpl = TRAINING_TEMPLATES.get(template_id, TRAINING_TEMPLATES["custom"])
    recommended = int(tpl.get("recommended_labeled") or TRAIN_GATE_RECOMMENDED_LABELED)

    img_dir = project_dir / "images"
    total_images = (
        len([p for p in img_dir.iterdir() if p.suffix.lower() in (".jpg", ".jpeg", ".png")])
        if img_dir.is_dir()
        else 0
    )
    labeled, boxes = _count_boxes(project_dir, classes)
    draft_n = len(list_draft_stems(project_dir))
    n_train, n_val, n_test = _estimate_split_counts(
        labeled, val_ratio=val_ratio, test_ratio=test_ratio
    )

    warnings: List[str] = []
    errors: List[str] = []

    if draft_n > 0:
        warnings.append(f"有 {draft_n} 张预标注草稿未审核，不计入训练")
    if labeled < recommended:
        warnings.append(f"已审核 {labeled} 张，建议至少 {recommended} 张以提升泛化")
    if labeled < TRAIN_GATE_HARD["min_labeled_images"]:
        errors.append(
            f"已审核图片 {labeled} 张，低于开训下限 {TRAIN_GATE_HARD['min_labeled_images']} 张"
        )
    if n_train < TRAIN_GATE_HARD["min_train_images"] and labeled > 0:
        errors.append(
            f"训练集预估仅 {n_train} 张，需要至少 {TRAIN_GATE_HARD['min_train_images']} 张"
        )
    if n_val < TRAIN_GATE_HARD["min_val_images"] and labeled > 0:
        errors.append(
            f"验证集预估仅 {n_val} 张，需要至少 {TRAIN_GATE_HARD['min_val_images']} 张"
        )
    if n_test < TRAIN_GATE_HARD["min_test_images"] and labeled > 0:
        errors.append(
            f"测试集预估仅 {n_test} 张，需要至少 {TRAIN_GATE_HARD['min_test_images']} 张"
        )
    for i, name in enumerate(classes):
        cnt = boxes.get(i, 0)
        if cnt < TRAIN_GATE_HARD["min_boxes_per_class"]:
            errors.append(
                f"类别「{name}」仅 {cnt} 个框，需要至少 {TRAIN_GATE_HARD['min_boxes_per_class']} 个"
            )

    # 安全帽 / 眼镜类别契约提示
    if template_id == "safety_helmet" and classes:
        expected = TRAINING_TEMPLATES["safety_helmet"]["classes"]
        if [c.lower() for c in classes] != [c.lower() for c in expected]:
            errors.append(
                f"安全帽类别顺序须为 {expected}（0=未戴违规，1=已戴合规），当前为 {classes}"
            )
    if template_id == "no_glasses" and classes:
        expected = TRAINING_TEMPLATES["no_glasses"]["classes"]
        if [c.lower() for c in classes] != [c.lower() for c in expected]:
            errors.append(
                f"眼镜类别顺序须为 {expected}（0=未戴违规，1=已戴合规），当前为 {classes}"
            )

    return DatasetHealth(
        labeled_images=labeled,
        draft_images=draft_n,
        total_images=total_images,
        boxes_per_class=boxes,
        class_names=classes,
        train_images_estimated=n_train,
        val_images_estimated=n_val,
        test_images_estimated=n_test,
        can_train=len(errors) == 0,
        warnings=warnings,
        errors=errors,
        recommended_labeled=recommended,
    )


def detect_train_device() -> str:
    try:
        import torch

        if torch.cuda.is_available():
            return "0"
    except Exception:  # noqa: BLE001
        pass
    return "cpu"


def run_evaluate_subprocess(
    repo_root: Path,
    *,
    model_path: str,
    data_yaml: str,
    device: str,
    split: str = "val",
    log_fp: Optional[Path] = None,
) -> Dict[str, Any]:
    """调用 evaluate.py eval --json-out，返回指标 dict。"""
    eval_py = repo_root / "training_system" / "scripts" / "evaluate.py"
    split_safe = split if split in ("val", "test", "train") else "val"
    json_out = Path(model_path).parent / f"eval_metrics_{split_safe}.json"
    cmd = [
        sys.executable,
        str(eval_py),
        "eval",
        "--model",
        model_path,
        "--data",
        data_yaml,
        "--device",
        device.strip() or "cpu",
        "--split",
        split_safe,
        "--json-out",
        str(json_out),
    ]
    if log_fp:
        with open(log_fp, "a", encoding="utf-8") as logf:
            logf.write(f"\n$ {' '.join(cmd)}\n")
            logf.flush()
            proc = subprocess.run(
                cmd,
                cwd=str(repo_root / "training_system"),
                stdout=logf,
                stderr=subprocess.STDOUT,
                env={**os.environ},
            )
        if proc.returncode != 0:
            return {"ok": False, "error": f"evaluate({split_safe}) 退出码 {proc.returncode}"}
    else:
        proc = subprocess.run(
            cmd,
            cwd=str(repo_root / "training_system"),
            capture_output=True,
            text=True,
            env={**os.environ},
        )
        if proc.returncode != 0:
            return {"ok": False, "error": proc.stderr or proc.stdout or "evaluate failed"}

    if not json_out.is_file():
        return {"ok": False, "error": f"未生成 eval_metrics_{split_safe}.json"}
    try:
        metrics = json.loads(json_out.read_text(encoding="utf-8"))
        metrics["ok"] = True
        metrics["split"] = split_safe
        return metrics
    except json.JSONDecodeError as e:
        return {"ok": False, "error": str(e)}


def check_deploy_quality_gate(
    metrics: Optional[Dict[str, Any]],
    *,
    force: bool = False,
) -> Tuple[bool, List[str]]:
    """返回 (passed, errors)。force 不改变判定，仅由调用方决定是否绕过。"""
    del force  # 保留参数以兼容调用签名
    errors: List[str] = []
    if not metrics or not metrics.get("ok"):
        if DEPLOY_GATE.get("require_test_metrics"):
            errors.append("缺少有效的测试集评估指标，禁止上线")
        return len(errors) == 0, errors

    map50 = metrics.get("map50")
    precision = metrics.get("precision")
    recall = metrics.get("recall")
    if map50 is not None and float(map50) < float(DEPLOY_GATE["min_map50"]):
        errors.append(
            f"测试集 mAP@0.5={float(map50):.4f} < 门禁 {DEPLOY_GATE['min_map50']}"
        )
    if precision is not None and float(precision) < float(DEPLOY_GATE["min_precision"]):
        errors.append(
            f"测试集 Precision={float(precision):.4f} < 门禁 {DEPLOY_GATE['min_precision']}"
        )
    if recall is not None and float(recall) < float(DEPLOY_GATE["min_recall"]):
        errors.append(
            f"测试集 Recall={float(recall):.4f} < 门禁 {DEPLOY_GATE['min_recall']}"
        )
    return len(errors) == 0, errors


def _validate_deploy_classes(model_path: Path, target: str) -> Tuple[Optional[str], Optional[str]]:
    """返回 (error, warning)。强制校验 required_classes 顺序。"""
    spec = DEPLOY_TARGETS.get(target)
    if not spec:
        return f"未知部署目标: {target}", None
    required = spec.get("required_classes")
    if not required:
        return None, None
    try:
        from ultralytics import YOLO
    except ImportError:
        return "未安装 ultralytics，无法校验类别契约", None
    try:
        names = YOLO(str(model_path)).names
        model_classes = [str(names[i]) for i in sorted(names.keys())]
    except Exception as e:  # noqa: BLE001
        return f"无法读取模型类别: {e}", None

    req = [str(c).lower() for c in required]
    got = [str(c).lower() for c in model_classes]
    if got != req:
        return (
            f"模型类别顺序 {model_classes} 与线上契约 {required} 不一致（须完全一致）",
            None,
        )
    return None, None


def _export_onnx_beside(weights_path: Path, *, device: str = "cpu") -> Optional[Path]:
    """导出 ONNX 到权重同目录，返回路径。"""
    try:
        from ultralytics import YOLO
    except ImportError:
        return None
    try:
        model = YOLO(str(weights_path))
        exported = model.export(
            format="onnx",
            imgsz=640,
            simplify=True,
            device=device.strip() or "cpu",
            dynamic=False,
            opset=12,
        )
        p = Path(str(exported))
        return p if p.is_file() else None
    except Exception:  # noqa: BLE001
        return None


def deploy_weights_to_production(
    repo_root: Path,
    *,
    weights_path: Path,
    target: str,
    backup: bool = True,
    patch_config: bool = True,
    test_metrics: Optional[Dict[str, Any]] = None,
    force: bool = False,
    export_device: str = "cpu",
) -> Dict[str, Any]:
    """复制权重到 models/，可选 ONNX 导出与 config.ini 更新；默认过质量门禁。"""
    spec = DEPLOY_TARGETS.get(target)
    if not spec:
        return {"success": False, "message": f"未知部署目标: {target}"}
    if not weights_path.is_file():
        return {"success": False, "message": "权重文件不存在"}

    gate_ok, gate_errors = check_deploy_quality_gate(test_metrics, force=force)
    if not gate_ok and not force:
        return {
            "success": False,
            "message": "未通过上线质量门禁：" + "；".join(gate_errors),
            "gate_errors": gate_errors,
            "test_metrics": test_metrics,
        }

    err, warn = _validate_deploy_classes(weights_path, target)
    if err:
        return {"success": False, "message": err}

    models_dir = repo_root / "models"
    models_dir.mkdir(parents=True, exist_ok=True)
    dest_name = spec["model_filename"]
    dest = models_dir / dest_name
    backup_path = None
    if backup and dest.is_file():
        backup_path = models_dir / f"{dest.stem}.bak_{int(time.time())}.pt"
        shutil.copy2(dest, backup_path)

    shutil.copy2(weights_path, dest)

    onnx_dest = None
    if spec.get("export_onnx") and spec.get("onnx_filename"):
        onnx_src = _export_onnx_beside(weights_path, device=export_device)
        if onnx_src is None:
            # 尝试同目录已有 .onnx
            cand = weights_path.with_suffix(".onnx")
            onnx_src = cand if cand.is_file() else None
        if onnx_src is None or not onnx_src.is_file():
            return {
                "success": False,
                "message": "需要导出 ONNX 但失败（请确认 ultralytics/onnx 可用）",
            }
        onnx_dest = models_dir / spec["onnx_filename"]
        if backup and onnx_dest.is_file():
            bak_o = models_dir / f"{onnx_dest.stem}.bak_{int(time.time())}.onnx"
            shutil.copy2(onnx_dest, bak_o)
        shutil.copy2(onnx_src, onnx_dest)

    # 类别清单 + 部署元数据
    try:
        from ultralytics import YOLO

        names = YOLO(str(dest)).names
        cls_file = models_dir / f"{dest.stem}_classes.txt"
        with open(cls_file, "w", encoding="utf-8") as f:
            for idx in sorted(names.keys()):
                f.write(f"{idx}: {names[idx]}\n")
    except Exception:  # noqa: BLE001
        names = {}

    registry = {
        "target": target,
        "weights": str(dest.resolve()),
        "onnx": str(onnx_dest.resolve()) if onnx_dest else None,
        "deployed_at": time.time(),
        "test_metrics": test_metrics,
        "forced": bool(force),
        "gate_errors": gate_errors if force else [],
        "classes": [str(names[i]) for i in sorted(names.keys())] if names else None,
    }
    (models_dir / f"{dest.stem}_deploy.json").write_text(
        json.dumps(registry, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    config_patched = False
    if patch_config and spec.get("config_updates"):
        from jxvisionai.config.ini_manager import patch_config_updates

        patch_config_updates(dict(spec["config_updates"]))
        config_patched = True

    msg = "已部署到 models/，请重启 JXVisionAI 服务后生效"
    if force and gate_errors:
        msg = "已强制部署（未达门禁：" + "；".join(gate_errors) + "）；" + msg
    if warn:
        msg = warn + "；" + msg
    if onnx_dest:
        msg += f"；已同步 ONNX → {onnx_dest.name}"
    return {
        "success": True,
        "message": msg,
        "dest": str(dest.resolve()),
        "onnx_dest": str(onnx_dest.resolve()) if onnx_dest else None,
        "backup": str(backup_path.resolve()) if backup_path else None,
        "config_patched": config_patched,
        "restart_required": True,
        "warning": warn,
        "forced": bool(force),
        "test_metrics": test_metrics,
        "gate": dict(DEPLOY_GATE),
    }


def list_production_snapshots(
    save_dir: Path,
    *,
    stream: str = "",
    detection_type: str = "",
    limit: int = 50,
) -> List[Dict[str, Any]]:
    """列举生产 snapshots 下的 jpg（P3）。"""
    if not save_dir.is_dir():
        return []
    out: List[Dict[str, Any]] = []
    stream = (stream or "").strip()
    det = (detection_type or "").strip().lower()
    roots: List[Path] = []
    if stream:
        cand = save_dir / stream
        if cand.is_dir():
            roots = [cand]
    else:
        roots = [save_dir]

    for root in roots:
        for p in sorted(root.rglob("*.jpg"), key=lambda x: x.stat().st_mtime, reverse=True):
            if det:
                # 路径或文件名含检测类型关键字（如 smoking、sleep）
                rel = str(p.relative_to(save_dir)).lower()
                if det not in rel and det not in p.name.lower():
                    continue
            try:
                mtime = p.stat().st_mtime
            except OSError:
                continue
            out.append(
                {
                    "path": str(p.resolve()),
                    "relative": str(p.relative_to(save_dir)),
                    "stream": p.relative_to(save_dir).parts[0] if p.relative_to(save_dir).parts else "",
                    "filename": p.name,
                    "mtime": mtime,
                }
            )
            if len(out) >= limit:
                return out
    return out


def import_snapshots_to_project(
    project_dir: Path,
    snapshot_paths: List[str],
    save_dir: Path,
) -> Dict[str, Any]:
    """从 snapshots 复制图片到项目 images/。"""
    img_dir = project_dir / "images"
    img_dir.mkdir(parents=True, exist_ok=True)
    save_resolved = save_dir.resolve()
    imported: List[str] = []
    skipped: List[str] = []
    for raw in snapshot_paths:
        p = Path(raw).resolve()
        if not p.is_file() or p.suffix.lower() not in (".jpg", ".jpeg", ".png"):
            skipped.append(raw)
            continue
        try:
            p.relative_to(save_resolved)
        except ValueError:
            skipped.append(raw)
            continue
        ext = p.suffix.lower()
        name = f"snap_{int(__import__('time').time())}_{uuid.uuid4().hex[:6]}{ext}"
        shutil.copy2(p, img_dir / name)
        imported.append(name)
    return {"imported": imported, "skipped": skipped, "count": len(imported)}


def prelabel_project_images(
    project_dir: Path,
    *,
    weights_path: str,
    conf: float = 0.25,
    only_unlabeled: bool = True,
    device: Optional[str] = None,
) -> Dict[str, Any]:
    """用 best.pt 写入 labels_draft/（草稿），须人工审核后才计入训练。"""
    from ultralytics import YOLO

    wp = Path(weights_path)
    if not wp.is_file():
        return {"success": False, "message": "权重不存在"}

    meta_path = project_dir / "meta.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.is_file() else {}
    n_class = len(meta.get("classes") or [])
    if n_class < 1:
        return {"success": False, "message": "项目无类别"}

    img_dir = project_dir / "images"
    draft_dir = project_dir / "labels_draft"
    draft_dir.mkdir(exist_ok=True)
    lbl_dir = project_dir / "labels"

    reviewed_stems = set(list_reviewed_stems(project_dir))
    draft_stems = set()
    for lp in draft_dir.glob("*.txt"):
        if lp.stat().st_size > 0:
            draft_stems.add(lp.stem)

    model = YOLO(str(wp))
    dev = device if device else detect_train_device()
    processed = 0
    written = 0
    for ip in sorted(img_dir.iterdir()):
        if ip.suffix.lower() not in (".jpg", ".jpeg", ".png"):
            continue
        stem = ip.stem
        if only_unlabeled and (stem in reviewed_stems or stem in draft_stems):
            continue
        # 已有正式标注绝不覆盖
        if stem in reviewed_stems:
            continue
        processed += 1
        results = model.predict(source=str(ip), conf=conf, device=dev, verbose=False)
        lines: List[str] = []
        if results and results[0].boxes is not None:
            for box in results[0].boxes:
                ci = int(box.cls[0])
                if not (0 <= ci < n_class):
                    continue
                xywhn = box.xywhn[0].tolist()
                lines.append(
                    f"{ci} {xywhn[0]:.6f} {xywhn[1]:.6f} {xywhn[2]:.6f} {xywhn[3]:.6f}"
                )
        lf = draft_dir / f"{stem}.txt"
        lf.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
        if lines:
            written += 1

    return {
        "success": True,
        "processed": processed,
        "written": written,
        "draft": True,
        "message": (
            f"已处理 {processed} 张，写入草稿 {written} 张（labels_draft/）。"
            "请在样本列表中审核通过后才会计入训练。"
        ),
    }


def suggest_thresholds_from_val(
    weights_path: str,
    staging_yaml: Path,
    staging_root: Path,
    *,
    class_index: int = 0,
) -> Dict[str, Any]:
    """在验证集上扫描置信度，建议 detector_conf（P4）。"""
    from ultralytics import YOLO

    val_img = staging_root / "images" / "val"
    val_lbl = staging_root / "labels" / "val"
    if not val_img.is_dir():
        return {"ok": False, "message": "无验证集"}

    model = YOLO(weights_path)
    conf_candidates = [0.15, 0.20, 0.25, 0.30, 0.35, 0.40, 0.45, 0.50, 0.55, 0.60]

    def load_gt(stem: str) -> List[Tuple[int, float, float, float, float]]:
        lp = val_lbl / f"{stem}.txt"
        if not lp.is_file():
            return []
        gt = []
        for line in lp.read_text(encoding="utf-8").splitlines():
            p = line.strip().split()
            if len(p) < 5:
                continue
            gt.append(
                (
                    int(float(p[0])),
                    float(p[1]),
                    float(p[2]),
                    float(p[3]),
                    float(p[4]),
                )
            )
        return gt

    def iou_yolo(
        a: Tuple[float, float, float, float],
        b: Tuple[float, float, float, float],
    ) -> float:
        ax, ay, aw, ah = a
        bx, by, bw, bh = b
        ax1, ay1 = ax - aw / 2, ay - ah / 2
        ax2, ay2 = ax + aw / 2, ay + ah / 2
        bx1, by1 = bx - bw / 2, by - bh / 2
        bx2, by2 = bx + bw / 2, by + bh / 2
        ix1, iy1 = max(ax1, bx1), max(ay1, by1)
        ix2, iy2 = min(ax2, bx2), min(ay2, by2)
        inter = max(0, ix2 - ix1) * max(0, iy2 - iy1)
        union = aw * ah + bw * bh - inter
        return inter / union if union > 0 else 0.0

    images = [
        p
        for p in val_img.iterdir()
        if p.suffix.lower() in (".jpg", ".jpeg", ".png")
    ]
    if not images:
        return {"ok": False, "message": "验证集无图片"}

    best_f1 = -1.0
    best_conf = 0.30
    curve: List[Dict[str, float]] = []

    for conf in conf_candidates:
        tp = fp = fn = 0
        for ip in images:
            gt_boxes = [
                (ci, cx, cy, w, h)
                for ci, cx, cy, w, h in load_gt(ip.stem)
                if ci == class_index
            ]
            preds = model.predict(source=str(ip), conf=conf, verbose=False)
            pred_boxes: List[Tuple[float, float, float, float]] = []
            if preds and preds[0].boxes is not None:
                for box in preds[0].boxes:
                    if int(box.cls[0]) != class_index:
                        continue
                    xywhn = box.xywhn[0].tolist()
                    pred_boxes.append(tuple(xywhn))
            matched_gt = set()
            for pb in pred_boxes:
                hit = False
                for gi, gb in enumerate(gt_boxes):
                    if gi in matched_gt:
                        continue
                    if iou_yolo(pb[0:4], gb[1:5]) >= 0.5:
                        tp += 1
                        matched_gt.add(gi)
                        hit = True
                        break
                if not hit:
                    fp += 1
            fn += len(gt_boxes) - len(matched_gt)

        prec = tp / (tp + fp) if (tp + fp) else 0.0
        rec = tp / (tp + fn) if (tp + fn) else 0.0
        f1 = 2 * prec * rec / (prec + rec) if (prec + rec) else 0.0
        curve.append({"conf": conf, "precision": round(prec, 4), "recall": round(rec, 4), "f1": round(f1, 4)})
        if f1 >= best_f1:
            best_f1 = f1
            best_conf = conf

    # 业务层告警阈值略高于 detector conf
    alert_conf = min(0.95, round(best_conf + 0.15, 2))

    return {
        "ok": True,
        "suggested_detector_conf": best_conf,
        "suggested_alert_conf": alert_conf,
        "suggested_min_duration_sec": 1.5,
        "curve": curve,
        "val_images": len(images),
    }
