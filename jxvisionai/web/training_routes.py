"""训练实验室（MVP）：RTSP 截帧、浏览器画框标注、服务端触发 Ultralytics 训练。

数据目录：<repo>/training_lab_data/projects/<project_id>/（images / labels / meta.json）
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
from flask import Blueprint, Response, abort, jsonify, render_template, request, send_from_directory
from werkzeug.utils import secure_filename

from jxvisionai.config.settings import SAVE_DIR, yolo_inference_device
from jxvisionai.utils.rtsp_url import normalize_rtsp_url
from jxvisionai.web.training_lab_core import (
    DEPLOY_TARGETS,
    TRAINING_TEMPLATES,
    check_dataset_health,
    deploy_weights_to_production,
    detect_train_device,
    import_snapshots_to_project,
    list_labeled_stems,
    list_production_snapshots,
    materialize_yolo_split,
    prelabel_project_images,
    run_evaluate_subprocess,
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
    # jxvisionai/web/training_routes.py -> jxvisionai -> repo
    return Path(__file__).resolve().parent.parent.parent


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


def read_rtsp_frame_bgr(url: str, timeout_sec: float = 12.0) -> Optional[Any]:
    """读取单帧 BGR；失败返回 None。"""
    u = normalize_rtsp_url((url or "").strip())
    if not _allowed_rtsp(u):
        return None
    cap = cv2.VideoCapture(u, cv2.CAP_FFMPEG)
    if not cap.isOpened():
        return None
    if hasattr(cv2, "CAP_PROP_OPEN_TIMEOUT_MSEC"):
        cap.set(cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, int(timeout_sec * 1000))
    t0 = time.monotonic()
    frame = None
    while time.monotonic() - t0 < timeout_sec:
        ok, fr = cap.read()
        if ok and fr is not None and fr.size > 0:
            frame = fr
            break
        time.sleep(0.05)
    cap.release()
    return frame


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


def _validate_infer(
    weights_path: str,
    frame_bgr,
    device_arg,
    conf: float = 0.25,
    imgsz: int = 640,
) -> tuple:
    """两路推理：① 用户阈值——画框快照；② 低阈值——候选列表（含每条置信度写入日志）。

    仅极少数样本训练时，高 conf 常会「未检出」，但低阈值仍可看到模型是否在打低分框。
    """
    model = _get_cached_yolo(weights_path)
    kw_base: Dict[str, Any] = {"imgsz": int(imgsz), "verbose": False}
    dev = _parse_infer_device(device_arg)
    if dev is not None:
        kw_base["device"] = dev

    conf_user = float(max(0.05, min(conf, 0.999)))

    rh = model.predict(source=frame_bgr, **kw_base, conf=conf_user)[0]
    plot_bgr = rh.plot()
    if plot_bgr is None:
        plot_bgr = frame_bgr.copy()

    names = getattr(model, "names", {}) or {}

    dets: List[Dict[str, Any]] = []
    if rh.boxes is not None and len(rh.boxes):
        for box in rh.boxes:
            ci = int(box.cls[0])
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
) -> str:
    diag_floor = max(0.001, float(_VALIDATE_CANDIDATE_FLOOR))
    if dets:
        parts = [
            f"{d.get('name', d.get('cls'))} conf={float(d.get('conf', 0)):.4f}"
            for d in dets
        ]
        return ("命中「显示阈值≥{:.4f}」：".format(conf_user)) + " | ".join(parts)
    if candidates:
        top = candidates[:24]
        cstr = "; ".join(
            f"{c.get('name')} conf={float(c.get('conf', 0)):.4f}"
            + (" ✓" if c.get("passed_user_threshold") else "")
            for c in top
        )
        more = f" （共 {len(candidates)} 框，至多展示 24）" if len(candidates) > 24 else ""
        return (
            f"未达到显示阈值（≥{conf_user:.4f}）。"
            f"候选扫描（conf≥{diag_floor:.4f}）： "
            + cstr
            + more
        )
    return (
        f"未达到显示阈值（≥{conf_user:.4f}）；候选扫描 conf≥{diag_floor:.4f} 仍无框。"
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
            frame = read_rtsp_frame_bgr(u, timeout_sec=12.0)
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
                        weights_path, frame, device_arg, conf=conf, imgsz=imgsz
                    )
                    snap = _validate_save_snap(project_dir, plot_bgr)
                    msg = _format_validate_infer_message(dets, candidates, float(conf))
                    _validate_append_log(
                        project_id,
                        {
                            "kind": "infer",
                            "message": msg,
                            "detections": dets,
                            "candidates": candidates,
                            "conf_threshold": float(conf),
                            "candidate_conf_floor": float(_VALIDATE_CANDIDATE_FLOOR),
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
        yaml_path = materialize_yolo_split(project_dir, _read_meta(project_dir))
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

    # 解析预训练权重路径
    pre = pretrained_model.strip() or "yolov8n.pt"
    if pre and not Path(pre).is_absolute():
        cand = Path(pre)
        if not cand.is_file():
            cand2 = (_repo_root() / pre).resolve()
            if cand2.is_file():
                pre = str(cand2)

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
    }
    if status == "completed" and weights.is_file():
        dev = device.strip() or detect_train_device()
        eval_metrics = run_evaluate_subprocess(
            _repo_root(),
            model_path=str(weights.resolve()),
            data_yaml=str(yaml_path.resolve()),
            device=dev,
            log_fp=log_fp,
        )
        payload["evaluation"] = eval_metrics
        if eval_metrics.get("ok"):
            payload["map50"] = eval_metrics.get("map50")
            payload["precision"] = eval_metrics.get("precision")
            payload["recall"] = eval_metrics.get("recall")
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
    from jxvisionai.web.app import login_required
    from jxvisionai.core.redis_manager import redis_manager

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
        frame = read_rtsp_frame_bgr(url)
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
                    "description": tpl.get("description"),
                    "classes": tpl.get("classes") or [],
                    "deploy_target": tpl.get("deploy_target"),
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
                    "created_at": meta.get("created_at"),
                    "image_count": len(list((d / "images").glob("*"))) if (d / "images").is_dir() else 0,
                    "labeled_count": health.labeled_images,
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
        meta = {
            "title": title,
            "classes": classes,
            "template_id": template_id,
            "deploy_target": tpl.get("deploy_target"),
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
        return jsonify(health.to_dict())

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
        frame = read_rtsp_frame_bgr(url)
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
        labeled = set(list_labeled_stems(project_dir))
        out = []
        for p in sorted(img_dir.iterdir(), key=lambda x: x.name):
            if p.suffix.lower() not in (".jpg", ".jpeg", ".png"):
                continue
            out.append(
                {
                    "filename": p.name,
                    "labeled": p.stem in labeled,
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
        labels_root = (project_dir / "labels").resolve()
        try:
            img_path.unlink()
            if str(lbl_path).startswith(str(labels_root) + os.sep) and lbl_path.is_file():
                lbl_path.unlink()
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
        fp = (project_dir / "labels" / filename).resolve()
        if not str(fp).startswith(str((project_dir / "labels").resolve())):
            abort(404)
        if not fp.is_file():
            return Response("", mimetype="text/plain")
        return send_from_directory(project_dir / "labels", filename, mimetype="text/plain", max_age=0)

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
        return jsonify({"success": True, "lines": len(lines)})

    @app.route("/api/training/projects/<pid>/train", methods=["POST"])
    @login_required
    def training_start_train(pid):
        project_dir = _pid_path(pid)
        meta = _read_meta(project_dir)
        data = request.get_json(silent=True) or {}
        force = bool(data.get("force"))

        health = check_dataset_health(project_dir, meta)
        if not health.can_train and not force:
            return jsonify(
                {
                    "success": False,
                    "message": "未达开训门槛",
                    "health": health.to_dict(),
                }
            ), 400

        defaults = meta.get("train_defaults") or {}
        epochs = int(data.get("epochs") or defaults.get("epochs") or 30)
        batch_size = int(data.get("batch_size") or defaults.get("batch") or 8)
        img_size = int(data.get("img_size") or defaults.get("imgsz") or 640)
        device = str(data.get("device") or detect_train_device()).strip()
        pretrained = str(
            data.get("pretrained_model") or defaults.get("pretrained") or "yolov8n.pt"
        ).strip()

        epochs = max(1, min(epochs, 500))
        batch_size = max(1, min(batch_size, 128))
        img_size = max(320, min(img_size, 1280))

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
            frame = read_rtsp_frame_bgr(url)
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
                str(wp), frame, device_arg, conf=conf, imgsz=imgsz
            )
            snap = _validate_save_snap(project_dir, plot_bgr)
            msg = _format_validate_infer_message(dets, candidates, float(conf))
            _validate_append_log(
                pid,
                {
                    "kind": "infer",
                    "message": msg,
                    "detections": dets,
                    "candidates": candidates,
                    "conf_threshold": float(conf),
                    "candidate_conf_floor": float(_VALIDATE_CANDIDATE_FLOOR),
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
            ),
            daemon=True,
        )
        with _validate_sessions_lock:
            _validate_sessions[pid] = {"stop": stop_ev, "thread": th}
        th.start()
        _validate_append_log(
            pid,
            {
                "kind": "info",
                "message": f"已开启 RTSP 循环验证，间隔 {interval:g}s",
                "detections": [],
                "snapshot": None,
                "source": "rtsp_loop",
            },
        )
        return jsonify({"success": True, "interval_sec": interval})

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

    @app.route("/api/training/projects/<pid>/deploy", methods=["POST"])
    @login_required
    def training_deploy(pid):
        project_dir = _pid_path(pid)
        meta = _read_meta(project_dir)
        data = request.get_json(silent=True) or {}
        target = (data.get("target") or meta.get("deploy_target") or "").strip()
        if not target:
            return jsonify({"success": False, "message": "请指定部署目标 target（如 smoking）"}), 400

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

        result = deploy_weights_to_production(
            _repo_root(),
            weights_path=wp,
            target=target,
            backup=bool(data.get("backup", True)),
            patch_config=bool(data.get("patch_config", True)),
        )
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

    @app.route("/api/training/projects/<pid>/import-snapshots", methods=["POST"])
    @login_required
    def training_import_snapshots(pid):
        project_dir = _pid_path(pid)
        data = request.get_json(silent=True) or {}
        paths = data.get("paths") or []
        if not isinstance(paths, list) or not paths:
            return jsonify({"success": False, "message": "请提供 paths 数组"}), 400
        result = import_snapshots_to_project(project_dir, paths, Path(SAVE_DIR))
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
        # 可选写入 config.ini（吸烟相关键）
        apply = bool(data.get("apply_config"))
        if apply and meta.get("deploy_target") == "smoking":
            from jxvisionai.config.ini_manager import patch_config_updates

            patch_config_updates(
                {
                    "smoking_cigarette_detector_conf": str(result["suggested_detector_conf"]),
                    "smoking_conf_threshold": str(result["suggested_alert_conf"]),
                    "smoking_min_duration_sec": str(result.get("suggested_min_duration_sec", 1.5)),
                }
            )
            result["config_patched"] = True
            result["restart_required"] = True
        return jsonify({"success": True, **result})


def init_training_lab(app):
    """注册蓝图与 API。"""
    app.register_blueprint(training_bp)
    _register_api_routes(app)
