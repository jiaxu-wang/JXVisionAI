"""训练实验室部署 / 外置导入的专模检测类型注册表。

目录布局::

    models/specialists/<key>/
        model.pt          # 或 model.onnx
        specialist.json   # 元数据（目录与 UI / 运行时契约）

专模会出现在检测类型配置中，可按流勾选；删除时同步移除权重与各流 detections 键。

来源（``origin``）::

    - ``trained``：训练实验室一键部署
    - ``imported``：社区/平台现成权重，经「导入现成专模」登记
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

logger = logging.getLogger(__name__)

SPECIALIST_KINDS = frozenset({"scene", "person_event", "violation"})
_KEY_RE = re.compile(r"^[a-z][a-z0-9_]{1,47}$")

# 内置扩展键 + COCO 数字键不可占用
_BUILTIN_RESERVED = frozenset(
    {
        "call",
        "phone_play",
        "gather",
        "face_recognition",
        "plate_recognition",
        "person",
        "cell_phone",
    }
)


def specialists_root(repo_root: Optional[Path] = None) -> Path:
    if repo_root is None:
        from visionai.config.settings import PROJECT_ROOT

        repo_root = Path(PROJECT_ROOT)
    return Path(repo_root) / "models" / "specialists"


def is_valid_specialist_key(key: str, *, reserved: Optional[Sequence[str]] = None) -> bool:
    k = (key or "").strip()
    if not _KEY_RE.match(k):
        return False
    if k.isdigit():
        return False
    if k in _BUILTIN_RESERVED:
        return False
    if reserved and k in reserved:
        return False
    return True


def _default_conf() -> float:
    try:
        from visionai.config.settings import DEDICATED_DEFAULT_CONF

        return float(DEDICATED_DEFAULT_CONF)
    except Exception:  # noqa: BLE001
        return 0.40


def _default_score() -> float:
    try:
        from visionai.config.settings import DEDICATED_DEFAULT_SCORE_THRESHOLD

        return float(DEDICATED_DEFAULT_SCORE_THRESHOLD)
    except Exception:  # noqa: BLE001
        return 0.45


def _default_duration() -> float:
    try:
        from visionai.config.settings import DEDICATED_DEFAULT_MIN_DURATION_SEC

        return float(DEDICATED_DEFAULT_MIN_DURATION_SEC)
    except Exception:  # noqa: BLE001
        return 1.0


def _default_max_persons() -> int:
    try:
        from visionai.config.settings import DEDICATED_MAX_PERSONS_PER_FRAME

        return int(DEDICATED_MAX_PERSONS_PER_FRAME)
    except Exception:  # noqa: BLE001
        return 8


def specialist_dir(key: str, repo_root: Optional[Path] = None) -> Path:
    return specialists_root(repo_root) / key.strip()


def _meta_path(key: str, repo_root: Optional[Path] = None) -> Path:
    return specialist_dir(key, repo_root) / "specialist.json"


def _normalize_int_tuple(raw: Any, fallback: Tuple[int, ...]) -> Tuple[int, ...]:
    if raw is None:
        return fallback
    if isinstance(raw, (list, tuple)):
        out: List[int] = []
        for x in raw:
            try:
                out.append(int(x))
            except (TypeError, ValueError):
                continue
        return tuple(out) if out else fallback
    return fallback


def normalize_specialist_meta(raw: Dict[str, Any], *, key: str) -> Dict[str, Any]:
    kind = str(raw.get("kind") or "person_event").strip().lower()
    if kind not in SPECIALIST_KINDS:
        kind = "person_event"
    name_zh = str(raw.get("name_zh") or key).strip() or key
    name_en = str(raw.get("name_en") or name_zh).strip() or name_zh
    model_path = str(raw.get("model_path") or "").strip()
    classes = raw.get("classes")
    if not isinstance(classes, list):
        classes = []
    classes = [str(c) for c in classes]

    conf = float(raw.get("conf") if raw.get("conf") is not None else _default_conf())
    score_threshold = float(
        raw.get("score_threshold")
        if raw.get("score_threshold") is not None
        else _default_score()
    )
    min_duration_sec = float(
        raw.get("min_duration_sec")
        if raw.get("min_duration_sec") is not None
        else _default_duration()
    )
    max_persons = int(raw.get("max_persons") or _default_max_persons())
    needs_persons = bool(raw.get("needs_persons", True))

    class_ids = raw.get("class_ids")
    class_ids_t: Optional[Tuple[int, ...]] = None
    if isinstance(class_ids, (list, tuple)) and class_ids:
        class_ids_t = _normalize_int_tuple(class_ids, ())

    positive = _normalize_int_tuple(raw.get("positive_class_ids"), (0,))
    subject = _normalize_int_tuple(raw.get("subject_class_ids"), (0,))
    comply = _normalize_int_tuple(raw.get("comply_class_ids"), (1,))

    return {
        "key": key,
        "kind": kind,
        "name_zh": name_zh,
        "name_en": name_en,
        "model_path": model_path,
        "classes": classes,
        "conf": max(0.05, min(0.99, conf)),
        "score_threshold": max(0.05, min(0.99, score_threshold)),
        "min_duration_sec": max(0.0, min_duration_sec),
        "max_persons": max(1, max_persons),
        "needs_persons": needs_persons,
        "class_ids": list(class_ids_t) if class_ids_t is not None else None,
        "positive_class_ids": list(positive),
        "subject_class_ids": list(subject),
        "comply_class_ids": list(comply),
        "created_at": raw.get("created_at"),
        "updated_at": raw.get("updated_at"),
        "source_project_id": raw.get("source_project_id"),
        "test_metrics": raw.get("test_metrics"),
        "source": "specialist",
        "origin": _normalize_origin(raw.get("origin")),
    }


def _normalize_origin(raw: Any) -> str:
    o = str(raw or "trained").strip().lower()
    if o in ("imported", "import", "external", "byo"):
        return "imported"
    return "trained"


def inspect_yolo_weights(weights_path: Path) -> Dict[str, Any]:
    """读取 Ultralytics YOLO 权重的类别名（导入向导预检用）。"""
    path = Path(weights_path)
    if not path.is_file():
        return {"success": False, "message": "权重文件不存在"}
    suffix = path.suffix.lower()
    if suffix not in (".pt", ".onnx"):
        return {"success": False, "message": "仅支持 .pt / .onnx"}
    try:
        from ultralytics import YOLO

        model = YOLO(str(path))
        names = model.names
        if isinstance(names, dict):
            classes = [str(names[i]) for i in sorted(int(k) for k in names.keys())]
        elif isinstance(names, (list, tuple)):
            classes = [str(x) for x in names]
        else:
            classes = []
        return {
            "success": True,
            "classes": classes,
            "num_classes": len(classes),
            "filename": path.name,
            "size_bytes": path.stat().st_size,
        }
    except Exception as e:  # noqa: BLE001
        return {"success": False, "message": f"无法读取权重类别: {e}"}


def load_specialist(key: str, repo_root: Optional[Path] = None) -> Optional[Dict[str, Any]]:
    key = (key or "").strip()
    if not key:
        return None
    mp = _meta_path(key, repo_root)
    if not mp.is_file():
        return None
    try:
        raw = json.loads(mp.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            return None
        meta = normalize_specialist_meta(raw, key=key)
        # 若相对路径失效，尝试目录内 model.*
        rel = meta.get("model_path") or ""
        root = Path(repo_root) if repo_root else None
        if root is None:
            from visionai.config.settings import PROJECT_ROOT

            root = Path(PROJECT_ROOT)
        abs_model = Path(rel)
        if not abs_model.is_absolute():
            abs_model = root / rel
        if not abs_model.is_file():
            d = specialist_dir(key, root)
            for name in ("model.pt", "model.onnx"):
                cand = d / name
                if cand.is_file():
                    meta["model_path"] = str(cand.relative_to(root)).replace("\\", "/")
                    break
        return meta
    except Exception as e:  # noqa: BLE001
        logger.warning("读取专模 %s 失败: %s", key, e)
        return None


def list_specialists(repo_root: Optional[Path] = None) -> List[Dict[str, Any]]:
    root = specialists_root(repo_root)
    if not root.is_dir():
        return []
    out: List[Dict[str, Any]] = []
    for child in sorted(root.iterdir()):
        if not child.is_dir():
            continue
        meta = load_specialist(child.name, repo_root)
        if meta:
            out.append(meta)
    return out


def specialist_keys(repo_root: Optional[Path] = None) -> Tuple[str, ...]:
    return tuple(m["key"] for m in list_specialists(repo_root))


def catalog_items_for_specialists(repo_root: Optional[Path] = None) -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    for meta in list_specialists(repo_root):
        items.append(
            {
                "key": meta["key"],
                "class_id": None,
                "name_en": meta["name_en"],
                "name_zh": meta["name_zh"],
                "supported": True,
                "source": "specialist",
                "origin": meta.get("origin") or "trained",
                "kind": meta["kind"],
                "deletable": True,
            }
        )
    return items


def save_specialist_meta(meta: Dict[str, Any], repo_root: Optional[Path] = None) -> Path:
    key = str(meta["key"]).strip()
    d = specialist_dir(key, repo_root)
    d.mkdir(parents=True, exist_ok=True)
    path = d / "specialist.json"
    payload = dict(meta)
    payload["updated_at"] = time.time()
    if not payload.get("created_at"):
        payload["created_at"] = payload["updated_at"]
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def deploy_specialist(
    repo_root: Path,
    *,
    weights_path: Path,
    key: str,
    kind: str,
    name_zh: str,
    name_en: str = "",
    classes: Optional[List[str]] = None,
    conf: Optional[float] = None,
    score_threshold: Optional[float] = None,
    min_duration_sec: Optional[float] = None,
    positive_class_ids: Optional[Sequence[int]] = None,
    subject_class_ids: Optional[Sequence[int]] = None,
    comply_class_ids: Optional[Sequence[int]] = None,
    class_ids: Optional[Sequence[int]] = None,
    needs_persons: bool = True,
    source_project_id: Optional[str] = None,
    test_metrics: Optional[Dict[str, Any]] = None,
    backup: bool = True,
    origin: str = "trained",
) -> Dict[str, Any]:
    """复制权重到 models/specialists/<key>/ 并写入 specialist.json。"""
    key = (key or "").strip()
    if not is_valid_specialist_key(key):
        return {
            "success": False,
            "message": "专模键名无效（须小写字母开头，仅含 a-z0-9_，且不可与内置检测键冲突）",
        }
    kind = (kind or "person_event").strip().lower()
    if kind not in SPECIALIST_KINDS:
        return {"success": False, "message": f"未知 kind: {kind}（scene/person_event/violation）"}
    if not weights_path.is_file():
        return {"success": False, "message": "权重文件不存在"}

    dest_dir = specialist_dir(key, repo_root)
    dest_dir.mkdir(parents=True, exist_ok=True)
    suffix = weights_path.suffix.lower() or ".pt"
    if suffix not in (".pt", ".onnx"):
        suffix = ".pt"
    dest = dest_dir / f"model{suffix}"
    backup_path = None
    if backup and dest.is_file():
        backup_path = dest_dir / f"model.bak_{int(time.time())}{suffix}"
        shutil.copy2(dest, backup_path)
    shutil.copy2(weights_path, dest)

    rel = str(dest.relative_to(repo_root)).replace("\\", "/")
    cls_list = [str(c) for c in (classes or [])]

    # 尝试从权重读类别名
    if not cls_list:
        insp = inspect_yolo_weights(dest)
        if insp.get("success") and insp.get("classes"):
            cls_list = list(insp["classes"])

    raw = {
        "key": key,
        "kind": kind,
        "name_zh": (name_zh or key).strip(),
        "name_en": (name_en or name_zh or key).strip(),
        "model_path": rel,
        "classes": cls_list,
        "conf": conf if conf is not None else _default_conf(),
        "score_threshold": score_threshold if score_threshold is not None else _default_score(),
        "min_duration_sec": min_duration_sec
        if min_duration_sec is not None
        else _default_duration(),
        "max_persons": _default_max_persons(),
        "needs_persons": bool(needs_persons),
        "positive_class_ids": list(positive_class_ids)
        if positive_class_ids is not None
        else [0],
        "subject_class_ids": list(subject_class_ids) if subject_class_ids is not None else [0],
        "comply_class_ids": list(comply_class_ids) if comply_class_ids is not None else [1],
        "class_ids": list(class_ids) if class_ids is not None else None,
        "source_project_id": source_project_id,
        "test_metrics": test_metrics,
        "source": "specialist",
        "origin": _normalize_origin(origin),
    }
    meta = normalize_specialist_meta(raw, key=key)
    save_specialist_meta(meta, repo_root)

    # 旁路 classes.txt 便于人工核对
    try:
        cls_file = dest_dir / "classes.txt"
        with open(cls_file, "w", encoding="utf-8") as f:
            for i, name in enumerate(cls_list):
                f.write(f"{i}: {name}\n")
    except Exception:  # noqa: BLE001
        pass

    origin_zh = "导入" if meta.get("origin") == "imported" else "部署"
    return {
        "success": True,
        "message": (
            f"已{origin_zh}专模「{meta['name_zh']}」（键 {key}），"
            "可在检测类型配置中勾选；一般无需重启"
        ),
        "key": key,
        "meta": meta,
        "dest": str(dest.resolve()),
        "backup": str(backup_path.resolve()) if backup_path else None,
        "restart_required": False,
    }


def delete_specialist(key: str, repo_root: Optional[Path] = None) -> Dict[str, Any]:
    key = (key or "").strip()
    if not key or not is_valid_specialist_key(key):
        # 已存在目录时允许删除（即使键规则变严）
        d = specialist_dir(key, repo_root) if key else None
        if not d or not d.is_dir():
            return {"success": False, "message": "无效专模键名"}
    d = specialist_dir(key, repo_root)
    if not d.is_dir():
        return {"success": False, "message": f"专模不存在: {key}"}
    try:
        shutil.rmtree(d)
    except OSError as e:
        return {"success": False, "message": f"删除失败: {e}"}
    return {"success": True, "message": f"已删除专模 {key}", "key": key}


def scrub_detection_key_from_streams(key: str) -> int:
    """从 Redis 各流 detections 中移除指定键，返回修改的流数量。"""
    key = (key or "").strip()
    if not key:
        return 0
    try:
        from visionai.core.redis_manager import redis_manager
    except Exception:  # noqa: BLE001
        return 0
    if not redis_manager:
        return 0
    streams = redis_manager.get_streams() or []
    changed = 0
    for s in streams:
        dets = s.get("detections")
        if isinstance(dets, dict) and key in dets:
            dets = dict(dets)
            dets.pop(key, None)
            s["detections"] = dets
            changed += 1
    if changed:
        redis_manager.save_streams(streams)
    return changed


def specs_from_specialists(repo_root: Optional[Path] = None) -> List[Any]:
    """转为 SceneSpec / PersonEventSpec / ViolationSpec 列表。"""
    from visionai.core.behaviors.extensions import PersonEventSpec, SceneSpec, ViolationSpec

    specs: List[Any] = []
    for meta in list_specialists(repo_root):
        path = str(meta.get("model_path") or "").strip()
        if not path:
            continue
        kind = meta["kind"]
        key = meta["key"]
        conf = float(meta["conf"])
        min_d = float(meta["min_duration_sec"])
        score = float(meta["score_threshold"])
        max_p = int(meta["max_persons"])
        if kind == "scene":
            cids = meta.get("class_ids")
            specs.append(
                SceneSpec(
                    key=key,
                    model_path=path,
                    conf=conf,
                    min_duration_sec=min_d,
                    class_ids=tuple(cids) if cids else None,
                )
            )
        elif kind == "violation":
            specs.append(
                ViolationSpec(
                    key=key,
                    model_path=path,
                    conf=conf,
                    score_threshold=score,
                    min_duration_sec=min_d,
                    subject_class_ids=tuple(meta["subject_class_ids"]),
                    comply_class_ids=tuple(meta["comply_class_ids"]),
                    max_persons=max_p,
                )
            )
        else:
            specs.append(
                PersonEventSpec(
                    key=key,
                    model_path=path,
                    conf=conf,
                    score_threshold=score,
                    min_duration_sec=min_d,
                    positive_class_ids=tuple(meta["positive_class_ids"]),
                    max_persons=max_p,
                    needs_persons=bool(meta.get("needs_persons", True)),
                    log_scores=False,
                    log_label=meta.get("name_zh") or key,
                )
            )
    return specs
