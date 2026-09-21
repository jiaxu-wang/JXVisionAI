"""训练实验室：RTSP 截帧、浏览器标注、Ultralytics 训练、测试集门禁部署。

数据目录：<repo>/training_lab_data/projects/<project_id>/
  images/  labels/（已审核）  labels_draft/（预标注草稿）  meta.json
"""

from __future__ import annotations

import json
import logging
import os
import random
import re
import shutil
import subprocess
import sys
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from collections import deque

import cv2
from flask import Blueprint, Response, abort, jsonify, render_template, request, send_file, send_from_directory
from werkzeug.utils import secure_filename

from visionai.config.settings import SAVE_DIR, yolo_inference_device
from visionai.core.stream_frame import read_frame_bgr_prefer_snap
from visionai.utils.rtsp_url import normalize_rtsp_url
from visionai.web.training_lab_core import (
    DEPLOY_GATE,
    DEPLOY_TARGETS,
    TRAINING_TEMPLATES,
    approve_draft_labels,
    check_dataset_health,
    deploy_weights_to_production,
    deploy_as_specialist,
    detect_train_device,
    autolabel_images_with_weights,
    import_snapshots_to_project,
    list_draft_stems,
    list_labeled_stems,
    list_negative_stems,
    list_production_snapshots,
    list_reviewed_stems,
    materialize_yolo_split,
    prelabel_project_images,
    run_evaluate_subprocess,
    sample_label_status,
    suggest_thresholds_from_val,
)

logger = logging.getLogger(__name__)

training_bp = Blueprint(
    "training",
    __name__,
    template_folder="templates",
    static_folder="static",
)


def _repo_root() -> Path:
    # visionai/web/training_routes.py -> visionai -> repo
    return Path(__file__).resolve().parent.parent.parent


_DEFAULT_PRETRAINED = "yolo26s.pt"


def _resolve_pretrained_model(pretrained_model: str) -> tuple[str, Optional[str]]:
    """解析预训练权重。本地文件转成绝对路径（训练 cwd 在 training_system/）。

    专模 model.pt 未下载时回退 yolo26s.pt（Ultralytics 可按文件名自动拉取）。
    返回 (传给 train.py 的路径或文件名, 警告或 None)。
    """
    pre = (pretrained_model or "").strip() or _DEFAULT_PRETRAINED
    repo = _repo_root()
    p = Path(pre)
    if p.is_file():
        return str(p.resolve()), None
    if not p.is_absolute():
        cand = (repo / pre).resolve()
        if cand.is_file():
            return str(cand), None
        cand_models = (repo / "models" / p.name).resolve()
        if cand_models.is_file():
            return str(cand_models), None
    # 无目录的 *.pt：交给 Ultralytics 下载，不要当缺失专模路径
    norm = pre.replace("\\", "/")
    if "/" not in norm and pre.endswith(".pt"):
        return pre, None
    warn = f"预训练权重不存在: {pre}，改用 {_DEFAULT_PRETRAINED}"
    logger.warning(warn)
    return _DEFAULT_PRETRAINED, warn


def _projects_base() -> Path:
    p = _repo_root() / "training_lab_data" / "projects"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _jobs_base() -> Path:
    p = _repo_root() / "training_lab_data" / "_jobs"
    p.mkdir(parents=True, exist_ok=True)
    return p


_PID_RE = re.compile(r"^[a-f0-9]{12}$")
_TRAINING_IMG_EXT = {".jpg", ".jpeg", ".png"}


def _safe_image_basename(name: Optional[str]) -> Optional[str]:
    """训练集图片文件名：仅单层 basename，允许的扩展名。"""
    s = (name or "").strip()
    if not s or s != os.path.basename(s):
        return None
    if ".." in s or "/" in s or "\\" in s:
        return None
    suf = Path(s).suffix.lower()
    if suf not in _TRAINING_IMG_EXT:
        return None
    return s


def _project_dir_safe(pid: str) -> Optional[Path]:
    """训练项目目录（仅 `projects_base` 下的 12 位 hex），用于删除等操作。"""
    if not _PID_RE.match(pid or ""):
        return None
    p = (_projects_base() / pid).resolve()
    base = _projects_base().resolve()
    if p == base or not str(p).startswith(str(base) + os.sep):
        return None
    return p if p.is_dir() else None


def _pid_path(pid: str) -> Path:
    if not _PID_RE.match(pid or ""):
        abort(404)
    return _projects_base() / pid


def _project_dir_for_job(project_id: str) -> Optional[Path]:
    """供后台线程使用，不用 Flask abort。"""
    if not _PID_RE.match(project_id or ""):
        return None
    p = _projects_base() / project_id
    return p if p.is_dir() else None


def _read_meta(project_dir: Path) -> Dict[str, Any]:
    mp = project_dir / "meta.json"
    if not mp.is_file():
        return {}
    with open(mp, encoding="utf-8") as f:
        return json.load(f)


def _write_meta(project_dir: Path, meta: Dict[str, Any]) -> None:
    project_dir.mkdir(parents=True, exist_ok=True)
    with open(project_dir / "meta.json", "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)


def _allowed_rtsp(url: str) -> bool:
    u = (url or "").strip().lower()
    return u.startswith("rtsp://") or u.startswith("rtsps://")


# ---- 模型验证（推理日志、RTSP 定时、上传图） ----

_VALIDATE_LOG_MAX = 120
_validate_logs: Dict[str, deque] = {}
_validate_logs_lock = threading.Lock()
_validate_sessions_lock = threading.Lock()
_validate_sessions: Dict[str, Dict[str, Any]] = {}
_model_infer_lock = threading.Lock()
_model_cache: Dict[str, Any] = {}
_VALIDATE_SNAP_RE = re.compile(r"^v_\d+_[a-f0-9]{6}\.jpg$")
# 诊断用第二路推理置信度下限：用于在未达用户阈值时在日志中列出候选框及 conf
_VALIDATE_DIAGNOSTIC_CONF = 0.01  # 日志说明用；候选扫描置信度下限见 _VALIDATE_CANDIDATE_FLOOR
_VALIDATE_CANDIDATE_FLOOR = 0.001
_VALIDATE_CANDIDATES_MAX = 100


def _validate_snap_dir(project_dir: Path) -> Path:
    d = project_dir / "_validate" / "snap"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _validate_upload_dir(project_dir: Path) -> Path:
    d = project_dir / "_validate" / "upload"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _list_training_weights(project_dir: Path) -> List[Dict[str, Any]]:
    """扫描 `runs/<job_id>/yolo_outputs/web_train/weights/best.pt`。"""
    out: List[Dict[str, Any]] = []
    runs_dir = project_dir / "runs"
    if not runs_dir.is_dir():
        return out
    for job_dir in sorted(runs_dir.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True):
        if not job_dir.is_dir():
            continue
        wpath = job_dir / "yolo_outputs" / "web_train" / "weights" / "best.pt"
        if wpath.is_file():
            jid = job_dir.name
            rel = wpath.resolve()
            out.append(
                {
                    "job_id": jid[:16] if len(jid) > 16 else jid,
                    "path": str(rel),
                    "mtime": wpath.stat().st_mtime,
                    "label": f"job {jid[:8]}… → best.pt",
                }
            )
    jobs_base = _jobs_base()
    if jobs_base.is_dir():
        for jp in sorted(jobs_base.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
            try:
                doc = json.loads(jp.read_text(encoding="utf-8"))
            except Exception:  # noqa: BLE001
                continue
            if doc.get("status") != "completed":
                continue
            wp = doc.get("weights")
            if not wp or not Path(wp).is_file():
                continue
            pr = doc.get("project_id")
            if pr != project_dir.name:
                continue
            out.append(
                {
                    "job_id": jp.stem[:16],
                    "path": str(Path(wp).resolve()),
                    "mtime": Path(wp).stat().st_mtime,
                    "label": f"任务 {jp.stem[:8]}… → best.pt",
                }
            )
    seen = set()
    uniq: List[Dict[str, Any]] = []
    for item in out:
        p = item.get("path")
        if p in seen:
            continue
        seen.add(p)
        uniq.append(item)
    return uniq


def _resolve_weights_in_project(project_dir: Path, weights: str) -> Optional[Path]:
    """仅允许项目目录下的权重文件。"""
    w = (weights or "").strip()
    if not w:
        return None
    p = Path(w)
    if p.is_absolute():
        rp = p.resolve()
        pr = project_dir.resolve()
        if str(rp).startswith(str(pr) + os.sep) and rp.is_file() and rp.suffix.lower() == ".pt":
            return rp
        return None
    cand = (project_dir / w).resolve()
    if (
        str(cand).startswith(str(project_dir.resolve()) + os.sep)
        and cand.is_file()
        and cand.suffix.lower() == ".pt"
    ):
        return cand
    return None


def _parse_infer_device(raw: Optional[str]):
    if raw is None or str(raw).strip() == "":
        return yolo_inference_device()
    t = str(raw).strip()
    if t.lower() == "cpu":
        return "cpu"
    if t.isdigit():
        return int(t)
    return t


def _get_cached_yolo(weights_path: str):
    from ultralytics import YOLO  # noqa: WPS433

    with _model_infer_lock:
        m = _model_cache.get(weights_path)
        if m is None:
            m = YOLO(weights_path)
            if len(_model_cache) >= 4:
                try:
                    oldest = next(iter(_model_cache.keys()))
                    del _model_cache[oldest]
                except (StopIteration, KeyError):
                    pass
            _model_cache[weights_path] = m
        return m


def _parse_class_filter(raw) -> Optional[int]:
    """验证类别过滤：None=全部；整数=只看该类（如 0=no_glasses，1=glasses）。"""
    if raw is None:
        return None
    if isinstance(raw, bool):
        return None
    if isinstance(raw, (int, float)):
        return int(raw)
    s = str(raw).strip().lower()
    if not s or s in ("all", "none", "*", "全部"):
        return None
    try:
        return int(s)
    except ValueError:
        return None


def _draw_dets_on_frame(frame_bgr, dets: List[Dict[str, Any]]):
    """按过滤后的检测结果画框（类别过滤时不用 YOLO 默认 plot，避免混入其他类）。"""
    out = frame_bgr.copy()
    for d in dets:
        xy = d.get("xyxy") or []
        if len(xy) < 4:
            continue
        x1, y1, x2, y2 = int(xy[0]), int(xy[1]), int(xy[2]), int(xy[3])
        color = (34, 211, 238) if int(d.get("cls", 0)) == 0 else (251, 191, 36)
        cv2.rectangle(out, (x1, y1), (x2, y2), color, 2)
        label = f"{d.get('name', d.get('cls'))} {float(d.get('conf', 0)):.2f}"
        ty = max(18, y1 - 6)
        (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.55, 1)
        cv2.rectangle(out, (x1, ty - th - 6), (x1 + tw + 6, ty + 2), (0, 0, 0), -1)
        cv2.putText(
            out,
            label,
            (x1 + 3, ty - 2),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.55,
            (255, 255, 255),
            1,
            cv2.LINE_AA,
        )
    return out


def _validate_infer(
    weights_path: str,
    frame_bgr,
    device_arg,
    conf: float = 0.25,
    imgsz: int = 640,
    class_filter: Optional[int] = None,
) -> tuple:
    """两路推理：① 用户阈值——画框快照；② 低阈值——候选列表（含每条置信度写入日志）。

    仅极少数样本训练时，高 conf 常会「未检出」，但低阈值仍可看到模型是否在打低分框。
    class_filter 非空时只保留该类（便于单独核验 no_glasses / glasses）。
    """
    model = _get_cached_yolo(weights_path)
    kw_base: Dict[str, Any] = {"imgsz": int(imgsz), "verbose": False}
    dev = _parse_infer_device(device_arg)
    if dev is not None:
        kw_base["device"] = dev

    conf_user = float(max(0.05, min(conf, 0.999)))

    rh = model.predict(source=frame_bgr, **kw_base, conf=conf_user)[0]
    names = getattr(model, "names", {}) or {}

    dets: List[Dict[str, Any]] = []
    if rh.boxes is not None and len(rh.boxes):
        for box in rh.boxes:
            ci = int(box.cls[0])
            if class_filter is not None and ci != class_filter:
                continue
            cf = float(box.conf[0])
            xy = [float(x) for x in box.xyxy[0].tolist()]
            dets.append(
                {
                    "cls": ci,
                    "name": str(names.get(ci, ci)),
                    "conf": round(cf, 5),
                    "xyxy": xy,
                }
            )

    if class_filter is None:
        plot_bgr = rh.plot()
        if plot_bgr is None:
            plot_bgr = frame_bgr.copy()
    else:
        plot_bgr = _draw_dets_on_frame(frame_bgr, dets)

    # 第二路：固定极低下限，专门收集「未过用户阈值」的候选及置信度（供日志排查）
    lo_conf = max(0.001, float(_VALIDATE_CANDIDATE_FLOOR))
    rl = model.predict(
        source=frame_bgr,
        **kw_base,
        conf=lo_conf,
        max_det=_VALIDATE_CANDIDATES_MAX,
    )[0]
    candidates: List[Dict[str, Any]] = []
    if rl.boxes is not None and len(rl.boxes):
        for box in rl.boxes:
            ci = int(box.cls[0])
            if class_filter is not None and ci != class_filter:
                continue
            cf = float(box.conf[0])
            xy = [float(x) for x in box.xyxy[0].tolist()]
            candidates.append(
                {
                    "cls": ci,
                    "name": str(names.get(ci, ci)),
                    "conf": round(cf, 5),
                    "passed_user_threshold": bool(cf >= conf_user),
                    "xyxy": xy,
                }
            )
    candidates.sort(key=lambda x: (-float(x["conf"]), int(x["cls"])))

    return plot_bgr, dets, candidates


def _format_validate_infer_message(
    dets: List[Dict[str, Any]],
    candidates: List[Dict[str, Any]],
    conf_user: float,
    class_filter: Optional[int] = None,
) -> str:
    diag_floor = max(0.001, float(_VALIDATE_CANDIDATE_FLOOR))
    cls_note = f"，仅类别 {class_filter}" if class_filter is not None else ""
    if dets:
        parts = [
            f"{d.get('name', d.get('cls'))} conf={float(d.get('conf', 0)):.4f}"
            for d in dets
        ]
        return (
            "命中「显示阈值≥{:.4f}」{}：".format(conf_user, cls_note)
            + " | ".join(parts)
        )
    if candidates:
        top = candidates[:24]
        cstr = "; ".join(
            f"{c.get('name')} conf={float(c.get('conf', 0)):.4f}"
            + (" ✓" if c.get("passed_user_threshold") else "")
            for c in top
        )
        more = f" （共 {len(candidates)} 框，至多展示 24）" if len(candidates) > 24 else ""
        return (
            f"未达到显示阈值（≥{conf_user:.4f}）{cls_note}。"
            f"候选扫描（conf≥{diag_floor:.4f}）： "
            + cstr
            + more
        )
    return (
        f"未达到显示阈值（≥{conf_user:.4f}）{cls_note}；候选扫描 conf≥{diag_floor:.4f} 仍无框。"
        "可尝试降低验证置信度，或继续增加标注样本与训练轮数。"
    )


def _format_det_lines(dets: List[Dict[str, Any]]) -> str:
    if not dets:
        return "未检出目标"
    parts = [f"{d.get('name', d.get('cls'))} {d.get('conf', 0):.2f}" for d in dets]
    return " | ".join(parts)


def _validate_save_snap(project_dir: Path, plot_bgr) -> str:
    d = _validate_snap_dir(project_dir)
    files = sorted(d.glob("v_*.jpg"), key=lambda p: p.stat().st_mtime)
    while len(files) >= 100:
        try:
            files[0].unlink()
            files.pop(0)
        except OSError:
            break
    name = f"v_{int(time.time())}_{uuid.uuid4().hex[:6]}.jpg"
    path = d / name
    cv2.imwrite(str(path), plot_bgr)
    return name


def _validate_append_log(project_id: str, entry: Dict[str, Any]) -> None:
    entry["ts"] = time.time()
    entry.setdefault("kind", "infer")
    with _validate_logs_lock:
        if project_id not in _validate_logs:
            _validate_logs[project_id] = deque(maxlen=_VALIDATE_LOG_MAX)
        _validate_logs[project_id].append(entry)


def _validate_stop_session(project_id: str) -> None:
    with _validate_sessions_lock:
        sess = _validate_sessions.pop(project_id, None)
    if not sess:
        return
    ev: threading.Event = sess["stop"]
    th: threading.Thread = sess.get("thread")
    ev.set()
    if th and th.is_alive():
        th.join(timeout=5.0)


def _validate_rtsp_worker(
    project_id: str,
    weights_path: str,
    rtsp_url: str,
    interval_sec: float,
    stop_ev: threading.Event,
    device_arg,
    conf: float,
    imgsz: int,
    class_filter: Optional[int] = None,
) -> None:
    project_dir = _project_dir_for_job(project_id)
    if project_dir is None:
        return
    u = normalize_rtsp_url((rtsp_url or "").strip())
    while not stop_ev.is_set():
        if not _allowed_rtsp(u):
            _validate_append_log(
                project_id,
                {"kind": "error", "message": "无效的 RTSP 地址", "snapshot": None, "detections": []},
            )
        else:
            frame = read_frame_bgr_prefer_snap(u, timeout_sec=12.0)
            if frame is None:
                _validate_append_log(
                    project_id,
                    {
                        "kind": "error",
                        "message": "拉流截帧失败",
                        "snapshot": None,
                        "detections": [],
                    },
                )
            else:
                try:
                    plot_bgr, dets, candidates = _validate_infer(
                        weights_path,
                        frame,
                        device_arg,
                        conf=conf,
                        imgsz=imgsz,
                        class_filter=class_filter,
                    )
                    snap = _validate_save_snap(project_dir, plot_bgr)
                    msg = _format_validate_infer_message(
                        dets, candidates, float(conf), class_filter=class_filter
                    )
                    _validate_append_log(
                        project_id,
                        {
                            "kind": "infer",
                            "message": msg,
                            "detections": dets,
                            "candidates": candidates,
                            "conf_threshold": float(conf),
                            "candidate_conf_floor": float(_VALIDATE_CANDIDATE_FLOOR),
                            "class_filter": class_filter,
                            "snapshot": snap,
                            "source": "rtsp",
                        },
                    )
                except Exception as ex:  # noqa: BLE001
                    logger.exception("验证推理失败")
                    _validate_append_log(
                        project_id,
                        {
                            "kind": "error",
                            "message": str(ex),
                            "snapshot": None,
                            "detections": [],
                        },
                    )
        if stop_ev.wait(timeout=max(0.5, float(interval_sec))):
            break


def _run_training_job(
    *,
    job_id: str,
    project_id: str,
    epochs: int,
    batch_size: int,
    img_size: int,
    device: str,
    pretrained_model: str,
) -> None:
    jobs_dir = _jobs_base()
    job_path = jobs_dir / f"{job_id}.json"
    project_dir = _project_dir_for_job(project_id)
    if project_dir is None:
        with open(job_path, "w", encoding="utf-8") as f:
            json.dump(
                {"status": "failed", "error": "项目不存在或 ID 无效", "project_id": project_id},
                f,
                ensure_ascii=False,
                indent=2,
            )
        return
    run_root = project_dir / "runs" / job_id
    run_root.mkdir(parents=True, exist_ok=True)
    log_fp = run_root / "train.log"

    train_py = _repo_root() / "training_system" / "scripts" / "train.py"
    if not train_py.is_file():
        with open(job_path, "w", encoding="utf-8") as f:
            json.dump(
                {"status": "failed", "error": "training_system/scripts/train.py 不存在", "project_id": project_id},
                f,
                ensure_ascii=False,
                indent=2,
            )
        return

    try:
        _meta = _read_meta(project_dir)
        yaml_path = materialize_yolo_split(
            project_dir, _meta, calib=bool(_meta.get("calib_specialist_key"))
        )
    except ValueError as e:
        with open(job_path, "w", encoding="utf-8") as f:
            json.dump(
                {"status": "failed", "error": str(e), "project_id": project_id},
                f,
                ensure_ascii=False,
                indent=2,
            )
        return

    out_base = run_root / "yolo_outputs"
    out_base.mkdir(parents=True, exist_ok=True)

    pre, pre_warn = _resolve_pretrained_model(pretrained_model)

    cmd = [
        sys.executable,
        str(train_py),
        "--data_yaml",
        str(yaml_path.resolve()),
        "--pretrained_model",
        pre,
        "--epochs",
        str(epochs),
        "--batch_size",
        str(batch_size),
        "--img_size",
        str(img_size),
        "--device",
        device.strip() or "cpu",
        "--workers",
        "2",
        "--project_dir",
        str(out_base.resolve()),
        "--experiment_name",
        "web_train",
        "--cos_lr",
    ]

    with open(log_fp, "a", encoding="utf-8") as logf:
        if pre_warn:
            logf.write(f"# {pre_warn}\n")
        logf.write(f"$ {' '.join(cmd)}\n")
        logf.flush()
        proc = subprocess.Popen(
            cmd,
            cwd=str(_repo_root() / "training_system"),
            stdout=logf,
            stderr=subprocess.STDOUT,
            env={**os.environ},
        )
        rc = proc.wait()

    weights = out_base / "web_train" / "weights" / "best.pt"
    status = "completed" if rc == 0 and weights.is_file() else "failed"
    payload: Dict[str, Any] = {
        "status": status,
        "returncode": rc,
        "project_id": project_id,
        "log": str(log_fp.resolve()),
        "weights": str(weights.resolve()) if weights.is_file() else None,
        "finished_at": time.time(),
        "evaluation": None,
        "test_evaluation": None,
        "deploy_ready": False,
    }
    if status == "completed" and weights.is_file():
        dev = device.strip() or detect_train_device()
        val_metrics = run_evaluate_subprocess(
            _repo_root(),
            model_path=str(weights.resolve()),
            data_yaml=str(yaml_path.resolve()),
            device=dev,
            split="val",
            log_fp=log_fp,
        )
        test_metrics = run_evaluate_subprocess(
            _repo_root(),
            model_path=str(weights.resolve()),
            data_yaml=str(yaml_path.resolve()),
            device=dev,
            split="test",
            log_fp=log_fp,
        )
        payload["evaluation"] = val_metrics
        payload["test_evaluation"] = test_metrics
        if val_metrics.get("ok"):
            payload["map50"] = val_metrics.get("map50")
            payload["precision"] = val_metrics.get("precision")
            payload["recall"] = val_metrics.get("recall")
        if test_metrics.get("ok"):
            payload["test_map50"] = test_metrics.get("map50")
            payload["test_precision"] = test_metrics.get("precision")
            payload["test_recall"] = test_metrics.get("recall")
            from visionai.web.training_lab_core import check_deploy_quality_gate

            ok, errs = check_deploy_quality_gate(test_metrics)
            payload["deploy_ready"] = ok
            payload["deploy_gate_errors"] = errs
            payload["deploy_gate"] = dict(DEPLOY_GATE)
        else:
            payload["deploy_ready"] = False
            payload["deploy_gate_errors"] = [
                test_metrics.get("error") or "测试集评估失败"
            ]
    with open(job_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)


@training_bp.route("/training")
def training_lab_page():
    from flask import redirect, session, url_for

    if "logged_in" not in session or not session["logged_in"]:
        return redirect(url_for("login"))
    return render_template("training_lab.html")


def _register_api_routes(app):
    """在 app 上注册需共享 login_required 的 API（与主 app 同一 session）。"""
    from visionai.web.app import login_required
    from visionai.core.redis_manager import redis_manager

    @app.route("/api/training/redis-streams", methods=["GET"])
    @login_required
    def training_redis_streams():
        if not redis_manager or not redis_manager.is_connected():
            return jsonify([])
        streams = redis_manager.get_streams()
        out = []
        for s in streams:
            out.append(
                {
                    "id": s.get("id"),
                    "name": s.get("name"),
                    "rtsp_url": (s.get("rtsp_url") or s.get("url") or "").strip(),
                }
            )
        return jsonify(out)

    @app.route("/api/training/rtsp-preview", methods=["GET"])
    @login_required
    def training_rtsp_preview():
        url = request.args.get("url", "").strip()
        if not _allowed_rtsp(url):
            return jsonify({"success": False, "message": "仅支持 rtsp:// 或 rtsps://"}), 400
        frame = read_frame_bgr_prefer_snap(url)
        if frame is None:
            return jsonify({"success": False, "message": "无法读取帧，请检查地址与网络"}), 400
        ok, buf = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), 85])
        if not ok:
            return jsonify({"success": False, "message": "编码失败"}), 500
        resp = Response(buf.tobytes(), mimetype="image/jpeg")
        resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        resp.headers["Pragma"] = "no-cache"
        resp.headers["Expires"] = "0"
        return resp

    @app.route("/api/training/templates", methods=["GET"])
    @login_required
    def training_templates_list():
        items = []
        for tid, tpl in TRAINING_TEMPLATES.items():
            items.append(
                {
                    "id": tid,
                    "title": tpl.get("title"),
                    "title_en": tpl.get("title_en") or tpl.get("title"),
                    "description": tpl.get("description"),
                    "description_en": tpl.get("description_en") or tpl.get("description"),
                    "classes": tpl.get("classes") or [],
                    "deploy_target": tpl.get("deploy_target"),
                    "deploy_mode": tpl.get("deploy_mode"),
                    "specialist_defaults": tpl.get("specialist_defaults"),
                    "defaults": {
                        "epochs": tpl.get("default_epochs"),
                        "batch": tpl.get("default_batch"),
                        "imgsz": tpl.get("default_imgsz"),
                        "pretrained": tpl.get("default_pretrained"),
                    },
                    "recommended_labeled": tpl.get("recommended_labeled"),
                }
            )
        return jsonify(items)

    @app.route("/api/training/deploy-targets", methods=["GET"])
    @login_required
    def training_deploy_targets():
        return jsonify(
            {
                k: {
                    "model_filename": v.get("model_filename"),
                    "config_keys": list((v.get("config_updates") or {}).keys()),
                }
                for k, v in DEPLOY_TARGETS.items()
            }
        )

    @app.route("/api/training/projects", methods=["GET"])
    @login_required
    def training_projects_list():
        base = _projects_base()
        items = []
        for d in sorted(base.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True):
            if not d.is_dir() or not _PID_RE.match(d.name):
                continue
            meta = _read_meta(d)
            health = check_dataset_health(d, meta)
            items.append(
                {
                    "id": d.name,
                    "title": meta.get("title", d.name),
                    "classes": meta.get("classes", []),
                    "template_id": meta.get("template_id"),
                    "deploy_target": meta.get("deploy_target"),
                    "deploy_mode": meta.get("deploy_mode"),
                    "calib_specialist_key": meta.get("calib_specialist_key"),
                    "created_at": meta.get("created_at"),
                    "image_count": len(list((d / "images").glob("*"))) if (d / "images").is_dir() else 0,
                    "labeled_count": health.labeled_images,
                    "draft_count": health.draft_images,
                    "can_train": health.can_train,
                }
            )
        return jsonify(items)

    @app.route("/api/training/projects", methods=["POST"])
    @login_required
    def training_projects_create():
        data = request.get_json(silent=True) or {}
        template_id = (data.get("template_id") or "custom").strip()
        tpl = TRAINING_TEMPLATES.get(template_id, TRAINING_TEMPLATES["custom"])

        title = (data.get("title") or "").strip() or tpl.get("title") or "未命名训练"
        raw_classes = data.get("classes")
        if isinstance(raw_classes, str) and raw_classes.strip():
            classes = [c.strip() for c in raw_classes.replace("，", ",").split(",") if c.strip()]
        elif isinstance(raw_classes, list) and raw_classes:
            classes = [str(c).strip() for c in raw_classes if str(c).strip()]
        else:
            classes = list(tpl.get("classes") or [])
        if not classes:
            return jsonify({"success": False, "message": "至少填写一个类别或选择有效场景模板"}), 400

        pid = uuid.uuid4().hex[:12]
        pdir = _projects_base() / pid
        (pdir / "images").mkdir(parents=True)
        (pdir / "labels").mkdir(parents=True)
        (pdir / "labels_draft").mkdir(parents=True)
        calib_key = (data.get("calib_specialist_key") or "").strip()
        meta = {
            "title": title,
            "classes": classes,
            "template_id": template_id,
            "deploy_target": tpl.get("deploy_target"),
            "deploy_mode": tpl.get("deploy_mode"),
            "calib_specialist_key": calib_key if re.match(r"^[a-z][a-z0-9_]*$", calib_key) else None,
            "created_at": time.time(),
            "train_defaults": {
                "epochs": tpl.get("default_epochs"),
                "batch": tpl.get("default_batch"),
                "imgsz": tpl.get("default_imgsz"),
                "pretrained": tpl.get("default_pretrained"),
            },
        }
        _write_meta(pdir, meta)
        return jsonify({"success": True, "project": {"id": pid, **meta}})

    @app.route("/api/training/projects/<pid>/dataset-health", methods=["GET"])
    @login_required
    def training_dataset_health(pid):
        project_dir = _pid_path(pid)
        meta = _read_meta(project_dir)
        health = check_dataset_health(project_dir, meta)
        out = health.to_dict()
        out["calib_specialist_key"] = meta.get("calib_specialist_key")
        out["negative_count"] = len(list_negative_stems(project_dir))
        return jsonify(out)

    @app.route("/api/training/projects/<pid>", methods=["DELETE"])
    @login_required
    def training_projects_delete(pid):
        pdir = _project_dir_safe(pid)
        if pdir is None:
            return jsonify({"success": False, "message": "项目不存在"}), 404
        try:
            shutil.rmtree(pdir)
        except OSError as e:
            logger.warning("删除训练项目失败: %s", e)
            return jsonify({"success": False, "message": str(e)}), 500
        _validate_stop_session(pid)
        with _validate_logs_lock:
            _validate_logs.pop(pid, None)
        return jsonify({"success": True})

    @app.route("/api/training/projects/<pid>/capture", methods=["POST"])
    @login_required
    def training_capture(pid):
        project_dir = _pid_path(pid)
        data = request.get_json(silent=True) or {}
        url = (data.get("rtsp_url") or "").strip()
        if not _allowed_rtsp(url):
            return jsonify({"success": False, "message": "需要有效的 rtsp:// 或 rtsps:// 地址"}), 400
        frame = read_frame_bgr_prefer_snap(url)
        if frame is None:
            return jsonify({"success": False, "message": "截帧失败"}), 400
        name = f"cap_{int(time.time())}_{uuid.uuid4().hex[:6]}.jpg"
        ipath = project_dir / "images" / name
        if not cv2.imwrite(str(ipath), frame):
            return jsonify({"success": False, "message": "保存图片失败"}), 500
        return jsonify({"success": True, "filename": name})

    @app.route("/api/training/projects/<pid>/samples", methods=["GET"])
    @login_required
    def training_samples(pid):
        project_dir = _pid_path(pid)
        img_dir = project_dir / "images"
        if not img_dir.is_dir():
            return jsonify([])
        out = []
        for p in sorted(img_dir.iterdir(), key=lambda x: x.name):
            if p.suffix.lower() not in (".jpg", ".jpeg", ".png"):
                continue
            status = sample_label_status(project_dir, p.stem)
            out.append(
                {
                    "filename": p.name,
                    "labeled": status == "reviewed",
                    "status": status,
                    "draft": status == "draft",
                }
            )
        return jsonify(out)

    @app.route("/api/training/projects/<pid>/samples", methods=["DELETE"])
    @login_required
    def training_delete_sample(pid):
        project_dir = _pid_path(pid)
        data = request.get_json(silent=True) or {}
        fn = _safe_image_basename(data.get("filename"))
        if not fn:
            return jsonify({"success": False, "message": "无效文件名"}), 400
        img_path = (project_dir / "images" / fn).resolve()
        images_root = (project_dir / "images").resolve()
        if not str(img_path).startswith(str(images_root) + os.sep):
            return jsonify({"success": False, "message": "路径无效"}), 400
        if not img_path.is_file():
            return jsonify({"success": False, "message": "文件不存在"}), 404
        stem = img_path.stem
        lbl_path = (project_dir / "labels" / f"{stem}.txt").resolve()
        draft_path = (project_dir / "labels_draft" / f"{stem}.txt").resolve()
        labels_root = (project_dir / "labels").resolve()
        draft_root = (project_dir / "labels_draft").resolve()
        try:
            img_path.unlink()
            if str(lbl_path).startswith(str(labels_root) + os.sep) and lbl_path.is_file():
                lbl_path.unlink()
            if draft_root.is_dir() and str(draft_path).startswith(str(draft_root) + os.sep) and draft_path.is_file():
                draft_path.unlink()
        except OSError as e:
            logger.warning("删除训练样本失败: %s", e)
            return jsonify({"success": False, "message": str(e)}), 500
        return jsonify({"success": True})

    @app.route("/api/training/projects/<pid>/image/<path:filename>", methods=["GET"])
    @login_required
    def training_serve_image(pid, filename):
        project_dir = _pid_path(pid)
        return send_from_directory(project_dir / "images", filename, max_age=0)

    @app.route("/api/training/projects/<pid>/labels/<path:filename>", methods=["GET"])
    @login_required
    def training_get_label(pid, filename):
        project_dir = _pid_path(pid)
        # 优先正式标注；无则回退草稿（便于审核编辑）
        for sub in ("labels", "labels_draft"):
            fp = (project_dir / sub / filename).resolve()
            root = (project_dir / sub).resolve()
            if not str(fp).startswith(str(root) + os.sep):
                continue
            if fp.is_file():
                return send_from_directory(project_dir / sub, filename, mimetype="text/plain", max_age=0)
        return Response("", mimetype="text/plain")

    @app.route("/api/training/projects/<pid>/labels/approve", methods=["POST"])
    @login_required
    def training_approve_labels(pid):
        project_dir = _pid_path(pid)
        data = request.get_json(silent=True) or {}
        approve_all = bool(data.get("all"))
        stems = data.get("stems") or []
        if not approve_all and not stems:
            # 单张：由 image 文件名推导
            image = _safe_image_basename(data.get("image") or data.get("filename"))
            if image:
                stems = [Path(image).stem]
        if not approve_all and not stems:
            return jsonify({"success": False, "message": "请提供 stems 或 image，或 all=true"}), 400
        result = approve_draft_labels(project_dir, stems=stems, approve_all=approve_all)
        return jsonify(result)

    @app.route("/api/training/projects/<pid>/labels", methods=["POST"])
    @login_required
    def training_save_label(pid):
        project_dir = _pid_path(pid)
        meta = _read_meta(project_dir)
        n_class = len(meta.get("classes") or [])
        if n_class < 1:
            return jsonify({"success": False, "message": "项目类别无效"}), 400

        data = request.get_json(silent=True) or {}
        image = _safe_image_basename(data.get("image"))
        boxes = data.get("boxes")
        if not image:
            return jsonify({"success": False, "message": "无效图片名"}), 400
        img_path = project_dir / "images" / image
        if not img_path.is_file():
            return jsonify({"success": False, "message": "图片不存在"}), 404

        lines: List[str] = []
        if isinstance(boxes, list):
            for b in boxes:
                try:
                    ci = int(b.get("class_index"))
                    cx = float(b.get("cx"))
                    cy = float(b.get("cy"))
                    w = float(b.get("w"))
                    h = float(b.get("h"))
                except (TypeError, ValueError):
                    continue
                if not (0 <= ci < n_class):
                    continue
                cx = min(1.0, max(0.0, cx))
                cy = min(1.0, max(0.0, cy))
                w = min(1.0, max(0.0, w))
                h = min(1.0, max(0.0, h))
                lines.append(f"{ci} {cx:.6f} {cy:.6f} {w:.6f} {h:.6f}")

        lbl_dir = project_dir / "labels"
        lbl_dir.mkdir(exist_ok=True)
        stem = Path(image).stem
        lf = lbl_dir / f"{stem}.txt"
        lf.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
        # 人工保存即视为审核通过：清理同名草稿
        draft = project_dir / "labels_draft" / f"{stem}.txt"
        if draft.is_file():
            try:
                draft.unlink()
            except OSError:
                pass
        return jsonify({"success": True, "lines": len(lines), "status": "reviewed"})

    @app.route("/api/training/projects/<pid>/train", methods=["POST"])
    @login_required
    def training_start_train(pid):
        project_dir = _pid_path(pid)
        meta = _read_meta(project_dir)
        data = request.get_json(silent=True) or {}
        force = bool(data.get("force"))

        health = check_dataset_health(project_dir, meta)
        is_calib_project = bool(meta.get("calib_specialist_key"))
        if is_calib_project and not health.can_train:
            # 校准项目（微调已部署专模）：小样本即可开训，仅需已审核准确样本达标
            from visionai.web.training_lab_core import CALIB_MIN_REVIEWED

            if health.labeled_images >= CALIB_MIN_REVIEWED:
                health.can_train = True
                health.errors = [
                    e
                    for e in (health.errors or [])
                    if "开训下限" not in e and "训练集预估" not in e
                    and "验证集预估" not in e and "测试集预估" not in e
                ]
        if not health.can_train and not force:
            msg = "未达开训门槛"
            if is_calib_project:
                from visionai.web.training_lab_core import CALIB_MIN_REVIEWED

                msg += f"（校准项目需已审核准确样本 ≥ {CALIB_MIN_REVIEWED} 张）"
            return jsonify(
                {
                    "success": False,
                    "message": msg,
                    "health": health.to_dict(),
                }
            ), 400

        defaults = meta.get("train_defaults") or {}
        epochs = int(data.get("epochs") or defaults.get("epochs") or 30)
        batch_size = int(data.get("batch_size") or defaults.get("batch") or 8)
        img_size = int(data.get("img_size") or defaults.get("imgsz") or 640)
        device = str(data.get("device") or detect_train_device()).strip()
        pretrained = str(
            data.get("pretrained_model") or defaults.get("pretrained") or "yolo26s.pt"
        ).strip()

        epochs = max(1, min(epochs, 500))
        batch_size = max(1, min(batch_size, 128))
        img_size = max(320, min(img_size, 1280))

        # 生产级：禁止强制绕过开训门槛（调试可设环境变量 TRAINING_LAB_ALLOW_FORCE=1）
        if force and os.environ.get("TRAINING_LAB_ALLOW_FORCE", "0") != "1":
            return jsonify(
                {
                    "success": False,
                    "message": "已禁用强制开训。请补齐已审核样本后再训，或设置 TRAINING_LAB_ALLOW_FORCE=1（仅调试）",
                    "health": health.to_dict(),
                }
            ), 400

        job_id = uuid.uuid4().hex[:16]
        job_path = _jobs_base() / f"{job_id}.json"
        with open(job_path, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "status": "running",
                    "project_id": pid,
                    "started_at": time.time(),
                    "log": str((_pid_path(pid) / "runs" / job_id / "train.log").resolve()),
                },
                f,
                ensure_ascii=False,
                indent=2,
            )

        th = threading.Thread(
            target=_run_training_job,
            kwargs={
                "job_id": job_id,
                "project_id": pid,
                "epochs": epochs,
                "batch_size": batch_size,
                "img_size": img_size,
                "device": device,
                "pretrained_model": pretrained,
            },
            daemon=True,
        )
        th.start()
        return jsonify({"success": True, "job_id": job_id})

    @app.route("/api/training/jobs/<job_id>", methods=["GET"])
    @login_required
    def training_job_status(job_id):
        if not re.match(r"^[a-f0-9]{16}$", job_id or ""):
            abort(404)
        jp = _jobs_base() / f"{job_id}.json"
        if not jp.is_file():
            return jsonify({"status": "unknown", "message": "任务不存在"}), 404
        with open(jp, encoding="utf-8") as f:
            return jsonify(json.load(f))

    @app.route("/api/training/jobs/<job_id>/log", methods=["GET"])
    @login_required
    def training_job_log(job_id):
        if not re.match(r"^[a-f0-9]{16}$", job_id or ""):
            abort(404)
        jp = _jobs_base() / f"{job_id}.json"
        if not jp.is_file():
            abort(404)
        with open(jp, encoding="utf-8") as f:
            doc = json.load(f)
        log_p = doc.get("log")
        if not log_p or not Path(log_p).is_file():
            return Response("(尚无日志)\n", mimetype="text/plain; charset=utf-8")
        return send_from_directory(Path(log_p).parent, Path(log_p).name, mimetype="text/plain; charset=utf-8")

    @app.route("/api/training/jobs/<job_id>/weights", methods=["GET"])
    @login_required
    def training_job_weights(job_id):
        if not re.match(r"^[a-f0-9]{16}$", job_id or ""):
            abort(404)
        jp = _jobs_base() / f"{job_id}.json"
        if not jp.is_file():
            abort(404)
        with open(jp, encoding="utf-8") as f:
            doc = json.load(f)
        w = doc.get("weights")
        if not w or not Path(w).is_file():
            abort(404)
        return send_from_directory(Path(w).parent, Path(w).name, as_attachment=True, download_name="best.pt")

    @app.route("/api/training/projects/<pid>/weights", methods=["GET"])
    @login_required
    def training_list_weights(pid):
        project_dir = _pid_path(pid)
        return jsonify(_list_training_weights(project_dir))

    @app.route("/api/training/projects/<pid>/validate/upload", methods=["POST"])
    @login_required
    def training_validate_upload(pid):
        project_dir = _pid_path(pid)
        if "file" not in request.files:
            return jsonify({"success": False, "message": "缺少 file 字段"}), 400
        f = request.files["file"]
        if not f or not f.filename:
            return jsonify({"success": False, "message": "未选择文件"}), 400
        base = secure_filename(f.filename) or "image.jpg"
        ext = Path(base).suffix.lower()
        if ext not in _TRAINING_IMG_EXT:
            return jsonify({"success": False, "message": "仅支持 jpg / jpeg / png"}), 400
        uniq = f"up_{int(time.time())}_{uuid.uuid4().hex[:6]}{ext}"
        dest = _validate_upload_dir(project_dir) / uniq
        f.save(str(dest))
        return jsonify({"success": True, "filename": uniq})

    @app.route("/api/training/projects/<pid>/validate/run-once", methods=["POST"])
    @login_required
    def training_validate_run_once(pid):
        project_dir = _pid_path(pid)
        data = request.get_json(silent=True) or {}
        wkey = (data.get("weights_path") or data.get("weights") or "").strip()
        wp = _resolve_weights_in_project(project_dir, wkey)
        if wp is None:
            return jsonify({"success": False, "message": "无效权重路径（须为本项目下已训练的 .pt）"}), 400
        source = (data.get("source") or "").strip().lower()
        device_arg = data.get("device")
        conf = float(data.get("conf") or 0.25)
        imgsz = int(data.get("imgsz") or 640)
        conf = max(0.05, min(conf, 0.99))
        imgsz = max(320, min(imgsz, 1280))
        class_filter = _parse_class_filter(
            data.get("class_filter") if "class_filter" in data else data.get("class_index")
        )

        frame = None
        src_label = ""
        if source == "upload":
            fn = data.get("filename") or ""
            fn = Path(fn).name
            if ".." in fn or "/" in fn or "\\" in fn:
                return jsonify({"success": False, "message": "无效文件名"}), 400
            if Path(fn).suffix.lower() not in _TRAINING_IMG_EXT:
                return jsonify({"success": False, "message": "仅支持图像文件"}), 400
            ip = (_validate_upload_dir(project_dir) / fn).resolve()
            ud = _validate_upload_dir(project_dir).resolve()
            if not str(ip).startswith(str(ud) + os.sep) or not ip.is_file():
                return jsonify({"success": False, "message": "上传文件不存在"}), 404
            frame = cv2.imread(str(ip))
            src_label = "upload:" + fn
        elif source == "rtsp":
            url = (data.get("rtsp_url") or "").strip()
            if not _allowed_rtsp(url):
                return jsonify({"success": False, "message": "无效 RTSP 地址"}), 400
            frame = read_frame_bgr_prefer_snap(url)
            src_label = "rtsp"
        else:
            return jsonify({"success": False, "message": "source 须为 upload 或 rtsp"}), 400

        if frame is None:
            msg = "无法读取图像" if source == "upload" else "RTSP 截帧失败"
            _validate_append_log(
                pid,
                {"kind": "error", "message": msg, "detections": [], "snapshot": None, "source": source},
            )
            return jsonify({"success": False, "message": msg}), 400

        try:
            plot_bgr, dets, candidates = _validate_infer(
                str(wp),
                frame,
                device_arg,
                conf=conf,
                imgsz=imgsz,
                class_filter=class_filter,
            )
            snap = _validate_save_snap(project_dir, plot_bgr)
            msg = _format_validate_infer_message(
                dets, candidates, float(conf), class_filter=class_filter
            )
            _validate_append_log(
                pid,
                {
                    "kind": "infer",
                    "message": msg,
                    "detections": dets,
                    "candidates": candidates,
                    "conf_threshold": float(conf),
                    "candidate_conf_floor": float(_VALIDATE_CANDIDATE_FLOOR),
                    "class_filter": class_filter,
                    "snapshot": snap,
                    "source": src_label,
                },
            )
        except Exception as ex:  # noqa: BLE001
            logger.exception("单次验证推理失败")
            _validate_append_log(
                pid,
                {"kind": "error", "message": str(ex), "detections": [], "snapshot": None},
            )
            return jsonify({"success": False, "message": str(ex)}), 500

        return jsonify(
            {
                "success": True,
                "detections": dets,
                "candidates": candidates,
                "conf_threshold": float(conf),
                "candidate_conf_floor": float(_VALIDATE_CANDIDATE_FLOOR),
                "class_filter": class_filter,
                "snapshot": snap,
                "summary": msg,
            }
        )

    @app.route("/api/training/projects/<pid>/validate/start", methods=["POST"])
    @login_required
    def training_validate_start(pid):
        project_dir = _pid_path(pid)
        data = request.get_json(silent=True) or {}
        wkey = (data.get("weights_path") or data.get("weights") or "").strip()
        wp = _resolve_weights_in_project(project_dir, wkey)
        if wp is None:
            return jsonify({"success": False, "message": "无效权重路径"}), 400
        rtsp = (data.get("rtsp_url") or "").strip()
        if not _allowed_rtsp(rtsp):
            return jsonify({"success": False, "message": "需要有效 RTSP 地址"}), 400
        interval = float(data.get("interval_sec") or 5)
        interval = max(1.0, min(interval, 120.0))
        conf = float(data.get("conf") or 0.25)
        conf = max(0.05, min(conf, 0.99))
        imgsz = max(320, min(int(data.get("imgsz") or 640), 1280))
        class_filter = _parse_class_filter(
            data.get("class_filter") if "class_filter" in data else data.get("class_index")
        )

        _validate_stop_session(pid)
        stop_ev = threading.Event()
        th = threading.Thread(
            target=_validate_rtsp_worker,
            args=(
                pid,
                str(wp.resolve()),
                rtsp,
                interval,
                stop_ev,
                data.get("device"),
                conf,
                imgsz,
                class_filter,
            ),
            daemon=True,
        )
        with _validate_sessions_lock:
            _validate_sessions[pid] = {"stop": stop_ev, "thread": th}
        th.start()
        cls_tip = f"，仅类别 {class_filter}" if class_filter is not None else ""
        _validate_append_log(
            pid,
            {
                "kind": "info",
                "message": f"已开启 RTSP 循环验证，间隔 {interval:g}s{cls_tip}",
                "detections": [],
                "snapshot": None,
                "source": "rtsp_loop",
                "class_filter": class_filter,
            },
        )
        return jsonify({"success": True, "interval_sec": interval, "class_filter": class_filter})

    @app.route("/api/training/projects/<pid>/validate/stop", methods=["POST"])
    @login_required
    def training_validate_stop(pid):
        _pid_path(pid)
        _validate_stop_session(pid)
        _validate_append_log(
            pid,
            {
                "kind": "info",
                "message": "已停止 RTSP 循环验证",
                "detections": [],
                "snapshot": None,
            },
        )
        return jsonify({"success": True})

    @app.route("/api/training/projects/<pid>/validate/status", methods=["GET"])
    @login_required
    def training_validate_status(pid):
        _pid_path(pid)
        with _validate_sessions_lock:
            running = pid in _validate_sessions
        return jsonify({"running": running})

    @app.route("/api/training/projects/<pid>/validate/logs", methods=["GET"])
    @login_required
    def training_validate_logs(pid):
        _pid_path(pid)
        try:
            limit = int(request.args.get("limit", "60"))
        except ValueError:
            limit = 60
        limit = min(100, max(1, limit))
        with _validate_logs_lock:
            dq = _validate_logs.get(pid)
            items = list(dq)[-limit:] if dq else []
        out: List[Dict[str, Any]] = []
        for e in reversed(items):
            ee = dict(e)
            try:
                ee["ts_iso"] = datetime.fromtimestamp(float(ee.get("ts", 0))).strftime(
                    "%Y-%m-%d %H:%M:%S"
                )
            except (TypeError, ValueError, OSError):
                ee["ts_iso"] = ""
            out.append(ee)
        return jsonify(out)

    @app.route("/api/training/projects/<pid>/validate/snap/<filename>", methods=["GET"])
    @login_required
    def training_validate_snap(pid, filename):
        project_dir = _pid_path(pid)
        fn = filename or ""
        if not _VALIDATE_SNAP_RE.match(fn):
            abort(404)
        d = _validate_snap_dir(project_dir)
        fp = (d / fn).resolve()
        if not str(fp).startswith(str(d.resolve()) + os.sep) or not fp.is_file():
            abort(404)
        return send_from_directory(d, fn, max_age=0)

    @app.route("/api/training/specialists", methods=["GET"])
    @login_required
    def training_list_specialists():
        from visionai.config.specialists import list_specialists

        return jsonify(list_specialists(_repo_root()))

    @app.route("/api/training/specialists/inspect", methods=["POST"])
    @login_required
    def training_inspect_specialist_weights():
        """上传权重预检：返回类别名，不落盘为专模。"""
        import tempfile

        from visionai.config.specialists import inspect_yolo_weights

        if "file" not in request.files:
            return jsonify({"success": False, "message": "缺少 file 字段"}), 400
        f = request.files["file"]
        if not f or not f.filename:
            return jsonify({"success": False, "message": "未选择文件"}), 400
        base = secure_filename(f.filename) or "model.pt"
        ext = Path(base).suffix.lower()
        if ext not in (".pt", ".onnx"):
            return jsonify({"success": False, "message": "仅支持 Ultralytics YOLO 的 .pt / .onnx"}), 400
        tmp_dir = Path(tempfile.mkdtemp(prefix="visionai_spec_insp_"))
        tmp_path = tmp_dir / f"probe{ext}"
        try:
            f.save(str(tmp_path))
            result = inspect_yolo_weights(tmp_path)
            result["filename"] = base
            status = 200 if result.get("success") else 400
            return jsonify(result), status
        finally:
            try:
                shutil.rmtree(tmp_dir, ignore_errors=True)
            except Exception:  # noqa: BLE001
                pass

    @app.route("/api/training/specialists/import", methods=["POST"])
    @login_required
    def training_import_specialist():
        """导入社区/平台现成 YOLO 权重为专模（multipart 文件或 weights_url）。"""
        import tempfile
        import urllib.request

        from visionai.config.specialists import deploy_specialist
        from visionai.core.behaviors.registry import reload_plugins

        form = request.form
        weights_url = (form.get("weights_url") or "").strip()
        tmp_dir = Path(tempfile.mkdtemp(prefix="visionai_spec_imp_"))
        tmp_path: Optional[Path] = None
        try:
            if "file" in request.files and request.files["file"] and request.files["file"].filename:
                f = request.files["file"]
                base = secure_filename(f.filename) or "model.pt"
                ext = Path(base).suffix.lower()
                if ext not in (".pt", ".onnx"):
                    return jsonify({"success": False, "message": "仅支持 Ultralytics YOLO 的 .pt / .onnx"}), 400
                tmp_path = tmp_dir / f"upload{ext}"
                f.save(str(tmp_path))
            elif weights_url:
                if not (weights_url.startswith("http://") or weights_url.startswith("https://")):
                    return jsonify({"success": False, "message": "weights_url 须为 http(s)"}), 400
                ext = ".onnx" if weights_url.lower().endswith(".onnx") else ".pt"
                tmp_path = tmp_dir / f"download{ext}"
                try:
                    urllib.request.urlretrieve(weights_url, str(tmp_path))  # noqa: S310
                except Exception as e:  # noqa: BLE001
                    return jsonify({"success": False, "message": f"下载权重失败: {e}"}), 400
            else:
                return jsonify({"success": False, "message": "请上传 file 或提供 weights_url"}), 400

            key = (form.get("key") or "").strip()
            kind = (form.get("kind") or "person_event").strip().lower()
            name_zh = (form.get("name_zh") or key).strip()
            name_en = (form.get("name_en") or name_zh).strip()

            def _parse_float(name: str, default: Optional[float] = None) -> Optional[float]:
                raw = form.get(name)
                if raw is None or str(raw).strip() == "":
                    return default
                try:
                    return float(raw)
                except (TypeError, ValueError):
                    return default

            def _parse_int_list(name: str) -> Optional[List[int]]:
                raw = form.get(name)
                if raw is None or str(raw).strip() == "":
                    return None
                out: List[int] = []
                for part in re.split(r"[,;\s]+", str(raw).strip()):
                    if not part:
                        continue
                    try:
                        out.append(int(part))
                    except ValueError:
                        continue
                return out if out else None

            def _parse_classes() -> Optional[List[str]]:
                raw = form.get("classes")
                if raw is None or str(raw).strip() == "":
                    return None
                parts = re.split(r"[,;\n]+", str(raw).strip())
                return [p.strip() for p in parts if p.strip()] or None

            needs_raw = (form.get("needs_persons") or "true").strip().lower()
            needs_persons = needs_raw in ("1", "true", "yes", "on")

            result = deploy_specialist(
                _repo_root(),
                weights_path=tmp_path,
                key=key,
                kind=kind,
                name_zh=name_zh,
                name_en=name_en,
                classes=_parse_classes(),
                conf=_parse_float("conf"),
                score_threshold=_parse_float("score_threshold"),
                min_duration_sec=_parse_float("min_duration_sec"),
                positive_class_ids=_parse_int_list("positive_class_ids"),
                subject_class_ids=_parse_int_list("subject_class_ids"),
                comply_class_ids=_parse_int_list("comply_class_ids"),
                class_ids=_parse_int_list("class_ids"),
                needs_persons=needs_persons,
                backup=True,
                origin="imported",
            )
            if result.get("success"):
                reload_plugins()
            status = 200 if result.get("success") else 400
            return jsonify(result), status
        finally:
            try:
                shutil.rmtree(tmp_dir, ignore_errors=True)
            except Exception:  # noqa: BLE001
                pass

    @app.route("/api/training/specialists/<key>", methods=["DELETE"])
    @login_required
    def training_delete_specialist(key):
        from visionai.config.specialists import delete_specialist, scrub_detection_key_from_streams
        from visionai.core.behaviors.registry import reload_plugins

        result = delete_specialist((key or "").strip(), _repo_root())
        if result.get("success"):
            scrub_detection_key_from_streams((key or "").strip())
            reload_plugins()
        status = 200 if result.get("success") else 400
        return jsonify(result), status

    @app.route("/api/training/projects/<pid>/deploy", methods=["POST"])
    @login_required
    def training_deploy(pid):
        project_dir = _pid_path(pid)
        meta = _read_meta(project_dir)
        data = request.get_json(silent=True) or {}
        template_id = meta.get("template_id") or "custom"
        tpl = TRAINING_TEMPLATES.get(template_id, TRAINING_TEMPLATES["custom"])
        deploy_mode = (data.get("deploy_mode") or meta.get("deploy_mode") or tpl.get("deploy_mode") or "").strip()
        target = (data.get("target") or meta.get("deploy_target") or "").strip()
        is_builtin = deploy_mode == "builtin" or bool(target and target in DEPLOY_TARGETS)

        if is_builtin:
            if not target or target not in DEPLOY_TARGETS:
                return jsonify(
                    {
                        "success": False,
                        "message": "内置部署目标已下线，请用专模方式部署（自定义/场景模板 → models/specialists/）",
                    }
                ), 400
        elif not (data.get("key") or (tpl.get("specialist_defaults") or {}).get("key_suggestion")):
            return jsonify({"success": False, "message": "专模部署需提供 key（或选择带默认键名的模板）"}), 400

        wkey = (data.get("weights_path") or data.get("weights") or data.get("job_id") or "").strip()
        wp: Optional[Path] = None
        if wkey and re.match(r"^[a-f0-9]{16}$", wkey):
            jp = _jobs_base() / f"{wkey}.json"
            if jp.is_file():
                doc = json.loads(jp.read_text(encoding="utf-8"))
                w = doc.get("weights")
                if w and Path(w).is_file():
                    wp = Path(w)
        if wp is None:
            wp = _resolve_weights_in_project(project_dir, wkey)
        if wp is None or not wp.is_file():
            return jsonify({"success": False, "message": "无效权重路径"}), 400

        # 优先使用同 job 的测试集指标
        test_metrics = data.get("test_metrics")
        job_id = (data.get("job_id") or "").strip()
        if (not test_metrics) and job_id and re.match(r"^[a-f0-9]{16}$", job_id):
            jp = _jobs_base() / f"{job_id}.json"
            if jp.is_file():
                doc = json.loads(jp.read_text(encoding="utf-8"))
                test_metrics = doc.get("test_evaluation")
                if not wkey:
                    w = doc.get("weights")
                    if w and Path(w).is_file():
                        wp = Path(w)
        # 若权重路径对应 runs/<job>/... 尝试读同目录旁 job json
        if not test_metrics:
            # 从 weights 路径反查 job
            try:
                parts = wp.resolve().parts
                if "runs" in parts:
                    idx = parts.index("runs")
                    if idx + 1 < len(parts):
                        jid = parts[idx + 1]
                        if re.match(r"^[a-f0-9]{16}$", jid):
                            jp = _jobs_base() / f"{jid}.json"
                            if jp.is_file():
                                doc = json.loads(jp.read_text(encoding="utf-8"))
                                test_metrics = doc.get("test_evaluation")
                                job_id = jid
            except Exception:  # noqa: BLE001
                pass

        force_deploy = bool(data.get("force"))
        if force_deploy and os.environ.get("TRAINING_LAB_ALLOW_FORCE_DEPLOY", "0") != "1":
            return jsonify(
                {
                    "success": False,
                    "message": "已禁用强制上线。请提升测试集指标，或设置 TRAINING_LAB_ALLOW_FORCE_DEPLOY=1（仅调试）",
                }
            ), 400

        if is_builtin:
            result = deploy_weights_to_production(
                _repo_root(),
                weights_path=wp,
                target=target,
                backup=bool(data.get("backup", True)),
                patch_config=bool(data.get("patch_config", True)),
                test_metrics=test_metrics if isinstance(test_metrics, dict) else None,
                force=force_deploy,
                export_device=str(data.get("device") or detect_train_device()),
            )
            status = 200 if result.get("success") else 400
            return jsonify(result), status

        sd = tpl.get("specialist_defaults") or {}
        spec_key = (data.get("key") or sd.get("key_suggestion") or "").strip()
        spec_kind = (data.get("kind") or sd.get("kind") or "person_event").strip().lower()
        name_zh = (data.get("name_zh") or sd.get("name_zh") or spec_key).strip()
        name_en = (data.get("name_en") or sd.get("name_en") or name_zh).strip()

        def _int_list(raw, fallback):
            if raw is None:
                return list(fallback) if fallback is not None else None
            if isinstance(raw, (list, tuple)):
                return [int(x) for x in raw]
            return None

        result = deploy_as_specialist(
            _repo_root(),
            weights_path=wp,
            key=spec_key,
            kind=spec_kind,
            name_zh=name_zh,
            name_en=name_en,
            positive_class_ids=_int_list(data.get("positive_class_ids"), sd.get("positive_class_ids")),
            subject_class_ids=_int_list(data.get("subject_class_ids"), sd.get("subject_class_ids")),
            comply_class_ids=_int_list(data.get("comply_class_ids"), sd.get("comply_class_ids")),
            class_ids=_int_list(data.get("class_ids"), sd.get("class_ids")),
            needs_persons=bool(data.get("needs_persons", sd.get("needs_persons", True))),
            expected_classes=meta.get("classes") or tpl.get("classes") or None,
            test_metrics=test_metrics if isinstance(test_metrics, dict) else None,
            force=force_deploy,
            source_project_id=pid,
            backup=bool(data.get("backup", True)),
        )
        if result.get("success"):
            from visionai.core.behaviors.registry import reload_plugins

            reload_plugins()
        status = 200 if result.get("success") else 400
        return jsonify(result), status

    @app.route("/api/training/snapshots", methods=["GET"])
    @login_required
    def training_list_snapshots():
        stream = request.args.get("stream", "")
        det = request.args.get("detection_type", "")
        try:
            limit = int(request.args.get("limit", "40"))
        except ValueError:
            limit = 40
        limit = max(1, min(limit, 200))
        items = list_production_snapshots(
            Path(SAVE_DIR),
            stream=stream,
            detection_type=det,
            limit=limit,
        )
        return jsonify(items)

    @app.route("/api/training/snapshots/image", methods=["GET"])
    @login_required
    def training_snapshot_image():
        """安全地回传生产 snapshots 下的单张图片（人工研判预览用）。"""
        raw = (request.args.get("path") or "").strip()
        if not raw:
            return jsonify({"success": False, "message": "缺少 path"}), 400
        p = Path(raw).resolve()
        save_resolved = Path(SAVE_DIR).resolve()
        try:
            p.relative_to(save_resolved)
        except ValueError:
            return jsonify({"success": False, "message": "非法路径"}), 403
        if not p.is_file() or p.suffix.lower() not in (".jpg", ".jpeg", ".png"):
            return jsonify({"success": False, "message": "文件不存在"}), 404
        return send_file(str(p))

    @app.route("/api/training/projects/<pid>/import-snapshots", methods=["POST"])
    @login_required
    def training_import_snapshots(pid):
        project_dir = _pid_path(pid)
        data = request.get_json(silent=True) or {}
        paths = data.get("paths") or []
        if not isinstance(paths, list) or not paths:
            return jsonify({"success": False, "message": "请提供 paths 数组"}), 400
        verdicts = data.get("verdicts")
        if not isinstance(verdicts, dict):
            verdicts = {}
        verdicts = {str(k): str(v) for k, v in verdicts.items() if str(v) in ("tp", "fp")}
        result = import_snapshots_to_project(project_dir, paths, Path(SAVE_DIR), verdicts=verdicts)
        # 记录本校准项目要覆盖的专模 key（重新部署时默认同名覆盖）
        sp_key = (data.get("specialist_key") or "").strip()
        sp_meta = None
        if sp_key and re.match(r"^[a-z][a-z0-9_]*$", sp_key):
            meta = _read_meta(project_dir)
            if meta.get("calib_specialist_key") != sp_key:
                meta["calib_specialist_key"] = sp_key
                _write_meta(project_dir, meta)
            from visionai.config.specialists import load_specialist

            sp_meta = load_specialist(sp_key, _repo_root())
        # 研判为「准确」的回流图：用专模当前权重直接自动标注（用户已确认准确，免草稿审核）
        tp_names = result.get("positive_names") or []
        if tp_names and sp_meta:
            model_rel = (sp_meta.get("model_path") or "").strip()
            wp = Path(model_rel)
            if model_rel and not wp.is_absolute():
                wp = (_repo_root() / model_rel).resolve()
            if wp.is_file():
                try:
                    al = autolabel_images_with_weights(
                        project_dir,
                        tp_names,
                        weights_path=str(wp),
                        conf=float(sp_meta.get("conf") or 0.25),
                    )
                    result["autolabel"] = al
                except Exception as e:  # noqa: BLE001
                    logger.warning("回流准确样本自动标注失败: %s", e)
                    result["autolabel"] = {"success": False, "message": str(e)}
        return jsonify({"success": True, **result})

    @app.route("/api/training/projects/<pid>/prelabel", methods=["POST"])
    @login_required
    def training_prelabel(pid):
        project_dir = _pid_path(pid)
        data = request.get_json(silent=True) or {}
        wkey = (data.get("weights_path") or data.get("weights") or "").strip()
        wp = _resolve_weights_in_project(project_dir, wkey)
        if wp is None:
            return jsonify({"success": False, "message": "无效权重路径"}), 400
        conf = float(data.get("conf") or 0.25)
        conf = max(0.05, min(conf, 0.95))
        only_unlabeled = bool(data.get("only_unlabeled", True))
        result = prelabel_project_images(
            project_dir,
            weights_path=str(wp),
            conf=conf,
            only_unlabeled=only_unlabeled,
            device=data.get("device"),
        )
        status = 200 if result.get("success") else 400
        return jsonify(result), status

    @app.route("/api/training/projects/<pid>/threshold-suggest", methods=["POST"])
    @login_required
    def training_threshold_suggest(pid):
        project_dir = _pid_path(pid)
        data = request.get_json(silent=True) or {}
        wkey = (data.get("weights_path") or data.get("weights") or "").strip()
        wp = _resolve_weights_in_project(project_dir, wkey)
        if wp is None:
            return jsonify({"success": False, "message": "无效权重路径"}), 400
        try:
            meta = _read_meta(project_dir)
            yaml_path = materialize_yolo_split(project_dir, meta)
        except ValueError as e:
            return jsonify({"success": False, "message": str(e)}), 400
        class_index = int(data.get("class_index") or 0)
        spec = DEPLOY_TARGETS.get(meta.get("deploy_target") or "")
        if spec and spec.get("single_class_index") is not None:
            class_index = int(spec["single_class_index"])
        result = suggest_thresholds_from_val(
            str(wp),
            yaml_path,
            project_dir / "_yolo_staging",
            class_index=class_index,
        )
        if not result.get("ok"):
            return jsonify({"success": False, **result}), 400
        return jsonify({"success": True, **result})


def init_training_lab(app):
    """注册蓝图与 API。"""
    app.register_blueprint(training_bp)
    _register_api_routes(app)
