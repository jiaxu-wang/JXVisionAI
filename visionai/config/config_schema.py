"""系统设置页：配置单元与字段 schema（规范键与 config.ini 分节对应）。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Tuple

from visionai.config.ini_sections import preferred_ini_key, preferred_section

# type: text | int | float | bool | password | timezone | readonly

_PATH_HINT = "相对项目根；也可用绝对路径"


def _path_comment(extra: str = "") -> str:
    if extra:
        return f"{extra}；{_PATH_HINT}"
    return _PATH_HINT


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


def _f(
    key: str,
    label: str,
    field_type: str = "text",
    *,
    comment: str = "",
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
    )


CONFIG_UNITS: Tuple[ConfigUnit, ...] = (
    ConfigUnit(
        id="meta",
        title="配置说明",
        description="以下为只读说明；修改其它单元后保存并重启，全配置生效。",
        fields=(
            ConfigField(
                "_priority",
                "生效优先级",
                "readonly",
                editable=False,
                readonly=True,
                comment="环境变量 > config.ini（[basic]/[redis]/[minio]/[email]/[models]）> 内置默认",
            ),
            ConfigField(
                "_restart",
                "生效方式",
                "readonly",
                editable=False,
                readonly=True,
                comment="保存写入对应分节；须重启服务后 settings.py 重新加载",
            ),
        ),
    ),
    ConfigUnit(
        id="security",
        title="基础与安全",
        description="[basic] 时区、检测、推理设备与日志等（登录密钥请改 config.ini / VISIONAI_SECRET）",
        fields=(
            _f("timezone", "应用时区", "timezone",
               comment="IANA 时区；影响告警落库与历史页展示。保存后须重启服务生效",
               section="basic"),
            _f("detection_interval", "检测间隔（秒）", "int",
               comment="两轮检测的间隔；越小越常开窗",
               section="basic"),
            _f("detect_burst_duration_ms", "一轮采样窗（毫秒）", "int",
               comment="到点后连续抽帧的墙钟时长；0 则关闭多帧，退回单帧",
               section="basic"),
            _f("detect_burst_frames", "一轮目标帧数", "int",
               comment="采样窗内最多抽几帧做模型分析；1 则关闭多帧",
               section="basic"),
            _f("detect_burst_min_frames", "一轮最少帧数", "int",
               comment="实际抽到少于此值则本轮跳过",
               section="basic"),
            _f("detect_burst_hit_ratio", "一轮命中率阈值", "float",
               comment="某类型在窗内阳性帧占比 ≥ 该值才作为本轮结论（0~1）",
               section="basic"),
            _f("conf_threshold", "主检测置信度阈值", "float", section="basic"),
            _f("inference_device", "推理设备总开关", "text",
               comment="cpu | gpu；改完重启生效，同时控制 YOLO+ONNX", section="basic"),
            _f("yolo_device", "YOLO 推理设备（分项）", "text",
               comment="总开关留空时生效；cpu 或 GPU 序号 0", section="basic"),
            _f("onnx_provider", "ONNX 推理（分项）", "text",
               comment="总开关留空时生效；cpu 或 cuda_first/gpu", section="basic"),
            _f("save_dir", "截图目录", "text",
               comment=_path_comment("如 ./snapshots"), relative_path=True, section="basic"),
            _f("save_interval", "截图最小间隔（秒）", "int", section="basic"),
            _f("log_level", "日志级别", "text", section="basic"),
            _f("log_dir", "日志目录", "text",
               comment=_path_comment("如 ./logs"), relative_path=True, section="basic"),
            _f("log_retention_days", "日志保留天数", "int", section="basic"),
            _f("auto_refresh_interval", "管理端自动刷新（秒）", "int", section="basic"),
            _f("detection_retention_days", "检测记录保留天数", "int", section="basic"),
        ),
    ),
    ConfigUnit(
        id="gather",
        title="人员聚集",
        description="[models] 与「人物」告警独立；开「人员聚集」即采集 person 框",
        fields=(
            _f("gather_min_persons", "最少人数", "int",
               comment="单帧检出人数 ≥ 该值", section="models"),
            _f("gather_min_duration_sec", "持续秒数", "float",
               comment="0 表示立即告警", section="models"),
        ),
    ),
    ConfigUnit(
        id="dedicated_models",
        title="内置专模路径",
        description="[models] YOLO 主模型与人脸识别权重",
        fields=(
            _f("yolo_model", "YOLO 主模型", "text",
               comment=_path_comment("本项目用 YOLO26，默认 models/yolo26s.pt"), relative_path=True),
            _f("face_recog_det_model_path", "人脸识别-检测 det_10g.onnx", "text",
               comment=_path_comment("buffalo_l"), relative_path=True),
            _f("face_recog_embed_model_path", "人脸识别-特征 w600k_r50.onnx", "text",
               comment=_path_comment("buffalo_l"), relative_path=True),
            _f("face_recog_genderage_model_path", "人脸识别-性别年龄", "text",
               comment=_path_comment("buffalo_l"), relative_path=True),
        ),
    ),
    ConfigUnit(
        id="dedicated_thresholds",
        title="专模默认阈值",
        description="[models] 各扩展检测未单独配置时使用的默认值",
        fields=(
            _f("dedicated_default_conf", "专模推理置信度", "float"),
            _f("dedicated_default_score_threshold", "告警分数阈值", "float"),
            _f("dedicated_default_min_duration_sec", "持续秒数", "float"),
            _f("face_recognition_threshold", "人脸相似度阈值", "float"),
            _f("face_recognition_min_duration_sec", "人脸持续秒数", "float"),
            _f("face_recog_genderage_enabled", "性别年龄全局开关", "bool"),
            _f("plate_recognition_min_duration_sec", "车牌识别持续秒数", "float"),
            _f("plate_recognition_ocr_min_conf", "车牌 OCR 最低置信度", "float"),
        ),
    ),
    ConfigUnit(
        id="phone",
        title="玩手机（姿态）",
        description="[models] 人+手机框重叠后用姿态区分玩手机；打电话请用训练实验室自训专模",
        fields=(
            _f("pose_model", "姿态模型路径", "text",
               comment=_path_comment(), relative_path=True),
            _f("pose_for_phone_enabled", "启用姿态辅助玩手机判定", "bool"),
            _f("phone_pose_kp_min_conf", "关键点最低置信", "float"),
            _f("phone_call_head_ratio", "贴头判定比例", "float",
               comment="姿态链路内部仍使用；打电话专模已下线"),
            _f("phone_play_wrist_ratio", "贴腕判定比例", "float"),
            _f("phone_vertical_boundary", "竖直分界", "float"),
        ),
    ),
    ConfigUnit(
        id="redis",
        title="Redis",
        description="[redis] 流配置与告警记录存储（节内短键 host/port/…）",
        fields=(
            _f("redis_host", "主机", "text",
               comment="Docker 内常用 redis；宿主机常用 127.0.0.1",
               section="redis", ini_key="host"),
            _f("redis_port", "端口", "int", section="redis", ini_key="port"),
            _f("redis_password", "密码", "password", section="redis", ini_key="password"),
            _f("redis_db", "数据库", "int", section="redis", ini_key="db"),
            _f("redis_key_prefix", "键前缀", "text", section="redis", ini_key="key_prefix"),
        ),
    ),
    ConfigUnit(
        id="storage",
        title="对象存储 (MinIO/S3)",
        description="[minio] 截图上传与生命周期",
        fields=(
            _f("object_storage_enabled", "启用对象存储", "bool",
               section="minio", ini_key="enabled"),
            _f("object_storage_keep_local", "同时保留本地文件", "bool",
               section="minio", ini_key="keep_local"),
            _f("s3_endpoint_url", "端点 URL", "text",
               section="minio", ini_key="endpoint_url"),
            _f("s3_access_key_id", "Access Key", "text",
               section="minio", ini_key="access_key_id"),
            _f("s3_secret_access_key", "Secret Key", "password",
               section="minio", ini_key="secret_access_key"),
            _f("s3_bucket", "桶名", "text", section="minio", ini_key="bucket"),
            _f("s3_region", "Region", "text", section="minio", ini_key="region"),
            _f("s3_use_ssl", "使用 SSL", "bool", section="minio", ini_key="use_ssl"),
            _f("s3_path_prefix", "对象键前缀", "text",
               section="minio", ini_key="path_prefix"),
            _f("s3_addressing_style", "寻址风格", "text",
               comment="path 或 virtual", section="minio", ini_key="addressing_style"),
            _f("s3_lifecycle_enabled", "桶生命周期规则", "bool",
               section="minio", ini_key="lifecycle_enabled"),
        ),
    ),
    ConfigUnit(
        id="smtp",
        title="告警邮件",
        description="[email] 全局 SMTP；每路收件人在「检测配置」页配置",
        fields=(
            _f("smtp_alert_enabled", "启用邮件告警", "bool",
               section="email", ini_key="alert_enabled"),
            _f("smtp_host", "SMTP 主机", "text", section="email", ini_key="host"),
            _f("smtp_port", "端口", "int", section="email", ini_key="port"),
            _f("smtp_use_ssl", "SSL", "bool", section="email", ini_key="use_ssl"),
            _f("smtp_use_tls", "TLS", "bool", section="email", ini_key="use_tls"),
            _f("smtp_user", "用户名", "text", section="email", ini_key="user"),
            _f("smtp_password", "密码/授权码", "password",
               section="email", ini_key="password"),
            _f("smtp_from", "发件人", "text", section="email", ini_key="from"),
        ),
    ),
)

# ini 规范键 -> settings 模块属性（特殊映射）
_KEY_TO_SETTINGS_ATTR = {
    "visionai_secret": "SECRET",
}


def all_schema_keys() -> List[str]:
    keys: List[str] = []
    for unit in CONFIG_UNITS:
        for f in unit.fields:
            if not f.readonly and f.key and not f.key.startswith("_"):
                keys.append(f.key)
    return keys
