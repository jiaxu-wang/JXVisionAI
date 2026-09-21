"""
运行时配置。

优先级：环境变量 > ``config/config.ini``（多分节，映射为规范键）> 本文件内置默认。
修改 ini 或环境变量后需重启进程。可用 ``VISIONAI_CONFIG`` 指定其它 ini 路径。

分节示例：``[basic]`` ``[redis]`` ``[minio]`` ``[email]`` ``[models]`` ``[preview]`` ``[integration]``。
``[ui] language`` 同时作为管理端首次访问默认语言，以及告警推送（webhook / 邮件）类型展示名的语言；检测协议值与 Redis 仍用中文。
仍兼容旧版单节 ``[visionai]``。Redis/对象存储等键前缀沿用历史标识 ``visionai``。
"""

import configparser
import os
import warnings
from typing import Dict, List, Optional, Union

from visionai.config.ini_sections import flatten_configparser, has_valid_sections

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
    return ""


# Flask 登录口令（VISIONAI_SECRET / [basic] visionai_secret）
SECRET = _secret()


def _session_secret() -> str:
    v = (os.environ.get("VISIONAI_SESSION_SECRET") or "").strip()
    if v:
        return v
    ini_v = (_INI.get("session_secret") or "").strip()
    if ini_v:
        return ini_v
    if SECRET:
        return SECRET
    return "visionai-dev-only-set-VISIONAI_SESSION_SECRET"


SESSION_SECRET = _session_secret()
ALLOW_PROCESS_RESTART = _cfg_bool("VISIONAI_ALLOW_PROCESS_RESTART", False)

# 检测
DETECTION_INTERVAL = _cfg_int("DETECTION_INTERVAL", 15)
CONF_THRESHOLD = _cfg_float("CONF_THRESHOLD", 0.5)
# 一轮内短窗抽帧：frames=1 或 duration_ms=0 时退回「到点检 1 帧」
DETECT_BURST_DURATION_MS = max(0, _cfg_int("DETECT_BURST_DURATION_MS", 500))
DETECT_BURST_FRAMES = max(1, min(60, _cfg_int("DETECT_BURST_FRAMES", 15)))
DETECT_BURST_MIN_FRAMES = max(1, min(DETECT_BURST_FRAMES, _cfg_int("DETECT_BURST_MIN_FRAMES", 1)))
DETECT_BURST_HIT_RATIO = max(0.0, min(1.0, _cfg_float("DETECT_BURST_HIT_RATIO", 0.4)))

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

# 车牌识别：检测框（专模 plate）+ OCR 读号 + 车牌库比对
PLATE_DET_MODEL_PATH = _cfg_path(
    "PLATE_DET_MODEL_PATH",
    os.path.join(PROJECT_ROOT, "models", "specialists", "plate", "model.onnx"),
)
PLATE_DET_CONF = max(0.05, min(0.99, _cfg_float("PLATE_DET_CONF", DEDICATED_DEFAULT_CONF)))
PLATE_RECOGNITION_MIN_DURATION_SEC = max(
    0.0, _cfg_float("PLATE_RECOGNITION_MIN_DURATION_SEC", 1.0)
)
PLATE_RECOGNITION_OCR_MIN_CONF = max(
    0.05, min(0.99, _cfg_float("PLATE_RECOGNITION_OCR_MIN_CONF", 0.35))
)
PLATE_RECOGNITION_MAX_PLATES_PER_FRAME = max(
    1, _cfg_int("PLATE_RECOGNITION_MAX_PLATES_PER_FRAME", 5)
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

# YOLO26 主检权重（[models] yolo_model）。
# 可选 models/yolo26{n,s,m,l,x}.pt — 越大通常越准越慢；改配置后须重启进程。
# 下载：scripts/download_yolo26.sh 或 docs/getting-started.md
YOLO_MODEL = _cfg_path("YOLO_MODEL", _models_default("yolo26s.pt"))

# ---------- 主检后端 [infer]（见 docs/architecture.md）----------
# python：Ultralytics 直接加载 YOLO_MODEL（.pt），换档位最方便
# cpp：走 visionai-inferd（ONNX 仓库 models/repo/…），多路共享引擎
INFER_BACKEND = _cfg_str("INFER_BACKEND", "python").strip().lower()
INFER_ENDPOINT = _cfg_str("INFER_ENDPOINT", "unix:///tmp/visionai-inferd.sock")
INFER_MODEL_REPOSITORY = _cfg_path("INFER_MODEL_REPOSITORY", "models/repo")
INFER_PRIMARY_NAME = _cfg_str("INFER_PRIMARY_NAME", "primary")
INFER_PRIMARY_VERSION = _cfg_str("INFER_PRIMARY_VERSION", "1")
# daemon 不可用：fail=本周期失败；fallback_python=回退 Ultralytics（开发用）
INFER_ON_DAEMON_ERROR = _cfg_str("INFER_ON_DAEMON_ERROR", "fail").strip().lower()
INFER_DEVICE = _cfg_str("INFER_DEVICE", "")  # 空则继承 [basic] inference_device

# ---------- ZLMediaKit 媒体面 [zlm] ----------
ZLM_ENABLED = _cfg_bool("ZLM_ENABLED", False)
ZLM_API_BASE = _cfg_str("ZLM_API_BASE", "http://127.0.0.1:8080").strip()
ZLM_SECRET = _cfg_str("ZLM_SECRET", "").strip()
ZLM_VHOST = _cfg_str("ZLM_VHOST", "__defaultVhost__").strip() or "__defaultVhost__"
ZLM_APP = _cfg_str("ZLM_APP", "jvai").strip() or "jvai"
ZLM_RTSP_PORT = max(1, min(65535, _cfg_int("ZLM_RTSP_PORT", 8554)))
ZLM_HTTP_PORT = max(1, min(65535, _cfg_int("ZLM_HTTP_PORT", 8080)))
ZLM_PREFER_LOCAL_PULL = _cfg_bool("ZLM_PREFER_LOCAL_PULL", True)
ZLM_FALLBACK_DIRECT_RTSP = _cfg_bool("ZLM_FALLBACK_DIRECT_RTSP", True)
ZLM_PUBLIC_HOST = _cfg_str("ZLM_PUBLIC_HOST", "127.0.0.1").strip() or "127.0.0.1"
# WebRTC ICE 端口（须与 config/zlm/config.ini [rtc] port 及 docker 映射一致）
ZLM_RTC_PORT = max(1, min(65535, _cfg_int("ZLM_RTC_PORT", 8000)))
# worker 容器内经 compose 网络拉 ZLM 本地 RTSP：主机名 + 容器内端口（如 zlmediakit:554）
# 空则 local_rtsp 仍用 127.0.0.1 + ZLM_RTSP_PORT（宿主机 ./start.sh 场景）
ZLM_PULL_HOST = _cfg_str("ZLM_PULL_HOST", "").strip()
_zlm_pull_port = _cfg_int("ZLM_PULL_RTSP_PORT", 0)
ZLM_PULL_RTSP_PORT = (
    max(1, min(65535, _zlm_pull_port)) if _zlm_pull_port > 0 else ZLM_RTSP_PORT
)

# 告警异步队列
ALERT_QUEUE_ENABLED = _cfg_bool("ALERT_QUEUE_ENABLED", True)
ALERT_QUEUE_MAX_LEN = max(100, _cfg_int("ALERT_QUEUE_MAX_LEN", 2000))
ALERT_QUEUE_BLOCK_SEC = max(1, _cfg_int("ALERT_QUEUE_BLOCK_SEC", 5))

# ---------- 第三方开放集成 [integration] ----------
# 机对机 API 密钥（请求头 X-Api-Key）；空则开放 API 一律 401
OPEN_API_KEY = _cfg_str("OPEN_API_KEY", "").strip()
# 告警 image_url 的对外根（无尾斜杠），如 http://JX_HOST:15000
PUBLIC_BASE_URL = _cfg_str("PUBLIC_BASE_URL", "").strip().rstrip("/")
# 全局告警 Webhook；与每路 URL 合并去重
OUTBOUND_WEBHOOK_URL = _cfg_str("OUTBOUND_WEBHOOK_URL", "").strip()
# 允许 iframe 本管理页的父源（空格/逗号分隔）；空则不写 CSP
EMBED_FRAME_ANCESTORS = _cfg_str("EMBED_FRAME_ANCESTORS", "").strip()
# 侧栏「平台接入」嵌入页 URL；空则显示未接入
PLATFORM_EMBED_URL = _cfg_str("PLATFORM_EMBED_URL", "").strip()

# 多 worker 流租约（P3 HA）
STREAM_LEASE_ENABLED = _cfg_bool("STREAM_LEASE_ENABLED", False)
STREAM_LEASE_TTL_SEC = max(5, _cfg_int("STREAM_LEASE_TTL_SEC", 30))
STREAM_LEASE_RENEW_SEC = max(2, min(STREAM_LEASE_TTL_SEC - 1, _cfg_int("STREAM_LEASE_RENEW_SEC", 10)))
WORKER_ID = _cfg_str("WORKER_ID", "").strip()
# 单路解码/推理无进展超过该秒数则标离线并释放线程槽，避免拖死整个 worker
STREAM_WATCHDOG_SEC = max(15, _cfg_int("STREAM_WATCHDOG_SEC", 120))

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

# 应用时区（IANA）：告警落库与管理端展示；改后需重启
# 优先级：VISIONAI_TIMEZONE > TIMEZONE > config.ini [basic] timezone > TZ > Asia/Shanghai
def _resolve_app_timezone() -> str:
    for env_k in ("VISIONAI_TIMEZONE", "TIMEZONE"):
        v = os.environ.get(env_k)
        if v and str(v).strip():
            return str(v).strip()
    ini_tz = _INI.get("timezone")
    if ini_tz and str(ini_tz).strip():
        return str(ini_tz).strip()
    v = os.environ.get("TZ")
    if v and str(v).strip():
        return str(v).strip()
    return "Asia/Shanghai"


APP_TIMEZONE = _resolve_app_timezone()
try:
    from zoneinfo import ZoneInfo

    ZoneInfo(APP_TIMEZONE)  # 校验 IANA 名
except Exception:  # noqa: BLE001
    warnings.warn(
        f"无效时区 {APP_TIMEZONE!r}，已回退 UTC；请改 [basic] timezone 或 VISIONAI_TIMEZONE",
        stacklevel=1,
    )
    APP_TIMEZONE = "UTC"

# Redis
REDIS_HOST = _cfg_str("REDIS_HOST", "127.0.0.1")
REDIS_PORT = _cfg_int("REDIS_PORT", 16379)
REDIS_PASSWORD = _cfg_str("REDIS_PASSWORD", "")
REDIS_DB = _cfg_int("REDIS_DB", 0)
REDIS_KEY_PREFIX = _cfg_str("REDIS_KEY_PREFIX", "visionai/")

# 检测记录保留（天，至少 1）：Redis 检测 Hash 的 TTL、S3/MinIO 截图生命周期均用此值
DETECTION_RETENTION_DAYS = max(1, _cfg_int("DETECTION_RETENTION_DAYS", 1))

# 管理端
AUTO_REFRESH_INTERVAL = _cfg_int("AUTO_REFRESH_INTERVAL", 20)

# 检测框标签字号（[preview]）：>0 固定像素；0=按帧短边×ratio 再夹在 min~max
LABEL_FONT_PX = max(0, _cfg_int("LABEL_FONT_PX", 0))
LABEL_FONT_MIN_PX = max(12, _cfg_int("LABEL_FONT_MIN_PX", 40))
LABEL_FONT_MAX_PX = max(LABEL_FONT_MIN_PX, _cfg_int("LABEL_FONT_MAX_PX", 96))
LABEL_FONT_RATIO = max(0.01, min(0.2, _cfg_float("LABEL_FONT_RATIO", 0.055)))

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
