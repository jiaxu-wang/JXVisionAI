"""
config.ini 分节与规范键映射。

- 规范键（canonical）：与环境变量小写一致，如 ``redis_host``、``smtp_host``。
- 分节内可用短键（如 ``[redis]`` 下 ``host``）；读取时映射为规范键。
- 仍兼容旧版单节 ``[visionai]``（键即为规范键）。
"""

from __future__ import annotations

from typing import Dict, Optional, Tuple

# 节别名 → 规范节名
SECTION_ALIASES: Dict[str, str] = {
    "app": "basic",
    "storage": "minio",
    "s3": "minio",
    "smtp": "email",
    "mail": "email",
}

LEGACY_SECTION = "visionai"

# 至少存在其一即视为合法配置文件
VALID_ROOT_SECTIONS = frozenset(
    {
        "basic",
        "app",
        "redis",
        "minio",
        "storage",
        "s3",
        "email",
        "smtp",
        "mail",
        "models",
        "preview",
        "infer",
        "zlm",
        "visionai",
    }
)

# 规范节 → { 文件内键 → 规范键 }
_SECTION_LOCAL_TO_CANONICAL: Dict[str, Dict[str, str]] = {
    "redis": {
        "host": "redis_host",
        "port": "redis_port",
        "password": "redis_password",
        "db": "redis_db",
        "key_prefix": "redis_key_prefix",
        "redis_host": "redis_host",
        "redis_port": "redis_port",
        "redis_password": "redis_password",
        "redis_db": "redis_db",
        "redis_key_prefix": "redis_key_prefix",
    },
    "minio": {
        "enabled": "object_storage_enabled",
        "keep_local": "object_storage_keep_local",
        "endpoint_url": "s3_endpoint_url",
        "access_key_id": "s3_access_key_id",
        "secret_access_key": "s3_secret_access_key",
        "bucket": "s3_bucket",
        "region": "s3_region",
        "use_ssl": "s3_use_ssl",
        "path_prefix": "s3_path_prefix",
        "addressing_style": "s3_addressing_style",
        "lifecycle_enabled": "s3_lifecycle_enabled",
        "object_storage_enabled": "object_storage_enabled",
        "object_storage_keep_local": "object_storage_keep_local",
        "s3_endpoint_url": "s3_endpoint_url",
        "s3_access_key_id": "s3_access_key_id",
        "s3_secret_access_key": "s3_secret_access_key",
        "s3_bucket": "s3_bucket",
        "s3_region": "s3_region",
        "s3_use_ssl": "s3_use_ssl",
        "s3_path_prefix": "s3_path_prefix",
        "s3_addressing_style": "s3_addressing_style",
        "s3_lifecycle_enabled": "s3_lifecycle_enabled",
    },
    "email": {
        "alert_enabled": "smtp_alert_enabled",
        "host": "smtp_host",
        "port": "smtp_port",
        "use_ssl": "smtp_use_ssl",
        "use_tls": "smtp_use_tls",
        "user": "smtp_user",
        "password": "smtp_password",
        "from": "smtp_from",
        "timeout": "smtp_timeout",
        "attach_max_bytes": "smtp_alert_attach_max_bytes",
        "smtp_alert_enabled": "smtp_alert_enabled",
        "smtp_host": "smtp_host",
        "smtp_port": "smtp_port",
        "smtp_use_ssl": "smtp_use_ssl",
        "smtp_use_tls": "smtp_use_tls",
        "smtp_user": "smtp_user",
        "smtp_password": "smtp_password",
        "smtp_from": "smtp_from",
        "smtp_timeout": "smtp_timeout",
        "smtp_alert_attach_max_bytes": "smtp_alert_attach_max_bytes",
    },
    "infer": {
        "backend": "infer_backend",
        "endpoint": "infer_endpoint",
        "model_repository": "infer_model_repository",
        "primary_name": "infer_primary_name",
        "primary_version": "infer_primary_version",
        "on_daemon_error": "infer_on_daemon_error",
        "device": "infer_device",
        "infer_backend": "infer_backend",
        "infer_endpoint": "infer_endpoint",
        "infer_model_repository": "infer_model_repository",
        "infer_primary_name": "infer_primary_name",
        "infer_primary_version": "infer_primary_version",
        "infer_on_daemon_error": "infer_on_daemon_error",
        "infer_device": "infer_device",
    },
    "zlm": {
        "enabled": "zlm_enabled",
        "api_base": "zlm_api_base",
        "secret": "zlm_secret",
        "vhost": "zlm_vhost",
        "app": "zlm_app",
        "rtsp_port": "zlm_rtsp_port",
        "http_port": "zlm_http_port",
        "prefer_local_pull": "zlm_prefer_local_pull",
        "fallback_direct_rtsp": "zlm_fallback_direct_rtsp",
        "public_host": "zlm_public_host",
        "rtc_port": "zlm_rtc_port",
        "pull_host": "zlm_pull_host",
        "pull_rtsp_port": "zlm_pull_rtsp_port",
        "zlm_enabled": "zlm_enabled",
        "zlm_api_base": "zlm_api_base",
        "zlm_secret": "zlm_secret",
        "zlm_vhost": "zlm_vhost",
        "zlm_app": "zlm_app",
        "zlm_rtsp_port": "zlm_rtsp_port",
        "zlm_http_port": "zlm_http_port",
        "zlm_prefer_local_pull": "zlm_prefer_local_pull",
        "zlm_fallback_direct_rtsp": "zlm_fallback_direct_rtsp",
        "zlm_public_host": "zlm_public_host",
        "zlm_rtc_port": "zlm_rtc_port",
        "zlm_pull_host": "zlm_pull_host",
        "zlm_pull_rtsp_port": "zlm_pull_rtsp_port",
    },
}

# 规范键 → 写入时的 (节, 文件内键)；basic/models/preview 默认同名
CANONICAL_WRITE: Dict[str, Tuple[str, str]] = {
    # basic
    "visionai_secret": ("basic", "visionai_secret"),
    "secret": ("basic", "visionai_secret"),
    "detection_interval": ("basic", "detection_interval"),
    "conf_threshold": ("basic", "conf_threshold"),
    "save_dir": ("basic", "save_dir"),
    "save_interval": ("basic", "save_interval"),
    "log_level": ("basic", "log_level"),
    "log_dir": ("basic", "log_dir"),
    "log_retention_days": ("basic", "log_retention_days"),
    "auto_refresh_interval": ("basic", "auto_refresh_interval"),
    "detection_retention_days": ("basic", "detection_retention_days"),
    "timezone": ("basic", "timezone"),
    "inference_device": ("basic", "inference_device"),
    "yolo_device": ("basic", "yolo_device"),
    "onnx_provider": ("basic", "onnx_provider"),
    # redis
    "redis_host": ("redis", "host"),
    "redis_port": ("redis", "port"),
    "redis_password": ("redis", "password"),
    "redis_db": ("redis", "db"),
    "redis_key_prefix": ("redis", "key_prefix"),
    # minio
    "object_storage_enabled": ("minio", "enabled"),
    "object_storage_keep_local": ("minio", "keep_local"),
    "s3_endpoint_url": ("minio", "endpoint_url"),
    "s3_access_key_id": ("minio", "access_key_id"),
    "s3_secret_access_key": ("minio", "secret_access_key"),
    "s3_bucket": ("minio", "bucket"),
    "s3_region": ("minio", "region"),
    "s3_use_ssl": ("minio", "use_ssl"),
    "s3_path_prefix": ("minio", "path_prefix"),
    "s3_addressing_style": ("minio", "addressing_style"),
    "s3_lifecycle_enabled": ("minio", "lifecycle_enabled"),
    # email
    "smtp_alert_enabled": ("email", "alert_enabled"),
    "smtp_host": ("email", "host"),
    "smtp_port": ("email", "port"),
    "smtp_use_ssl": ("email", "use_ssl"),
    "smtp_use_tls": ("email", "use_tls"),
    "smtp_user": ("email", "user"),
    "smtp_password": ("email", "password"),
    "smtp_from": ("email", "from"),
    "smtp_timeout": ("email", "timeout"),
    "smtp_alert_attach_max_bytes": ("email", "attach_max_bytes"),
    # preview（流预览仅 ZLM WebRTC；本节保留检测框标签字号）
    "label_font_px": ("preview", "label_font_px"),
    "label_font_min_px": ("preview", "label_font_min_px"),
    "label_font_max_px": ("preview", "label_font_max_px"),
    "label_font_ratio": ("preview", "label_font_ratio"),
}

# models 节：下列规范键写入 [models]，文件内键与规范键同名
_MODELS_KEYS = (
    "yolo_model",
    "pose_model",
    "pose_for_phone_enabled",
    "phone_pose_kp_min_conf",
    "phone_call_head_ratio",
    "phone_play_wrist_ratio",
    "phone_vertical_boundary",
    "gather_min_persons",
    "gather_min_duration_sec",
    "face_recog_model_root",
    "face_recog_det_size",
    "face_recog_det_model_path",
    "face_recog_embed_model_path",
    "face_recog_genderage_model_path",
    "face_recog_genderage_enabled",
    "face_recog_det_conf",
    "face_recog_rotate",
    "face_recognition_threshold",
    "face_recognition_min_duration_sec",
    "face_library_dir",
    "face_recognition_max_faces_per_frame",
    "plate_det_model_path",
    "plate_det_conf",
    "plate_recognition_min_duration_sec",
    "plate_recognition_ocr_min_conf",
    "plate_recognition_max_plates_per_frame",
    "make_call_model_path",
    "make_call_model_conf",
    "make_call_score_threshold",
    "make_call_min_duration_sec",
    "make_call_use_dedicated",
    "make_call_require_person_overlap",
    "dedicated_max_persons_per_frame",
    "dedicated_default_conf",
    "dedicated_default_score_threshold",
    "dedicated_default_min_duration_sec",
)

for _k in _MODELS_KEYS:
    CANONICAL_WRITE[_k] = ("models", _k)

for _k, _file_key in (
    ("infer_backend", "backend"),
    ("infer_endpoint", "endpoint"),
    ("infer_model_repository", "model_repository"),
    ("infer_primary_name", "primary_name"),
    ("infer_primary_version", "primary_version"),
    ("infer_on_daemon_error", "on_daemon_error"),
    ("infer_device", "device"),
):
    CANONICAL_WRITE[_k] = ("infer", _file_key)

for _k, _file_key in (
    ("zlm_enabled", "enabled"),
    ("zlm_api_base", "api_base"),
    ("zlm_secret", "secret"),
    ("zlm_vhost", "vhost"),
    ("zlm_app", "app"),
    ("zlm_rtsp_port", "rtsp_port"),
    ("zlm_http_port", "http_port"),
    ("zlm_prefer_local_pull", "prefer_local_pull"),
    ("zlm_fallback_direct_rtsp", "fallback_direct_rtsp"),
    ("zlm_public_host", "public_host"),
    ("zlm_rtc_port", "rtc_port"),
    ("zlm_pull_host", "pull_host"),
    ("zlm_pull_rtsp_port", "pull_rtsp_port"),
):
    CANONICAL_WRITE[_k] = ("zlm", _file_key)


def normalize_section(section: str) -> str:
    s = (section or "").strip().lower()
    return SECTION_ALIASES.get(s, s)


def canonicalize(section: str, key: str) -> str:
    """将 (节, 文件内键) 转为规范键。"""
    sec = normalize_section(section)
    k = (key or "").strip().lower()
    if not k:
        return k
    if sec == LEGACY_SECTION:
        return k
    mapping = _SECTION_LOCAL_TO_CANONICAL.get(sec)
    if mapping and k in mapping:
        return mapping[k]
    return k


def write_location(canonical_key: str) -> Tuple[str, str]:
    """规范键 → 写入用的 (节, 文件内键)。"""
    ck = (canonical_key or "").strip().lower()
    if ck in CANONICAL_WRITE:
        return CANONICAL_WRITE[ck]
    return ("basic", ck)


def has_valid_sections(section_names) -> bool:
    for name in section_names:
        if normalize_section(name) in VALID_ROOT_SECTIONS or name.strip().lower() in VALID_ROOT_SECTIONS:
            return True
        if name.strip().lower() == LEGACY_SECTION:
            return True
    return False


def flatten_configparser(cp) -> Dict[str, str]:
    """把多分节 ConfigParser 打成 规范键→值。后写覆盖先写。"""
    out: Dict[str, str] = {}
    for section in cp.sections():
        for k, v in cp.items(section, raw=True):
            if v is None:
                continue
            canon = canonicalize(section, k)
            if not canon:
                continue
            out[canon] = str(v).strip()
    return out


def preferred_ini_key(canonical_key: str) -> str:
    _, local = write_location(canonical_key)
    return local


def preferred_section(canonical_key: str) -> str:
    sec, _ = write_location(canonical_key)
    return sec
