"""项目配置：环境变量 > config/config.ini > 内置默认值。修改 ini 后需重启进程/容器方生效。"""

import configparser
import os
import warnings
from typing import Dict, List, Optional, Union

_DEFAULT_SECRET = "123456-bb6b-4889-a715-d9eb2d1925cc"

# 可执行文件所在项目根：.../visionai/config/settings.py -> /app
_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir, os.pardir))
_DEFAULT_INI = os.path.join(_ROOT, "config", "config.ini")


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
SMOKING_MODEL_PATH = _cfg_str("SMOKING_MODEL_PATH", "")
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
SMOKING_CIGARETTE_DETECTOR_PATH = _cfg_str("SMOKING_CIGARETTE_DETECTOR_PATH", "").strip()
SMOKING_CIGARETTE_DETECTOR_CONF = max(0.05, min(0.99, _cfg_float("SMOKING_CIGARETTE_DETECTOR_CONF", 0.35)))
# 逗号分隔类 id，默认 0（单类 cigarette）；留空则表示不限制类别
SMOKING_CIGARETTE_CLASS_IDS = _cfg_str("SMOKING_CIGARETTE_CLASS_IDS", "").strip()

# 保存
SAVE_DIR = _cfg_str("SAVE_DIR", "./snapshots")
SAVE_FORMAT = "%Y%m%d_%H%M%S_%f.jpg"
SAVE_INTERVAL = _cfg_int("SAVE_INTERVAL", 10)

# YOLO
YOLO_MODEL = _cfg_str("YOLO_MODEL", "yolov8n.pt")

# 打电话 / 玩手机：YOLO+COCO overlap 后用工单人体姿态（YOLOv8 pose）把手机中心与耳根/口鼻/手腕比距分类
POSE_MODEL = _cfg_str("POSE_MODEL", "yolov8n-pose.pt")
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
LOG_DIR = _cfg_str("LOG_DIR", "./logs")

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
PREVIEW_HLS_ROOT = _cfg_str("PREVIEW_HLS_ROOT", "./hls-preview")
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
