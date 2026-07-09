"""系统设置页：配置单元与字段 schema（键名与 config.ini / settings.py 对应）。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Tuple

# type: text | int | float | bool | password | readonly

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
    # 仅展示、不写入 ini
    readonly: bool = False
    # 本地文件/目录路径：ini 可写相对项目根
    relative_path: bool = False


@dataclass(frozen=True)
class ConfigUnit:
    id: str
    title: str
    description: str
    fields: Tuple[ConfigField, ...]


CONFIG_UNITS: Tuple[ConfigUnit, ...] = (
    ConfigUnit(
        id="meta",
        title="配置说明",
        description="以下为只读说明；修改其它单元后保存并重启，全配置生效。",
        fields=(
            ConfigField("_priority", "生效优先级", "readonly", editable=False, readonly=True,
                        comment="环境变量 > config.ini > settings.py 内置默认值"),
            ConfigField("_restart", "生效方式", "readonly", editable=False, readonly=True,
                        comment="保存写入 config.ini（保留原文件注释）；须重启服务后 settings.py 重新加载"),
        ),
    ),
    ConfigUnit(
        id="security",
        title="基础与安全",
        description="Flask 登录会话密钥",
        fields=(
            ConfigField("visionai_secret", "visionai_secret", "password",
                        comment="与 docker-compose 中 VISIONAI_SECRET 一致；生产请修改"),
        ),
    ),
    ConfigUnit(
        id="detection",
        title="检测主模型",
        description="YOLOv8 主检测与截图",
        fields=(
            ConfigField("detection_interval", "检测间隔（秒）", "int",
                        comment="数值越小越常跑 YOLO+行为层；吸烟场景建议 5~8"),
            ConfigField("conf_threshold", "主检测置信度阈值", "float"),
            ConfigField("yolo_model", "YOLO 主模型", "text",
                        comment=_path_comment("如 yolov8n.pt 或 models/yolov8n.pt"),
                        relative_path=True),
            ConfigField("yolo_device", "YOLO 推理设备", "text",
                        comment="留空=自动；cpu 或 GPU 序号 0"),
            ConfigField("onnx_provider", "ONNX 推理", "text",
                        comment="cpu 或 cuda_first"),
            ConfigField("save_dir", "截图目录", "text",
                        comment=_path_comment("如 ./snapshots"), relative_path=True),
            ConfigField("save_interval", "截图最小间隔（秒）", "int"),
        ),
    ),
    ConfigUnit(
        id="gather",
        title="人员聚集",
        description="与「人物」告警独立；开「人员聚集」即采集 person 框",
        fields=(
            ConfigField("gather_min_persons", "最少人数", "int",
                        comment="单帧检出人数 ≥ 该值"),
            ConfigField("gather_min_duration_sec", "持续秒数", "float",
                        comment="0 表示立即告警"),
        ),
    ),
    ConfigUnit(
        id="dedicated_models",
        title="专模路径",
        description="扩展检测模型文件路径（.pt / .onnx）",
        fields=(
            ConfigField("face_model_path", "人脸 face_detection.onnx", "text",
                        comment=_path_comment(), relative_path=True),
            ConfigField("fall_model_path", "跌倒 fall_detection.onnx", "text",
                        comment=_path_comment(), relative_path=True),
            ConfigField("flame_model_path", "火焰 flame.pt", "text",
                        comment=_path_comment(), relative_path=True),
            ConfigField("license_plate_model_path", "车牌 license_plate_detection.onnx", "text",
                        comment=_path_comment(), relative_path=True),
            ConfigField("make_call_model_path", "打电话 make_call.onnx", "text",
                        comment=_path_comment(), relative_path=True),
            ConfigField("mask_model_path", "口罩 mask.onnx", "text",
                        comment=_path_comment(), relative_path=True),
            ConfigField("reflective_vest_model_path", "反光衣 reflective_vest.pt", "text",
                        comment=_path_comment(), relative_path=True),
            ConfigField("road_waterlogging_model_path", "道路积水 road_waterlogging.onnx", "text",
                        comment=_path_comment(), relative_path=True),
            ConfigField("safety_helmet_model_path", "安全帽 safety_helmet.pt", "text",
                        comment=_path_comment(), relative_path=True),
            ConfigField("sleeping_model_path", "睡觉 sleeping.pt", "text",
                        comment=_path_comment(), relative_path=True),
        ),
    ),
    ConfigUnit(
        id="dedicated_thresholds",
        title="专模默认阈值",
        description="各扩展检测未单独配置时使用的默认值",
        fields=(
            ConfigField("dedicated_default_conf", "专模推理置信度", "float"),
            ConfigField("dedicated_default_score_threshold", "告警分数阈值", "float"),
            ConfigField("dedicated_default_min_duration_sec", "持续秒数", "float"),
            ConfigField("sleeping_model_conf", "睡觉-专模置信度", "float",
                        comment="低头看屏易误报，建议 ≥0.55"),
            ConfigField("sleeping_score_threshold", "睡觉-告警阈值", "float",
                        comment="建议 0.65~0.75"),
            ConfigField("sleeping_min_duration_sec", "睡觉-持续秒数", "float"),
        ),
    ),
    ConfigUnit(
        id="smoking",
        title="吸烟",
        description="smoking_detection.pt 专模；yolo_direct=true 时不跑 ViT",
        fields=(
            ConfigField("smoking_yolo_direct", "YOLO 专模直连", "bool"),
            ConfigField("smoking_require_person_overlap", "需要 COCO 人物重叠", "bool"),
            ConfigField("smoking_cigarette_detector_path", "吸烟模型路径", "text",
                        comment=_path_comment(), relative_path=True),
            ConfigField("smoking_cigarette_detector_conf", "专模置信度", "float"),
            ConfigField("smoking_cigarette_class_ids", "类别 ID", "text",
                        comment="单类一般为 0"),
            ConfigField("smoking_conf_threshold", "告警阈值", "float"),
            ConfigField("smoking_min_duration_sec", "持续秒数", "float"),
            ConfigField("smoking_log_scores", "打印分数日志", "bool"),
            ConfigField("smoking_model_path", "备用 ViT 路径", "text",
                        comment=_path_comment("yolo_direct=false 时生效"), relative_path=True),
            ConfigField("smoking_preprocess", "ViT 预处理", "text", comment="vit_hf 或 imagenet"),
            ConfigField("smoking_positive_class_index", "ViT 正类索引", "int"),
        ),
    ),
    ConfigUnit(
        id="phone",
        title="打电话 / 玩手机",
        description="make_call.onnx 专模 + 姿态模型",
        fields=(
            ConfigField("make_call_use_dedicated", "使用 make_call 专模", "bool"),
            ConfigField("make_call_require_person_overlap", "打电话需人物重叠", "bool"),
            ConfigField("make_call_model_conf", "打电话专模置信度", "float"),
            ConfigField("make_call_score_threshold", "打电话告警阈值", "float"),
            ConfigField("make_call_min_duration_sec", "打电话持续秒数", "float"),
            ConfigField("pose_model", "姿态模型路径", "text",
                        comment=_path_comment(), relative_path=True),
            ConfigField("pose_for_phone_enabled", "姿态区分打电话/玩手机", "bool"),
            ConfigField("phone_pose_kp_min_conf", "关键点最低置信", "float"),
            ConfigField("phone_call_head_ratio", "贴头判定比例", "float"),
            ConfigField("phone_play_wrist_ratio", "贴腕判定比例", "float"),
            ConfigField("phone_vertical_boundary", "竖直分界", "float"),
        ),
    ),
    ConfigUnit(
        id="redis",
        title="Redis",
        description="流配置与告警记录存储",
        fields=(
            ConfigField("redis_host", "主机", "text",
                        comment="Docker 内常用 redis；宿主机常用 127.0.0.1"),
            ConfigField("redis_port", "端口", "int"),
            ConfigField("redis_password", "密码", "password"),
            ConfigField("redis_db", "数据库", "int"),
            ConfigField("redis_key_prefix", "键前缀", "text"),
            ConfigField("detection_retention_days", "记录保留天数", "int"),
        ),
    ),
    ConfigUnit(
        id="storage",
        title="对象存储 (S3/MinIO)",
        description="截图上传与生命周期",
        fields=(
            ConfigField("object_storage_enabled", "启用对象存储", "bool"),
            ConfigField("object_storage_keep_local", "同时保留本地文件", "bool"),
            ConfigField("s3_endpoint_url", "端点 URL", "text"),
            ConfigField("s3_access_key_id", "Access Key", "text"),
            ConfigField("s3_secret_access_key", "Secret Key", "password"),
            ConfigField("s3_bucket", "桶名", "text"),
            ConfigField("s3_region", "Region", "text"),
            ConfigField("s3_use_ssl", "使用 SSL", "bool"),
            ConfigField("s3_path_prefix", "对象键前缀", "text"),
            ConfigField("s3_addressing_style", "寻址风格", "text", comment="path 或 virtual"),
            ConfigField("s3_lifecycle_enabled", "桶生命周期规则", "bool"),
        ),
    ),
    ConfigUnit(
        id="smtp",
        title="告警邮件",
        description="全局 SMTP；每路收件人在事件监控配置",
        fields=(
            ConfigField("smtp_alert_enabled", "启用邮件告警", "bool"),
            ConfigField("smtp_host", "SMTP 主机", "text"),
            ConfigField("smtp_port", "端口", "int"),
            ConfigField("smtp_use_ssl", "SSL", "bool"),
            ConfigField("smtp_use_tls", "TLS", "bool"),
            ConfigField("smtp_user", "用户名", "text"),
            ConfigField("smtp_password", "密码/授权码", "password"),
            ConfigField("smtp_from", "发件人", "text"),
        ),
    ),
    ConfigUnit(
        id="log",
        title="日志与管理端",
        description="",
        fields=(
            ConfigField("log_level", "日志级别", "text"),
            ConfigField("log_dir", "日志目录", "text",
                        comment=_path_comment("如 ./logs"), relative_path=True),
            ConfigField("log_retention_days", "日志保留天数", "int"),
            ConfigField("auto_refresh_interval", "管理端自动刷新（秒）", "int"),
        ),
    ),
)

# ini 键 -> settings 模块属性（特殊映射）
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
