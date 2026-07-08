"""项目配置：环境变量 > config/config.ini > 内置默认值。修改 ini 后需重启进程/容器方生效。"""

import configparser
import os
import warnings
from typing import Dict, List, Optional, Union

_DEFAULT_SECRET = "123456-bb6b-4889-a715-d9eb2d1925cc"

# 可执行文件所在项目根：.../visionai/config/settings.py -> /app
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
        if not read or "visionai" not in cp:
            return {}
        return {k.lower().strip(): v.strip() for k, v in cp["visionai"].items() if v is not None}
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

# 吸烟（行为层：人物裁剪 + ONNX 二分类；需配置 SMOKING_MODEL_PATH）
SMOKING_MODEL_PATH = _cfg_path("SMOKING_MODEL_PATH", "")
# 与导出模型一致：imagenet（ResNet 等）| vit_hf（HuggingFace ViT 常用 0.5/0.5，见 scripts/export_smoking_onnx.py）
SMOKING_PREPROCESS = _cfg_str("SMOKING_PREPROCESS", "imagenet").strip().lower()
SMOKING_CONF_THRESHOLD = _cfg_float("SMOKING_CONF_THRESHOLD", 0.5)
SMOKING_INPUT_SIZE = max(32, _cfg_int("SMOKING_INPUT_SIZE", 224))
SMOKING_PERSON_PAD_RATIO = max(0.0, _cfg_float("SMOKING_PERSON_PAD_RATIO", 0.15))
SMOKING_MIN_DURATION_SEC = max(0.0, _cfg_float("SMOKING_MIN_DURATION_SEC", 0.5))
SMOKING_MAX_PERSONS_PER_FRAME = max(1, _cfg_int("SMOKING_MAX_PERSONS_PER_FRAME", 8))
SMOKING_POSITIVE_CLASS_INDEX = max(0, _cfg_int("SMOKING_POSITIVE_CLASS_INDEX", 1))
# 每轮吸烟 ONNX 推理后打印各人体置信度（调试用；生产可 smoking_log_scores = false）
SMOKING_LOG_SCORES = _cfg_bool("SMOKING_LOG_SCORES", True)
# 可选：专训单/多类「香烟」小目标 YOLO（.pt）；非空时仅当该帧人物与香烟框有关联时才做下方 ViT 吸烟二分类，降低手靠近脸误报
SMOKING_CIGARETTE_DETECTOR_PATH = _cfg_path("SMOKING_CIGARETTE_DETECTOR_PATH", "")
SMOKING_CIGARETTE_DETECTOR_CONF = max(0.05, min(0.99, _cfg_float("SMOKING_CIGARETTE_DETECTOR_CONF", 0.35)))
# 逗号分隔类 id，默认 0（单类 cigarette）；留空则表示不限制类别
SMOKING_CIGARETTE_CLASS_IDS = _cfg_str("SMOKING_CIGARETTE_CLASS_IDS", "").strip()
# 专训单类「smoking」等 YOLO（.pt）：与人物框重叠即告警，不跑 ViT ONNX（见 smoking_cigarette_detector_path）
SMOKING_YOLO_DIRECT = _cfg_bool("SMOKING_YOLO_DIRECT", False)
SMOKING_REQUIRE_PERSON_OVERLAP = _cfg_bool("SMOKING_REQUIRE_PERSON_OVERLAP", False)

# ---------- 专模扩展检测（models/ 下 .pt / .onnx；与 COCO 主检测并行）----------
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

FACE_MODEL_PATH = _cfg_path("FACE_MODEL_PATH", _models_default("face_detection.onnx"))
FACE_MODEL_CONF = max(0.05, min(0.99, _cfg_float("FACE_MODEL_CONF", DEDICATED_DEFAULT_CONF)))
FACE_MIN_DURATION_SEC = max(0.0, _cfg_float("FACE_MIN_DURATION_SEC", 0.0))

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

FALL_MODEL_PATH = _cfg_path("FALL_MODEL_PATH", _models_default("fall_detection.onnx"))
FALL_MODEL_CONF = max(0.05, min(0.99, _cfg_float("FALL_MODEL_CONF", DEDICATED_DEFAULT_CONF)))
FALL_SCORE_THRESHOLD = max(
    0.05, min(0.99, _cfg_float("FALL_SCORE_THRESHOLD", DEDICATED_DEFAULT_SCORE_THRESHOLD))
)
FALL_MIN_DURATION_SEC = max(
    0.0, _cfg_float("FALL_MIN_DURATION_SEC", DEDICATED_DEFAULT_MIN_DURATION_SEC)
)

FLAME_MODEL_PATH = _cfg_path("FLAME_MODEL_PATH", _models_default("flame.pt"))
FLAME_MODEL_CONF = max(0.05, min(0.99, _cfg_float("FLAME_MODEL_CONF", DEDICATED_DEFAULT_CONF)))
FLAME_MIN_DURATION_SEC = max(0.0, _cfg_float("FLAME_MIN_DURATION_SEC", 0.5))

LICENSE_PLATE_MODEL_PATH = _cfg_path(
    "LICENSE_PLATE_MODEL_PATH", _models_default("license_plate_detection.onnx")
)
LICENSE_PLATE_MODEL_CONF = max(
    0.05, min(0.99, _cfg_float("LICENSE_PLATE_MODEL_CONF", DEDICATED_DEFAULT_CONF))
)
LICENSE_PLATE_MIN_DURATION_SEC = max(
    0.0, _cfg_float("LICENSE_PLATE_MIN_DURATION_SEC", 0.0)
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

MASK_MODEL_PATH = _cfg_path("MASK_MODEL_PATH", _models_default("mask.onnx"))
MASK_MODEL_CONF = max(0.05, min(0.99, _cfg_float("MASK_MODEL_CONF", DEDICATED_DEFAULT_CONF)))
MASK_SCORE_THRESHOLD = max(
    0.05, min(0.99, _cfg_float("MASK_SCORE_THRESHOLD", DEDICATED_DEFAULT_SCORE_THRESHOLD))
)
MASK_MIN_DURATION_SEC = max(
    0.0, _cfg_float("MASK_MIN_DURATION_SEC", DEDICATED_DEFAULT_MIN_DURATION_SEC)
)

REFLECTIVE_VEST_MODEL_PATH = _cfg_path(
    "REFLECTIVE_VEST_MODEL_PATH", _models_default("reflective_vest.pt")
)
REFLECTIVE_VEST_MODEL_CONF = max(
    0.05, min(0.99, _cfg_float("REFLECTIVE_VEST_MODEL_CONF", DEDICATED_DEFAULT_CONF))
)
REFLECTIVE_VEST_SCORE_THRESHOLD = max(
    0.05,
    min(0.99, _cfg_float("REFLECTIVE_VEST_SCORE_THRESHOLD", DEDICATED_DEFAULT_SCORE_THRESHOLD)),
)
REFLECTIVE_VEST_MIN_DURATION_SEC = max(
    0.0, _cfg_float("REFLECTIVE_VEST_MIN_DURATION_SEC", DEDICATED_DEFAULT_MIN_DURATION_SEC)
)

ROAD_WATERLOGGING_MODEL_PATH = _cfg_path(
    "ROAD_WATERLOGGING_MODEL_PATH", _models_default("road_waterlogging.onnx")
)
ROAD_WATERLOGGING_MODEL_CONF = max(
    0.05, min(0.99, _cfg_float("ROAD_WATERLOGGING_MODEL_CONF", DEDICATED_DEFAULT_CONF))
)
ROAD_WATERLOGGING_MIN_DURATION_SEC = max(
    0.0, _cfg_float("ROAD_WATERLOGGING_MIN_DURATION_SEC", 0.5)
)

SAFETY_HELMET_MODEL_PATH = _cfg_path(
    "SAFETY_HELMET_MODEL_PATH", _models_default("safety_helmet.pt")
)
SAFETY_HELMET_MODEL_CONF = max(
    0.05, min(0.99, _cfg_float("SAFETY_HELMET_MODEL_CONF", DEDICATED_DEFAULT_CONF))
)
SAFETY_HELMET_SCORE_THRESHOLD = max(
    0.05,
    min(0.99, _cfg_float("SAFETY_HELMET_SCORE_THRESHOLD", DEDICATED_DEFAULT_SCORE_THRESHOLD)),
)
SAFETY_HELMET_MIN_DURATION_SEC = max(
    0.0, _cfg_float("SAFETY_HELMET_MIN_DURATION_SEC", DEDICATED_DEFAULT_MIN_DURATION_SEC)
)

SLEEPING_MODEL_PATH = _cfg_path("SLEEPING_MODEL_PATH", _models_default("sleeping.pt"))
SLEEPING_MODEL_CONF = max(
    0.05, min(0.99, _cfg_float("SLEEPING_MODEL_CONF", DEDICATED_DEFAULT_CONF))
)
SLEEPING_SCORE_THRESHOLD = max(
    0.05, min(0.99, _cfg_float("SLEEPING_SCORE_THRESHOLD", DEDICATED_DEFAULT_SCORE_THRESHOLD))
)
SLEEPING_MIN_DURATION_SEC = max(
    0.0, _cfg_float("SLEEPING_MIN_DURATION_SEC", DEDICATED_DEFAULT_MIN_DURATION_SEC)
)

# 保存
SAVE_DIR = _cfg_path("SAVE_DIR", "./snapshots")
SAVE_FORMAT = "%Y%m%d_%H%M%S_%f.jpg"
SAVE_INTERVAL = _cfg_int("SAVE_INTERVAL", 10)

# YOLO
YOLO_MODEL = _cfg_path("YOLO_MODEL", _models_default("yolov8n.pt"))

# 打电话 / 玩手机：YOLO+COCO overlap 后用工单人体姿态（YOLOv8 pose）把手机中心与耳根/口鼻/手腕比距分类
POSE_MODEL = _cfg_path("POSE_MODEL", _models_default("yolov8n-pose.pt"))
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

# YOLO / Ultralytics 推理设备：（主检测 + yolov8-pose）见 `yolo_inference_device()`
YOLO_DEVICE = (_lookup_str("YOLO_DEVICE") or "").strip()
# ONNX（吸烟等）：cpu | cuda_first
ONNX_PROVIDER = (_lookup_str("ONNX_PROVIDER") or "cpu").strip().lower() or "cpu"


def yolo_inference_device() -> Optional[Union[str, int]]:
    """传给 Ultralytics `model(..., device=...)`；None 表示不传参（沿用库默认 Auto）。"""
    raw = YOLO_DEVICE.strip()
    if not raw:
        return None
    lo = raw.lower()
    if lo in ("auto", "none", "default"):
        return None
    if lo == "cpu":
        return "cpu"
    if raw.isdigit():
        try:
            return int(raw)
        except ValueError:
            return raw
    return raw


def onnx_runtime_providers_ordered() -> List[str]:
    """InferenceSession(..., providers=...) 顺序；运行时探测 onnxruntime 是否含 CUDA EP。"""
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
                "onnx_provider 为 CUDA 首选但 onnxruntime 无 CUDAExecutionProvider "
                "（通常需 onnxruntime-gpu），已退回 CPUExecutionProvider",
                stacklevel=2,
            )
            return ["CPUExecutionProvider"]
        return ["CUDAExecutionProvider", "CPUExecutionProvider"]

    warnings.warn(
        f"未知的 onnx_provider={pref!r}，改用 CPUExecutionProvider",
        stacklevel=2,
    )
    return ["CPUExecutionProvider"]
