"""系统设置页：配置单元与字段 schema（规范键与 config.ini 分节对应）。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Tuple

from visionai.config.ini_sections import preferred_ini_key, preferred_section

# type: text | int | float | bool | password | timezone | readonly

_PATH_HINT = "相对项目根；也可用绝对路径"
_PATH_HINT_EN = "Relative to the project root; absolute paths also work"


def _path_comment(extra: str = "") -> str:
    if extra:
        return f"{extra}；{_PATH_HINT}"
    return _PATH_HINT


def _path_comment_en(extra: str = "") -> str:
    if extra:
        return f"{extra}; {_PATH_HINT_EN}"
    return _PATH_HINT_EN


@dataclass(frozen=True)
class ConfigField:
    key: str
    label: str
    field_type: str = "text"
    editable: bool = True
    comment: str = ""
    readonly: bool = False
    relative_path: bool = False
    # ini 节名；空则按 ini_sections.preferred_section(key)
    section: str = ""
    # 节内短键；空则按 preferred_ini_key(key)
    ini_key: str = ""
    label_en: str = ""
    comment_en: str = ""

    def resolved_section(self) -> str:
        return self.section or preferred_section(self.key)

    def resolved_ini_key(self) -> str:
        return self.ini_key or preferred_ini_key(self.key)


@dataclass(frozen=True)
class ConfigUnit:
    id: str
    title: str
    description: str
    fields: Tuple[ConfigField, ...]
    title_en: str = ""
    description_en: str = ""


def _f(
    key: str,
    label: str,
    field_type: str = "text",
    *,
    comment: str = "",
    label_en: str = "",
    comment_en: str = "",
    relative_path: bool = False,
    section: str = "",
    ini_key: str = "",
) -> ConfigField:
    return ConfigField(
        key,
        label,
        field_type,
        comment=comment,
        relative_path=relative_path,
        section=section or preferred_section(key),
        ini_key=ini_key or preferred_ini_key(key),
        label_en=label_en or label,
        comment_en=comment_en or comment,
    )


CONFIG_UNITS: Tuple[ConfigUnit, ...] = (
    ConfigUnit(
        id="meta",
        title="配置说明",
        title_en="About this config",
        description="以下为只读说明；修改其它单元后保存并重启，全配置生效。",
        description_en="Read-only notes. After you change other units, save and restart for all settings to take effect.",
        fields=(
            ConfigField(
                "_priority",
                "生效优先级",
                "readonly",
                editable=False,
                readonly=True,
                comment="环境变量 > config.ini（[basic]/[redis]/[minio]/[email]/[models]/[ui]）> 内置默认",
                label_en="Precedence",
                comment_en="Environment variables > config.ini ([basic]/[redis]/[minio]/[email]/[models]/[ui]) > built-in defaults",
            ),
            ConfigField(
                "_restart",
                "生效方式",
                "readonly",
                editable=False,
                readonly=True,
                comment="保存写入对应分节；须重启服务后 settings.py 重新加载",
                label_en="How changes apply",
                comment_en="Saves into the matching INI section; restart so settings.py reloads",
            ),
        ),
    ),
    ConfigUnit(
        id="security",
        title="基础与安全",
        title_en="Basics and security",
        description="[basic] 时区、检测、推理设备与日志等（登录密钥请改 config.ini / VISIONAI_SECRET）",
        description_en="[basic] Timezone, detection, inference device, and logs (change the login secret in config.ini / VISIONAI_SECRET)",
        fields=(
            _f(
                "timezone",
                "应用时区",
                "timezone",
                comment="IANA 时区；影响告警落库与历史页展示。保存后须重启服务生效",
                label_en="App timezone",
                comment_en="IANA timezone; used for alert timestamps and history. Restart after saving",
                section="basic",
            ),
            _f(
                "detection_interval",
                "检测间隔（秒）",
                "int",
                comment="两轮检测的间隔；越小越常开窗",
                label_en="Detection interval (seconds)",
                comment_en="Interval between detection rounds; smaller means more frequent windows",
                section="basic",
            ),
            _f(
                "detect_burst_duration_ms",
                "一轮采样窗（毫秒）",
                "int",
                comment="到点后连续抽帧的墙钟时长；0 则关闭多帧，退回单帧",
                label_en="Sampling window (ms)",
                comment_en="Wall-clock duration of consecutive frames after each tick; 0 disables multi-frame and uses a single frame",
                section="basic",
            ),
            _f(
                "detect_burst_frames",
                "一轮目标帧数",
                "int",
                comment="采样窗内最多抽几帧做模型分析；1 则关闭多帧",
                label_en="Target frames per round",
                comment_en="Max frames sampled in the window for model analysis; 1 disables multi-frame",
                section="basic",
            ),
            _f(
                "detect_burst_min_frames",
                "一轮最少帧数",
                "int",
                comment="实际抽到少于此值则本轮跳过",
                label_en="Minimum frames per round",
                comment_en="Skip the round if fewer frames were captured",
                section="basic",
            ),
            _f(
                "detect_burst_hit_ratio",
                "一轮命中率阈值",
                "float",
                comment="某类型在窗内阳性帧占比 ≥ 该值才作为本轮结论（0~1）",
                label_en="Hit-ratio threshold",
                comment_en="A type is accepted for the round only if its positive-frame ratio in the window is ≥ this value (0–1)",
                section="basic",
            ),
            _f(
                "conf_threshold",
                "主检测置信度阈值",
                "float",
                label_en="Main detector confidence",
                section="basic",
            ),
            _f(
                "inference_device",
                "推理设备总开关",
                "text",
                comment="cpu | gpu；改完重启生效，同时控制 YOLO+ONNX",
                label_en="Inference device (global)",
                comment_en="cpu or gpu; restart required; applies to both YOLO and ONNX",
                section="basic",
            ),
            _f(
                "yolo_device",
                "YOLO 推理设备（分项）",
                "text",
                comment="总开关留空时生效；cpu 或 GPU 序号 0",
                label_en="YOLO device (override)",
                comment_en="Used when the global switch is empty; cpu or GPU index 0",
                section="basic",
            ),
            _f(
                "onnx_provider",
                "ONNX 推理（分项）",
                "text",
                comment="总开关留空时生效；cpu 或 cuda_first/gpu",
                label_en="ONNX provider (override)",
                comment_en="Used when the global switch is empty; cpu or cuda_first/gpu",
                section="basic",
            ),
            _f(
                "save_dir",
                "截图目录",
                "text",
                comment=_path_comment("如 ./snapshots"),
                comment_en=_path_comment_en("e.g. ./snapshots"),
                label_en="Snapshot directory",
                relative_path=True,
                section="basic",
            ),
            _f(
                "save_interval",
                "截图最小间隔（秒）",
                "int",
                label_en="Min snapshot interval (seconds)",
                section="basic",
            ),
            _f(
                "log_level",
                "日志级别",
                "text",
                label_en="Log level",
                section="basic",
            ),
            _f(
                "log_dir",
                "日志目录",
                "text",
                comment=_path_comment("如 ./logs"),
                comment_en=_path_comment_en("e.g. ./logs"),
                label_en="Log directory",
                relative_path=True,
                section="basic",
            ),
            _f(
                "log_retention_days",
                "日志保留天数",
                "int",
                label_en="Log retention (days)",
                section="basic",
            ),
            _f(
                "auto_refresh_interval",
                "管理端自动刷新（秒）",
                "int",
                label_en="Admin auto-refresh (seconds)",
                section="basic",
            ),
            _f(
                "detection_retention_days",
                "检测记录保留天数",
                "int",
                label_en="Detection record retention (days)",
                section="basic",
            ),
        ),
    ),
    ConfigUnit(
        id="gather",
        title="人员聚集",
        title_en="Crowd gathering",
        description="[models] 与「人物」告警独立；开「人员聚集」即采集 person 框",
        description_en="[models] Independent of the Person alert; enabling Crowd gathering collects person boxes",
        fields=(
            _f(
                "gather_min_persons",
                "最少人数",
                "int",
                comment="单帧检出人数 ≥ 该值",
                label_en="Minimum people",
                comment_en="People detected in one frame ≥ this value",
                section="models",
            ),
            _f(
                "gather_min_duration_sec",
                "持续秒数",
                "float",
                comment="0 表示立即告警",
                label_en="Duration (seconds)",
                comment_en="0 means alert immediately",
                section="models",
            ),
        ),
    ),
    ConfigUnit(
        id="dedicated_models",
        title="内置专模路径",
        title_en="Built-in model paths",
        description="[models] YOLO 主模型与人脸识别权重",
        description_en="[models] Primary YOLO model and face-recognition weights",
        fields=(
            _f(
                "yolo_model",
                "YOLO 主模型",
                "text",
                comment=_path_comment("本项目用 YOLO26，默认 models/yolo26s.pt"),
                comment_en=_path_comment_en("This project uses YOLO26; default models/yolo26s.pt"),
                label_en="Primary YOLO model",
                relative_path=True,
            ),
            _f(
                "face_recog_det_model_path",
                "人脸识别-检测 det_10g.onnx",
                "text",
                comment=_path_comment("buffalo_l"),
                comment_en=_path_comment_en("buffalo_l"),
                label_en="Face detection (det_10g.onnx)",
                relative_path=True,
            ),
            _f(
                "face_recog_embed_model_path",
                "人脸识别-特征 w600k_r50.onnx",
                "text",
                comment=_path_comment("buffalo_l"),
                comment_en=_path_comment_en("buffalo_l"),
                label_en="Face embedding (w600k_r50.onnx)",
                relative_path=True,
            ),
            _f(
                "face_recog_genderage_model_path",
                "人脸识别-性别年龄",
                "text",
                comment=_path_comment("buffalo_l"),
                comment_en=_path_comment_en("buffalo_l"),
                label_en="Face gender/age",
                relative_path=True,
            ),
        ),
    ),
    ConfigUnit(
        id="dedicated_thresholds",
        title="专模默认阈值",
        title_en="Dedicated-model defaults",
        description="[models] 各扩展检测未单独配置时使用的默认值",
        description_en="[models] Defaults when an extra detector has no per-type override",
        fields=(
            _f("dedicated_default_conf", "专模推理置信度", "float",
               label_en="Dedicated inference confidence"),
            _f("dedicated_default_score_threshold", "告警分数阈值", "float",
               label_en="Alert score threshold"),
            _f("dedicated_default_min_duration_sec", "持续秒数", "float",
               label_en="Duration (seconds)"),
            _f("face_recognition_threshold", "人脸相似度阈值", "float",
               label_en="Face similarity threshold"),
            _f("face_recognition_min_duration_sec", "人脸持续秒数", "float",
               label_en="Face duration (seconds)"),
            _f("face_recog_genderage_enabled", "性别年龄全局开关", "bool",
               label_en="Gender/age (global)"),
            _f("plate_recognition_min_duration_sec", "车牌识别持续秒数", "float",
               label_en="Plate recognition duration (seconds)"),
            _f("plate_recognition_ocr_min_conf", "车牌 OCR 最低置信度", "float",
               label_en="Plate OCR min confidence"),
        ),
    ),
    ConfigUnit(
        id="phone",
        title="玩手机（姿态）",
        title_en="Phone use (pose)",
        description="[models] 人+手机框重叠后用姿态区分玩手机；打电话请用训练实验室自训专模",
        description_en="[models] After person+phone box overlap, pose distinguishes phone use; train a dedicated model in the lab for phone calls",
        fields=(
            _f(
                "pose_model",
                "姿态模型路径",
                "text",
                comment=_path_comment(),
                comment_en=_path_comment_en(),
                label_en="Pose model path",
                relative_path=True,
            ),
            _f(
                "pose_for_phone_enabled",
                "启用姿态辅助玩手机判定",
                "bool",
                label_en="Use pose to confirm phone use",
            ),
            _f(
                "phone_pose_kp_min_conf",
                "关键点最低置信",
                "float",
                label_en="Min keypoint confidence",
            ),
            _f(
                "phone_call_head_ratio",
                "贴头判定比例",
                "float",
                comment="姿态链路内部仍使用；打电话专模已下线",
                label_en="Near-head ratio",
                comment_en="Still used on the pose path; the dedicated phone-call model is retired",
            ),
            _f(
                "phone_play_wrist_ratio",
                "贴腕判定比例",
                "float",
                label_en="Near-wrist ratio",
            ),
            _f(
                "phone_vertical_boundary",
                "竖直分界",
                "float",
                label_en="Vertical boundary",
            ),
        ),
    ),
    ConfigUnit(
        id="redis",
        title="Redis",
        title_en="Redis",
        description="[redis] 流配置与告警记录存储（节内短键 host/port/…）",
        description_en="[redis] Stream config and alert storage (short keys host/port/…)",
        fields=(
            _f(
                "redis_host",
                "主机",
                "text",
                comment="Docker 内常用 redis；宿主机常用 127.0.0.1",
                label_en="Host",
                comment_en="Often redis in Docker; 127.0.0.1 on the host",
                section="redis",
                ini_key="host",
            ),
            _f("redis_port", "端口", "int", label_en="Port",
               section="redis", ini_key="port"),
            _f("redis_password", "密码", "password", label_en="Password",
               section="redis", ini_key="password"),
            _f("redis_db", "数据库", "int", label_en="Database",
               section="redis", ini_key="db"),
            _f("redis_key_prefix", "键前缀", "text", label_en="Key prefix",
               section="redis", ini_key="key_prefix"),
        ),
    ),
    ConfigUnit(
        id="storage",
        title="对象存储 (MinIO/S3)",
        title_en="Object storage (MinIO/S3)",
        description="[minio] 截图上传与生命周期",
        description_en="[minio] Snapshot upload and lifecycle",
        fields=(
            _f("object_storage_enabled", "启用对象存储", "bool",
               label_en="Enable object storage",
               section="minio", ini_key="enabled"),
            _f("object_storage_keep_local", "同时保留本地文件", "bool",
               label_en="Keep local copies",
               section="minio", ini_key="keep_local"),
            _f("s3_endpoint_url", "端点 URL", "text",
               label_en="Endpoint URL",
               section="minio", ini_key="endpoint_url"),
            _f("s3_access_key_id", "Access Key", "text",
               label_en="Access Key",
               section="minio", ini_key="access_key_id"),
            _f("s3_secret_access_key", "Secret Key", "password",
               label_en="Secret Key",
               section="minio", ini_key="secret_access_key"),
            _f("s3_bucket", "桶名", "text", label_en="Bucket",
               section="minio", ini_key="bucket"),
            _f("s3_region", "Region", "text", label_en="Region",
               section="minio", ini_key="region"),
            _f("s3_use_ssl", "使用 SSL", "bool", label_en="Use SSL",
               section="minio", ini_key="use_ssl"),
            _f("s3_path_prefix", "对象键前缀", "text",
               label_en="Object key prefix",
               section="minio", ini_key="path_prefix"),
            _f(
                "s3_addressing_style",
                "寻址风格",
                "text",
                comment="path 或 virtual",
                label_en="Addressing style",
                comment_en="path or virtual",
                section="minio",
                ini_key="addressing_style",
            ),
            _f("s3_lifecycle_enabled", "桶生命周期规则", "bool",
               label_en="Bucket lifecycle rules",
               section="minio", ini_key="lifecycle_enabled"),
        ),
    ),
    ConfigUnit(
        id="smtp",
        title="告警邮件",
        title_en="Alert email",
        description="[email] 全局 SMTP；每路收件人在「检测配置」页配置",
        description_en="[email] Global SMTP; per-stream recipients are set on Detection policy",
        fields=(
            _f("smtp_alert_enabled", "启用邮件告警", "bool",
               label_en="Enable email alerts",
               section="email", ini_key="alert_enabled"),
            _f("smtp_host", "SMTP 主机", "text", label_en="SMTP host",
               section="email", ini_key="host"),
            _f("smtp_port", "端口", "int", label_en="Port",
               section="email", ini_key="port"),
            _f("smtp_use_ssl", "SSL", "bool", label_en="SSL",
               section="email", ini_key="use_ssl"),
            _f("smtp_use_tls", "TLS", "bool", label_en="TLS",
               section="email", ini_key="use_tls"),
            _f("smtp_user", "用户名", "text", label_en="Username",
               section="email", ini_key="user"),
            _f("smtp_password", "密码/授权码", "password",
               label_en="Password / app password",
               section="email", ini_key="password"),
            _f("smtp_from", "发件人", "text", label_en="From",
               section="email", ini_key="from"),
        ),
    ),
    ConfigUnit(
        id="integration",
        title="开放集成",
        title_en="Open integration",
        description="[integration] 机对机 API、全局告警推送与侧栏嵌入页；机对机项改完须重启",
        description_en="[integration] Machine-to-machine API, global alert push, and sidebar embed URL; restart after API changes",
        fields=(
            _f(
                "open_api_key",
                "开放 API 密钥",
                "password",
                comment="请求头 X-Api-Key；空则 /api/open/v1 一律 401",
                label_en="Open API key",
                comment_en="Header X-Api-Key; empty means /api/open/v1 always returns 401",
                section="integration",
                ini_key="open_api_key",
            ),
            _f(
                "public_base_url",
                "对外根 URL",
                "text",
                comment="告警 image_url 前缀，如 http://主机:15000，无尾斜杠",
                label_en="Public base URL",
                comment_en="Prefix for alert image_url, e.g. http://host:15000 with no trailing slash",
                section="integration",
                ini_key="public_base_url",
            ),
            _f(
                "outbound_webhook_url",
                "全局告警 Webhook",
                "text",
                comment="对接方 POST 地址；每路仍可追加 alert_webhook_urls",
                label_en="Global alert webhook",
                comment_en="Partner POST URL; per-stream alert_webhook_urls can still be added",
                section="integration",
                ini_key="outbound_webhook_url",
            ),
            _f(
                "embed_frame_ancestors",
                "管理页 iframe 父源",
                "text",
                comment="允许嵌入本管理页的 origin，空格或逗号分隔；空则不写 CSP",
                label_en="Admin iframe parent origins",
                comment_en="Origins allowed to iframe this admin UI; empty disables CSP frame-ancestors",
                section="integration",
                ini_key="embed_frame_ancestors",
            ),
            _f(
                "platform_embed_url",
                "平台接入嵌入页 URL",
                "text",
                comment="侧栏「平台接入」iframe 地址；空则该页显示未接入。保存后点菜单即可（不必为该项单独重启）",
                label_en="Platform embed page URL",
                comment_en="Sidebar Platform access iframe URL; empty shows Not connected. Reload the menu after save (no extra restart for this field)",
                section="integration",
                ini_key="platform_embed_url",
            ),
        ),
    ),
)

# ini 规范键 -> settings 模块属性（特殊映射）
_KEY_TO_SETTINGS_ATTR = {
    "visionai_secret": "SECRET",
    "open_api_key": "OPEN_API_KEY",
    "public_base_url": "PUBLIC_BASE_URL",
    "outbound_webhook_url": "OUTBOUND_WEBHOOK_URL",
    "embed_frame_ancestors": "EMBED_FRAME_ANCESTORS",
    "platform_embed_url": "PLATFORM_EMBED_URL",
}


def all_schema_keys() -> List[str]:
    keys: List[str] = []
    for unit in CONFIG_UNITS:
        for f in unit.fields:
            if not f.readonly and f.key and not f.key.startswith("_"):
                keys.append(f.key)
    return keys
