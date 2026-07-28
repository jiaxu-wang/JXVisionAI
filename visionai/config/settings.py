"""
运行时配置。

优先级：环境变量 > ``config/config.ini``（多分节，映射为规范键）> 本文件内置默认。
修改 ini 或环境变量后需重启进程。可用 ``VISIONAI_CONFIG`` 指定其它 ini 路径。

分节示例：``[basic]`` ``[redis]`` ``[minio]`` ``[email]`` ``[models]`` ``[preview]``。
仍兼容旧版单节 ``[visionai]``。Redis/对象存储等键前缀沿用历史标识 ``visionai``。
"""

import configparser
import os
import warnings
from typing import Dict, List, Optional, Union

from visionai.config.ini_sections import flatten_configparser, has_valid_sections

_DEFAULT_SECRET = "123456-bb6b-4889-a715-d9eb2d1925cc"

# .../visionai/config/settings.py → 项目根
_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir, os.pardir))
PROJECT_ROOT = _ROOT
_DEFAULT_INI = os.path.join(_ROOT, "config", "config.ini")

_PATH_RELATIVE_HINT = "相对路径均相对项目根目录；绝对路径与 http(s):// URL 原样使用"


def _read_ini() -> Dict[str, str]:
    path = os.environ.get("VISIONAI_CONFIG", _DEFAULT_INI)
    if not path or not os.path.isfile(path):
        return {}
    try:
        cp = configparser.ConfigParser(interpolation=None)
        read = cp.read(path, encoding="utf-8")
        if not read or not has_valid_sections(cp.sections()):
            return {}
        return flatten_configparser(cp)
    except Exception as e:  # noqa: BLE001
        warnings.warn(f"读取配置文件失败，已忽略: {path}: {e}", stacklevel=2)
        return {}


_INI: Dict[str, str] = _read_ini()


def _lookup_str(name: str) -> Optional[str]:
    v = os.environ.get(name)
    if v is not None and v != "":
        return v
    lk = name.lower()
    if lk in _INI:
        return _INI[lk]
    return None


def _cfg_str(name: str, default: str) -> str:
    o = _lookup_str(name)
    return o if o is not None else default


def _cfg_int(name: str, default: int) -> int:
    o = _lookup_str(name)
    if o is None:
        return default
    try:
        return int(o)
    except (TypeError, ValueError):
        return default


def _cfg_float(name: str, default: float) -> float:
    o = _lookup_str(name)
    if o is None:
        return default
    try:
        return float(o)
    except (TypeError, ValueError):
        return default


def resolve_config_path(raw: str) -> str:
    """config.ini 路径项：相对路径相对项目根解析为绝对路径。"""
    p = (raw or "").strip()
    if not p:
        return ""
    if "://" in p:
        return p
    if os.path.isabs(p):
        return os.path.normpath(p)
    if p.startswith("./"):
        p = p[2:]
    return os.path.normpath(os.path.join(_ROOT, p))


def to_display_path(path: str) -> str:
    """展示用：项目根下的绝对路径转为相对路径。"""
    p = (path or "").strip()
    if not p or "://" in p:
        return p
    try:
        rel = os.path.relpath(os.path.normpath(p), _ROOT)
    except ValueError:
        return p
    if rel.startswith(".."):
        return p
    return rel.replace("\\", "/")


def _cfg_path(name: str, default: str) -> str:
    raw = _cfg_str(name, default)
    return resolve_config_path(raw) if raw else ""


def _cfg_bool(name: str, default: bool) -> bool:
    o = _lookup_str(name)
    if o is None:
        return default
    v = o.strip().lower()
    if v in ("0", "false", "no", "off"):
        return False
    if v in ("1", "true", "yes", "on"):
        return True
    return default


def _secret() -> str:
    for k in ("VISIONAI_SECRET", "SECRET"):
        v = os.environ.get(k)
        if v is not None and v != "":
            return v
    if "visionai_secret" in _INI and _INI["visionai_secret"]:
        return _INI["visionai_secret"]
    if "secret" in _INI and _INI["secret"]:
        return _INI["secret"]
    return _DEFAULT_SECRET


# Flask 会话密钥
SECRET = _secret()

# 检测
DETECTION_INTERVAL = _cfg_int("DETECTION_INTERVAL", 15)
CONF_THRESHOLD = _cfg_float("CONF_THRESHOLD", 0.5)

# 人员聚集：单帧检出人物数 ≥ 阈值即判定（可选持续时长防抖，0 表示立即告警）
GATHER_MIN_PERSONS = max(3, _cfg_int("GATHER_MIN_PERSONS", 3))
GATHER_MIN_DURATION_SEC = max(3, _cfg_float("GATHER_MIN_DURATION_SEC", 3))

# ---------- 内置专模（models/ 下 .pt / .onnx；与 COCO 主检测并行）----------
def _models_default(filename: str) -> str:
    return f"models/{filename}"


DEDICATED_MAX_PERSONS_PER_FRAME = max(1, _cfg_int("DEDICATED_MAX_PERSONS_PER_FRAME", 8))
DEDICATED_DEFAULT_CONF = max(0.05, min(0.99, _cfg_float("DEDICATED_DEFAULT_CONF", 0.40)))
DEDICATED_DEFAULT_SCORE_THRESHOLD = max(
    0.05, min(0.99, _cfg_float("DEDICATED_DEFAULT_SCORE_THRESHOLD", 0.45))
)
DEDICATED_DEFAULT_MIN_DURATION_SEC = max(
    0.0, _cfg_float("DEDICATED_DEFAULT_MIN_DURATION_SEC", 1.0)
)

# 人脸识别（InsightFace buffalo_l，模型目录 models/buffalo_l/）
FACE_RECOG_MODEL_ROOT = _cfg_path("FACE_RECOG_MODEL_ROOT", PROJECT_ROOT)
_ds = max(320, min(1280, _cfg_int("FACE_RECOG_DET_SIZE", 640)))
FACE_RECOG_DET_SIZE = (_ds, _ds)
FACE_RECOG_DET_MODEL_PATH = _cfg_path(
    "FACE_RECOG_DET_MODEL_PATH", os.path.join("models", "buffalo_l", "det_10g.onnx")
)
FACE_RECOG_EMBED_MODEL_PATH = _cfg_path(
    "FACE_RECOG_EMBED_MODEL_PATH", os.path.join("models", "buffalo_l", "w600k_r50.onnx")
)
FACE_RECOG_GENDERAGE_MODEL_PATH = _cfg_path(
    "FACE_RECOG_GENDERAGE_MODEL_PATH",
    os.path.join("models", "buffalo_l", "genderage.onnx"),
)
# 性别/年龄总开关（false 时即使流配置勾选也不跑）；真正启用还需在「检测类型配置」勾选
FACE_RECOG_GENDERAGE_ENABLED = _cfg_bool("FACE_RECOG_GENDERAGE_ENABLED", True)
FACE_RECOG_DET_CONF = max(0.05, min(0.99, _cfg_float("FACE_RECOG_DET_CONF", 0.5)))
FACE_RECOG_ROTATE = max(0, min(360, _cfg_int("FACE_RECOG_ROTATE", 0)))
FACE_RECOGNITION_THRESHOLD = max(
    0.05, min(0.99, _cfg_float("FACE_RECOGNITION_THRESHOLD", 0.45))
)
FACE_RECOGNITION_MIN_DURATION_SEC = max(
    0.0, _cfg_float("FACE_RECOGNITION_MIN_DURATION_SEC", 2.0)
)
FACE_LIBRARY_DIR = _cfg_path("FACE_LIBRARY_DIR", os.path.join(PROJECT_ROOT, "face_library"))
FACE_RECOGNITION_MAX_FACES_PER_FRAME = max(
    1, _cfg_int("FACE_RECOGNITION_MAX_FACES_PER_FRAME", 5)
)

MAKE_CALL_MODEL_PATH = _cfg_path("MAKE_CALL_MODEL_PATH", _models_default("make_call.onnx"))
MAKE_CALL_MODEL_CONF = max(
    0.05, min(0.99, _cfg_float("MAKE_CALL_MODEL_CONF", DEDICATED_DEFAULT_CONF))
)
MAKE_CALL_SCORE_THRESHOLD = max(
    0.05, min(0.99, _cfg_float("MAKE_CALL_SCORE_THRESHOLD", DEDICATED_DEFAULT_SCORE_THRESHOLD))
)
MAKE_CALL_MIN_DURATION_SEC = max(
    0.0, _cfg_float("MAKE_CALL_MIN_DURATION_SEC", DEDICATED_DEFAULT_MIN_DURATION_SEC)
)
MAKE_CALL_USE_DEDICATED = _cfg_bool("MAKE_CALL_USE_DEDICATED", True)
MAKE_CALL_REQUIRE_PERSON_OVERLAP = _cfg_bool("MAKE_CALL_REQUIRE_PERSON_OVERLAP", False)

# 保存
SAVE_DIR = _cfg_path("SAVE_DIR", "./snapshots")
SAVE_FORMAT = "%Y%m%d_%H%M%S_%f.jpg"
SAVE_INTERVAL = _cfg_int("SAVE_INTERVAL", 10)

# YOLO
YOLO_MODEL = _cfg_path("YOLO_MODEL", _models_default("yolo26s.pt"))

# 打电话 / 玩手机：YOLO+COCO overlap 后用人体姿态（YOLO26-pose）把手机中心与耳根/口鼻/手腕比距分类
POSE_MODEL = _cfg_path("POSE_MODEL", _models_default("yolo26s-pose.pt"))
POSE_FOR_PHONE_ENABLED = _cfg_bool("POSE_FOR_PHONE_ENABLED", True)

# 关键点置信低于此值不参加「贴头/贴腕」距离（仍可走竖直带 fallback）
PHONE_POSE_KP_MIN_CONF = max(0.0, min(1.0, _cfg_float("PHONE_POSE_KP_MIN_CONF", 0.28)))
PHONE_CALL_HEAD_RATIO = max(0.05, _cfg_float("PHONE_CALL_HEAD_RATIO", 0.26))
PHONE_PLAY_WRIST_RATIO = max(0.05, _cfg_float("PHONE_PLAY_WRIST_RATIO", 0.20))
PHONE_VERTICAL_BOUNDARY = max(0.2, min(0.85, _cfg_float("PHONE_VERTICAL_BOUNDARY", 0.42)))

# 日志
LOG_LEVEL = _cfg_str("LOG_LEVEL", "INFO")
LOG_FORMAT = "%(asctime)s - %(levelname)s - %(message)s"
LOG_RETENTION_DAYS = max(1, _cfg_int("LOG_RETENTION_DAYS", 3))
LOG_DIR = _cfg_path("LOG_DIR", "./logs")

# Redis
REDIS_HOST = _cfg_str("REDIS_HOST", "192.168.2.159")
REDIS_PORT = _cfg_int("REDIS_PORT", 16379)
REDIS_PASSWORD = _cfg_str("REDIS_PASSWORD", "VisionAI@2026")
REDIS_DB = _cfg_int("REDIS_DB", 0)
REDIS_KEY_PREFIX = _cfg_str("REDIS_KEY_PREFIX", "visionai/")

# 检测记录保留（天，至少 1）：Redis 检测 Hash 的 TTL、S3/MinIO 截图生命周期均用此值
DETECTION_RETENTION_DAYS = max(1, _cfg_int("DETECTION_RETENTION_DAYS", 1))

# 管理端
AUTO_REFRESH_INTERVAL = _cfg_int("AUTO_REFRESH_INTERVAL", 20)

# 流预览：MJPEG/WS 带标注轮询（秒，愈小愈跟手略增 CPU）
PREVIEW_ANNOTATED_POLL_SEC = max(0.02, _cfg_float("PREVIEW_ANNOTATED_POLL_SEC", 0.05))
# HLS：FFmpeg 中转码输出目录（相对运行目录）、分片时长、列表窗口、空闲停止秒数
PREVIEW_HLS_ENABLED = _cfg_bool("PREVIEW_HLS_ENABLED", True)
PREVIEW_HLS_ROOT = _cfg_path("PREVIEW_HLS_ROOT", "./hls-preview")
PREVIEW_HLS_SEGMENT_SEC = max(0.3, min(4.0, _cfg_float("PREVIEW_HLS_SEGMENT_SEC", 0.5)))
PREVIEW_HLS_LIST_SIZE = max(3, min(20, _cfg_int("PREVIEW_HLS_LIST_SIZE", 6)))
PREVIEW_HLS_IDLE_SEC = max(30, _cfg_int("PREVIEW_HLS_IDLE_SEC", 120))
# WebSocket 实时原画上限 FPS（愈高延迟愈低、带宽/CPU 愈高）
PREVIEW_WS_MAX_FPS = max(5, min(60, _cfg_int("PREVIEW_WS_MAX_FPS", 30)))
# WebRTC：服务端 aiortc + MediaPlayer（依赖 PyAV/FFmpeg）；逗号分隔多个 stun:url
PREVIEW_WEBRTC_ENABLED = _cfg_bool("PREVIEW_WEBRTC_ENABLED", True)
PREVIEW_WEBRTC_STUN_URLS = _cfg_str(
    "PREVIEW_WEBRTC_STUN_URLS",
    "stun:stun.l.google.com:19302",
).strip()

# 告警外发邮件（全局 SMTP；每路收件人与是否发信在 Redis：alert_emails、alert_email_enabled）
# Webhook：每路 alert_webhook_urls、alert_webhook_enabled（仅 Redis，见 visionai/utils/alert_webhook.py）
SMTP_ALERT_ENABLED = _cfg_bool("SMTP_ALERT_ENABLED", True)
SMTP_HOST = _cfg_str("SMTP_HOST", "").strip()
SMTP_PORT = max(1, min(65535, _cfg_int("SMTP_PORT", 587)))
SMTP_USER = _cfg_str("SMTP_USER", "").strip()
SMTP_PASSWORD = _cfg_str("SMTP_PASSWORD", "")
SMTP_FROM = _cfg_str("SMTP_FROM", "").strip()
SMTP_USE_TLS = _cfg_bool("SMTP_USE_TLS", True)
SMTP_USE_SSL = _cfg_bool("SMTP_USE_SSL", False)
SMTP_TIMEOUT = max(5, _cfg_int("SMTP_TIMEOUT", 30))
SMTP_ALERT_ATTACH_MAX_BYTES = max(100_000, _cfg_int("SMTP_ALERT_ATTACH_MAX_BYTES", 5242880))

# 对象存储（S3 兼容：MinIO / AWS S3 / 其他）
OBJECT_STORAGE_ENABLED = _cfg_bool("OBJECT_STORAGE_ENABLED", False)
# 开启上传后是否仍写本地盘（推荐 True，便于本机调试用；仅对象存储时可为 False）
OBJECT_STORAGE_KEEP_LOCAL = _cfg_bool("OBJECT_STORAGE_KEEP_LOCAL", True)
S3_ENDPOINT_URL = _cfg_str("S3_ENDPOINT_URL", "")
S3_ACCESS_KEY_ID = _cfg_str("S3_ACCESS_KEY_ID", "")
S3_SECRET_ACCESS_KEY = _cfg_str("S3_SECRET_ACCESS_KEY", "")
S3_BUCKET = _cfg_str("S3_BUCKET", "visionai")
S3_REGION = _cfg_str("S3_REGION", "us-east-1")
S3_USE_SSL = _cfg_bool("S3_USE_SSL", True)
# 对象键前缀，截图默认在其下，后续视频等可再分子前缀
S3_PATH_PREFIX = _cfg_str("S3_PATH_PREFIX", "visionai/").rstrip("/") + "/"
# MinIO 常用 path
S3_ADDRESSING_STYLE = _cfg_str("S3_ADDRESSING_STYLE", "path")
# 启动时对桶写入生命周期规则：前缀 S3_PATH_PREFIX + snapshots/，过期天数 = DETECTION_RETENTION_DAYS
S3_LIFECYCLE_ENABLED = _cfg_bool("S3_LIFECYCLE_ENABLED", True)

# 总开关（推荐）：cpu | gpu —— 同时控制 YOLO(PyTorch) 与 ONNX；改完重启即生效
# 留空则分别看 yolo_device / onnx_provider（高级拆分）
INFERENCE_DEVICE = (_lookup_str("INFERENCE_DEVICE") or "").strip().lower()
# YOLO / Ultralytics：留空=自动；cpu；GPU 序号如 0（仅当 inference_device 未设时单独生效）
YOLO_DEVICE = (_lookup_str("YOLO_DEVICE") or "").strip()
# ONNX Runtime：cpu | cuda_first/gpu（仅当 inference_device 未设时单独生效）
ONNX_PROVIDER = (_lookup_str("ONNX_PROVIDER") or "cpu").strip().lower() or "cpu"


def _normalized_inference_device() -> str:
    """返回 cpu | gpu | ''（空表示用分项配置）。"""
    d = INFERENCE_DEVICE.strip().lower()
    if d in ("cpu", "gpu", "cuda"):
        return "cpu" if d == "cpu" else "gpu"
    return ""


def yolo_inference_device() -> Optional[Union[str, int]]:
    """传给 Ultralytics `model(..., device=...)`；None 表示不传参（沿用库默认 Auto）。"""
    mode = _normalized_inference_device()
    if mode == "cpu":
        return "cpu"
    if mode == "gpu":
        raw = YOLO_DEVICE.strip()
        if raw.isdigit():
            try:
                return int(raw)
            except ValueError:
                return 0
        lo = raw.lower()
        if lo and lo not in ("auto", "none", "default", "gpu", "cuda"):
            if lo == "cpu":
                return 0  # 总开关为 gpu 时忽略分项 cpu
            return raw
        return 0

    raw = YOLO_DEVICE.strip()
    if not raw:
        return None
    lo = raw.lower()
    if lo in ("auto", "none", "default"):
        return None
    if lo == "cpu":
        return "cpu"
    if lo in ("gpu", "cuda"):
        return 0
    if raw.isdigit():
        try:
            return int(raw)
        except ValueError:
            return raw
    return raw


def onnx_runtime_providers_ordered() -> List[str]:
    """InferenceSession(..., providers=...) 顺序；运行时探测 onnxruntime 是否含 CUDA EP。"""
    mode = _normalized_inference_device()
    if mode == "cpu":
        pref = "cpu"
    elif mode == "gpu":
        pref = "cuda_first"
    else:
        pref = ONNX_PROVIDER.strip().lower()

    if pref == "cpu":
        return ["CPUExecutionProvider"]

    try:
        import onnxruntime as ort  # noqa: WPS433
    except Exception:  # noqa: BLE001
        return ["CPUExecutionProvider"]

    avail = frozenset(getattr(ort, "get_available_providers", lambda: [])())
    if pref in ("cuda", "cuda_first", "gpu", "cuda_auto"):
        if "CUDAExecutionProvider" not in avail:
            warnings.warn(
                "需要 CUDA 推理但 onnxruntime 无 CUDAExecutionProvider "
                "（请安装 onnxruntime-gpu 并卸载纯 CPU 的 onnxruntime），已退回 CPU",
                stacklevel=2,
            )
            return ["CPUExecutionProvider"]
        return ["CUDAExecutionProvider", "CPUExecutionProvider"]

    warnings.warn(
        f"未知的 onnx_provider={pref!r}，改用 CPUExecutionProvider",
        stacklevel=2,
    )
    return ["CPUExecutionProvider"]


def describe_inference_backend() -> str:
    """启动日志用：当前有效的 YOLO / ONNX 设备摘要。"""
    mode = _normalized_inference_device() or "split"
    yolo = yolo_inference_device()
    yolo_s = "auto" if yolo is None else str(yolo)
    onnx = onnx_runtime_providers_ordered()
    onnx_s = "+".join(onnx)
    return f"inference_device={mode or 'auto'} yolo={yolo_s} onnx=[{onnx_s}]"
