"""训练实验室核心：场景模板、数据健康检查、评估、部署、快照回流、预标注、阈值建议。"""

from __future__ import annotations

import json
import os
import random
import re
import shutil
import subprocess
import sys
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# ---------- 场景模板（P4） ----------
TRAINING_TEMPLATES: Dict[str, Dict[str, Any]] = {
    "smoking": {
        "id": "smoking",
        "title": "吸烟检测",
        "description": "单类 smoking，与线上 smoking_cigarette_detector_path 一致",
        "classes": ["smoking"],
        "deploy_target": "smoking",
        "default_epochs": 50,
        "default_batch": 8,
        "default_imgsz": 640,
        "default_pretrained": "yolov8n.pt",
        "recommended_labeled": 80,
    },
    "safety_helmet": {
        "id": "safety_helmet",
        "title": "安全帽",
        "description": "专模 safety_helmet.pt",
        "classes": ["helmet", "no_helmet"],
        "deploy_target": "safety_helmet",
        "default_epochs": 80,
        "default_batch": 8,
        "default_imgsz": 640,
        "default_pretrained": "yolov8n.pt",
        "recommended_labeled": 100,
    },
    "make_call": {
        "id": "make_call",
        "title": "打电话",
        "description": "专模 make_call.onnx 对应的 YOLO 训练（导出 ONNX 需另步骤）",
        "classes": ["make_call"],
        "deploy_target": "make_call",
        "default_epochs": 50,
        "default_batch": 8,
        "default_imgsz": 640,
        "default_pretrained": "yolov8n.pt",
        "recommended_labeled": 80,
    },
    "custom": {
        "id": "custom",
        "title": "自定义",
        "description": "自行填写类别，不绑定部署目标",
        "classes": [],
        "deploy_target": None,
        "default_epochs": 30,
        "default_batch": 8,
        "default_imgsz": 640,
        "default_pretrained": "yolov8n.pt",
        "recommended_labeled": 50,
    },
}

# ---------- 开训门槛（P1） ----------
TRAIN_GATE_HARD = {
    "min_labeled_images": 10,
    "min_boxes_per_class": 5,
    "min_val_images": 2,
}

TRAIN_GATE_RECOMMENDED_LABELED = 80

# ---------- 部署目标（P2） ----------
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
    },
    "safety_helmet": {
        "model_filename": "safety_helmet.pt",
        "config_updates": {
            "safety_helmet_model_path": "models/safety_helmet.pt",
        },
        "required_classes": None,
    },
    "make_call": {
        "model_filename": "make_call.pt",
        "config_updates": {
            "make_call_model_path": "models/make_call.pt",
            "make_call_use_dedicated": "true",
        },
        "required_classes": ["make_call"],
        "single_class_index": 0,
    },
}


def list_labeled_stems(project_dir: Path) -> List[str]:
    img_dir = project_dir / "images"
    lbl_dir = project_dir / "labels"
    if not img_dir.is_dir():
        return []
    stems: List[str] = []
    for p in img_dir.iterdir():
        if p.suffix.lower() not in (".jpg", ".jpeg", ".png"):
            continue
        stem = p.stem
        lf = lbl_dir / f"{stem}.txt"
        if lf.is_file() and lf.stat().st_size > 0:
            stems.append(stem)
    return sorted(stems)


def materialize_yolo_split(
    project_dir: Path,
    meta: Dict[str, Any],
    *,
    val_ratio: float = 0.2,
    seed: int = 42,
) -> Path:
    """将 project images/labels 拆到 _yolo_staging/，返回 data.yaml 路径。"""
    stems = list_labeled_stems(project_dir)
    if not stems:
        raise ValueError("没有已标注图片（labels 下需有对应非空 .txt）")

    classes: List[str] = meta.get("classes") or []
    if not classes:
        raise ValueError("项目缺少类别列表")

    staging = project_dir / "_yolo_staging"
    if staging.is_dir():
        shutil.rmtree(staging)
    for sub in ("images/train", "images/val", "labels/train", "labels/val"):
        (staging / sub).mkdir(parents=True, exist_ok=True)

    rnd = random.Random(seed)
    shuffled = stems[:]
    rnd.shuffle(shuffled)
    n = len(shuffled)
    n_val = max(1, int(round(n * val_ratio))) if n > 1 else 1
    if n == 1:
        val_stems = shuffled[:]
        train_stems = shuffled[:]
    else:
        n_val = min(n_val, n - 1)
        val_stems = shuffled[:n_val]
        train_stems = shuffled[n_val:]

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

    root_abs = staging.resolve()
    yaml_path = staging / "data.yaml"
    names_lines = "\n".join(f"  {i}: {name}" for i, name in enumerate(classes))
    content = f"""path: {root_abs.as_posix()}
train: images/train
val: images/val

names:\n{names_lines}
"""
    yaml_path.write_text(content, encoding="utf-8")
    return yaml_path


@dataclass
class DatasetHealth:
    labeled_images: int
    total_images: int
    boxes_per_class: Dict[int, int]
    class_names: List[str]
    val_images_estimated: int
    can_train: bool
    warnings: List[str]
    errors: List[str]
    recommended_labeled: int

    def to_dict(self) -> Dict[str, Any]:
        return {
            "labeled_images": self.labeled_images,
            "total_images": self.total_images,
            "boxes_per_class": self.boxes_per_class,
            "class_names": self.class_names,
            "val_images_estimated": self.val_images_estimated,
            "can_train": self.can_train,
            "warnings": self.warnings,
            "errors": self.errors,
            "recommended_labeled": self.recommended_labeled,
            "gate": dict(TRAIN_GATE_HARD),
        }


def _count_boxes(project_dir: Path, class_names: List[str]) -> Tuple[int, Dict[int, int]]:
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
    val_ratio: float = 0.2,
) -> DatasetHealth:
    classes: List[str] = meta.get("classes") or []
    template_id = meta.get("template_id") or "custom"
    tpl = TRAINING_TEMPLATES.get(template_id, TRAINING_TEMPLATES["custom"])
    recommended = int(tpl.get("recommended_labeled") or TRAIN_GATE_RECOMMENDED_LABELED)

    img_dir = project_dir / "images"
    total_images = len(list(img_dir.glob("*"))) if img_dir.is_dir() else 0
    labeled, boxes = _count_boxes(project_dir, classes)
    n_val = max(1, int(round(labeled * val_ratio))) if labeled > 1 else (1 if labeled else 0)
    if labeled > 1:
        n_val = min(n_val, labeled - 1)

    warnings: List[str] = []
    errors: List[str] = []

    if labeled < recommended:
        warnings.append(f"已标注 {labeled} 张，建议至少 {recommended} 张以提升泛化")
    if labeled < TRAIN_GATE_HARD["min_labeled_images"]:
        errors.append(
            f"已标注图片 {labeled} 张，低于开训下限 {TRAIN_GATE_HARD['min_labeled_images']} 张"
        )
    if n_val < TRAIN_GATE_HARD["min_val_images"] and labeled > 0:
        errors.append(f"验证集预估仅 {n_val} 张，需要至少 {TRAIN_GATE_HARD['min_val_images']} 张")
    for i, name in enumerate(classes):
        cnt = boxes.get(i, 0)
        if cnt < TRAIN_GATE_HARD["min_boxes_per_class"]:
            errors.append(
                f"类别「{name}」仅 {cnt} 个框，需要至少 {TRAIN_GATE_HARD['min_boxes_per_class']} 个"
            )

    return DatasetHealth(
        labeled_images=labeled,
        total_images=total_images,
        boxes_per_class=boxes,
        class_names=classes,
        val_images_estimated=n_val,
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
    log_fp: Optional[Path] = None,
) -> Dict[str, Any]:
    """调用 evaluate.py eval --json-out，返回指标 dict。"""
    eval_py = repo_root / "training_system" / "scripts" / "evaluate.py"
    json_out = Path(model_path).parent / "eval_metrics.json"
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
            return {"ok": False, "error": f"evaluate 退出码 {proc.returncode}"}
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
        return {"ok": False, "error": "未生成 eval_metrics.json"}
    try:
        metrics = json.loads(json_out.read_text(encoding="utf-8"))
        metrics["ok"] = True
        return metrics
    except json.JSONDecodeError as e:
        return {"ok": False, "error": str(e)}


def _validate_deploy_classes(model_path: Path, target: str) -> Tuple[Optional[str], Optional[str]]:
    """返回 (error, warning)。"""
    spec = DEPLOY_TARGETS.get(target)
    if not spec:
        return f"未知部署目标: {target}", None
    required = spec.get("required_classes")
    if not required:
        return None, None
    try:
        from ultralytics import YOLO
    except ImportError:
        return None, "未安装 ultralytics，已跳过类别校验"
    try:
        names = YOLO(str(model_path)).names
        model_classes = [str(names[i]) for i in sorted(names.keys())]
    except Exception as e:  # noqa: BLE001
        return f"无法读取模型类别: {e}", None
    req_lower = {c.lower() for c in required}
    model_lower = {c.lower() for c in model_classes}
    if len(model_classes) == 1 and required:
        if model_lower != req_lower and not req_lower.intersection(model_lower):
            return f"模型类别 {model_classes} 与要求 {required} 不一致", None
    return None, None


def deploy_weights_to_production(
    repo_root: Path,
    *,
    weights_path: Path,
    target: str,
    backup: bool = True,
    patch_config: bool = True,
) -> Dict[str, Any]:
    """复制权重到 models/ 并可选更新 config.ini。"""
    spec = DEPLOY_TARGETS.get(target)
    if not spec:
        return {"success": False, "message": f"未知部署目标: {target}"}
    if not weights_path.is_file():
        return {"success": False, "message": "权重文件不存在"}

    err, warn = _validate_deploy_classes(weights_path, target)
    if err:
        return {"success": False, "message": err}

    models_dir = repo_root / "models"
    models_dir.mkdir(parents=True, exist_ok=True)
    dest_name = spec["model_filename"]
    dest = models_dir / dest_name
    backup_path = None
    if backup and dest.is_file():
        backup_path = models_dir / f"{dest.stem}.bak_{int(__import__('time').time())}.pt"
        shutil.copy2(dest, backup_path)

    shutil.copy2(weights_path, dest)

    # 类别清单
    try:
        from ultralytics import YOLO

        names = YOLO(str(dest)).names
        cls_file = models_dir / f"{dest.stem}_classes.txt"
        with open(cls_file, "w", encoding="utf-8") as f:
            for idx in sorted(names.keys()):
                f.write(f"{idx}: {names[idx]}\n")
    except Exception:  # noqa: BLE001
        pass

    config_patched = False
    if patch_config and spec.get("config_updates"):
        from visionai.config.ini_manager import patch_config_updates

        patch_config_updates(dict(spec["config_updates"]))
        config_patched = True

    msg = "已部署到 models/，请重启 JXVisionAI 服务后生效"
    if warn:
        msg = warn + "；" + msg
    return {
        "success": True,
        "message": msg,
        "dest": str(dest.resolve()),
        "backup": str(backup_path.resolve()) if backup_path else None,
        "config_patched": config_patched,
        "restart_required": True,
        "warning": warn,
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
    """用 best.pt 对项目图片预标注（P3）。"""
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
    lbl_dir = project_dir / "labels"
    lbl_dir.mkdir(exist_ok=True)

    labeled_stems = set()
    for lp in lbl_dir.glob("*.txt"):
        if lp.stat().st_size > 0:
            labeled_stems.add(lp.stem)

    model = YOLO(str(wp))
    dev = device if device else detect_train_device()
    processed = 0
    written = 0
    for ip in sorted(img_dir.iterdir()):
        if ip.suffix.lower() not in (".jpg", ".jpeg", ".png"):
            continue
        stem = ip.stem
        if only_unlabeled and stem in labeled_stems:
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
        lf = lbl_dir / f"{stem}.txt"
        lf.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
        if lines:
            written += 1

    return {
        "success": True,
        "processed": processed,
        "written": written,
        "message": f"已处理 {processed} 张，写入标注 {written} 张",
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
