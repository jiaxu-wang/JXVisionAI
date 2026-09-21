"""COCO 80 类与内置扩展：与 Ultralytics 预训练 YOLO26（COCO）类别索引一致。

专模检测类型由 ``visionai.config.specialists`` 动态注册，不在此硬编码。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

# 与 ultralytics/cfg/datasets/coco.yaml 一致
COCO_NAMES: Dict[int, str] = {
    0: "person",
    1: "bicycle",
    2: "car",
    3: "motorcycle",
    4: "airplane",
    5: "bus",
    6: "train",
    7: "truck",
    8: "boat",
    9: "traffic light",
    10: "fire hydrant",
    11: "stop sign",
    12: "parking meter",
    13: "bench",
    14: "bird",
    15: "cat",
    16: "dog",
    17: "horse",
    18: "sheep",
    19: "cow",
    20: "elephant",
    21: "bear",
    22: "zebra",
    23: "giraffe",
    24: "backpack",
    25: "umbrella",
    26: "handbag",
    27: "tie",
    28: "suitcase",
    29: "frisbee",
    30: "skis",
    31: "snowboard",
    32: "sports ball",
    33: "kite",
    34: "baseball bat",
    35: "baseball glove",
    36: "skateboard",
    37: "surfboard",
    38: "tennis racket",
    39: "bottle",
    40: "wine glass",
    41: "cup",
    42: "fork",
    43: "knife",
    44: "spoon",
    45: "bowl",
    46: "banana",
    47: "apple",
    48: "sandwich",
    49: "orange",
    50: "broccoli",
    51: "carrot",
    52: "hot dog",
    53: "pizza",
    54: "donut",
    55: "cake",
    56: "chair",
    57: "couch",
    58: "potted plant",
    59: "bed",
    60: "dining table",
    61: "toilet",
    62: "tv",
    63: "laptop",
    64: "mouse",
    65: "remote",
    66: "keyboard",
    67: "cell phone",
    68: "microwave",
    69: "oven",
    70: "toaster",
    71: "sink",
    72: "refrigerator",
    73: "book",
    74: "clock",
    75: "vase",
    76: "scissors",
    77: "teddy bear",
    78: "hair drier",
    79: "toothbrush",
}

COCO_NAMES_ZH: Dict[int, str] = {
    0: "人物",
    1: "自行车",
    2: "汽车",
    3: "摩托车",
    4: "飞机",
    5: "公交车",
    6: "火车",
    7: "卡车",
    8: "船",
    9: "交通灯",
    10: "消防栓",
    11: "停止标志",
    12: "停车计时器",
    13: "长椅",
    14: "鸟",
    15: "猫",
    16: "狗",
    17: "马",
    18: "羊",
    19: "牛",
    20: "大象",
    21: "熊",
    22: "斑马",
    23: "长颈鹿",
    24: "背包",
    25: "雨伞",
    26: "手提包",
    27: "领带",
    28: "行李箱",
    29: "飞盘",
    30: "滑雪板",
    31: "单板滑雪",
    32: "运动球",
    33: "风筝",
    34: "棒球棒",
    35: "棒球手套",
    36: "滑板",
    37: "冲浪板",
    38: "网球拍",
    39: "瓶子",
    40: "酒杯",
    41: "杯子",
    42: "叉子",
    43: "刀",
    44: "勺子",
    45: "碗",
    46: "香蕉",
    47: "苹果",
    48: "三明治",
    49: "橙子",
    50: "西兰花",
    51: "胡萝卜",
    52: "热狗",
    53: "披萨",
    54: "甜甜圈",
    55: "蛋糕",
    56: "椅子",
    57: "沙发",
    58: "盆栽",
    59: "床",
    60: "餐桌",
    61: "马桶",
    62: "电视",
    63: "笔记本电脑",
    64: "鼠标",
    65: "遥控器",
    66: "键盘",
    67: "手机",
    68: "微波炉",
    69: "烤箱",
    70: "烤面包机",
    71: "水槽",
    72: "冰箱",
    73: "书",
    74: "时钟",
    75: "花瓶",
    76: "剪刀",
    77: "泰迪熊",
    78: "吹风机",
    79: "牙刷",
}

# 旧版前端/Redis 中的检测键 -> COCO 类别 id
_LEGACY_DETECTION_KEY_TO_CLASS_ID: Dict[str, int] = {
    "person": 0,
    "cell_phone": 67,
    "car": 2,
    "motorcycle": 3,
    "bicycle": 1,
    "cat": 15,
    "dog": 16,
    "horse": 17,
    "sheep": 18,
    "cow": 19,
}

NUM_COCO_CLASSES = 80
CALL_KEY = "call"
PHONE_PLAY_KEY = "phone_play"
GATHER_KEY = "gather"
FACE_RECOG_KEY = "face_recognition"
PLATE_RECOG_KEY = "plate_recognition"
FATIGUE_KEY = "fatigue_driving"

# 内置扩展（非专模）。打电话能力已下线；历史告警文案仍保留 CALL_KEY 标签。
EXTENSION_KEYS: Tuple[str, ...] = (
    PHONE_PLAY_KEY,
    GATHER_KEY,
    FACE_RECOG_KEY,
    PLATE_RECOG_KEY,
    FATIGUE_KEY,
)

EXTENSION_LABELS_ZH: Dict[str, str] = {
    CALL_KEY: "打电话",  # 仅兼容历史告警文案，不再作为检测类型
    PHONE_PLAY_KEY: "玩手机",
    GATHER_KEY: "人员聚集",
    FACE_RECOG_KEY: "人脸识别",
    PLATE_RECOG_KEY: "车牌识别",
    FATIGUE_KEY: "疲劳驾驶",
}

# 告警推送 / 调度 typeName 用的短英文名（与管理端 typesMap 对齐）
EXTENSION_LABELS_EN: Dict[str, str] = {
    CALL_KEY: "Phone call",
    PHONE_PLAY_KEY: "Using phone",
    GATHER_KEY: "Crowd gathering",
    FACE_RECOG_KEY: "Face recognition",
    PLATE_RECOG_KEY: "License plate",
    FATIGUE_KEY: "Fatigue driving",
}

EXTENSION_CATALOG_META: List[Dict[str, str]] = [
    {
        "key": PHONE_PLAY_KEY,
        "name_en": "playing with phone (YOLO+COCO overlap + pose)",
        "name_zh": EXTENSION_LABELS_ZH[PHONE_PLAY_KEY],
    },
    {
        "key": GATHER_KEY,
        "name_en": "crowd gathering (min persons in frame)",
        "name_zh": EXTENSION_LABELS_ZH[GATHER_KEY],
    },
    {
        "key": FACE_RECOG_KEY,
        "name_en": "face recognition (library match / stranger alert)",
        "name_zh": EXTENSION_LABELS_ZH[FACE_RECOG_KEY],
    },
    {
        "key": PLATE_RECOG_KEY,
        "name_en": "license plate OCR + library (known / unknown)",
        "name_zh": EXTENSION_LABELS_ZH[PLATE_RECOG_KEY],
    },
    {
        "key": FATIGUE_KEY,
        "name_en": "fatigue driving (PERCLOS / yawn / nod, cabin face only)",
        "name_zh": EXTENSION_LABELS_ZH[FATIGUE_KEY],
    },
]


def _specialist_label_map() -> Dict[str, str]:
    try:
        from visionai.config.specialists import list_specialists

        return {m["key"]: m["name_zh"] for m in list_specialists()}
    except Exception:  # noqa: BLE001
        return {}


def _specialist_keys() -> Tuple[str, ...]:
    try:
        from visionai.config.specialists import specialist_keys

        return specialist_keys()
    except Exception:  # noqa: BLE001
        return ()


def all_extension_keys() -> Tuple[str, ...]:
    """内置扩展 + 已部署专模键。"""
    return tuple(dict.fromkeys([*EXTENSION_KEYS, *_specialist_keys()]))


def person_behavior_keys() -> Tuple[str, ...]:
    """人物关联行为：person_event / violation 专模。"""
    keys: List[str] = []
    try:
        from visionai.config.specialists import list_specialists

        for m in list_specialists():
            if m.get("kind") in ("person_event", "violation"):
                keys.append(m["key"])
    except Exception:  # noqa: BLE001
        pass
    return tuple(dict.fromkeys(keys))


def scene_behavior_keys() -> Tuple[str, ...]:
    keys: List[str] = []
    try:
        from visionai.config.specialists import list_specialists

        for m in list_specialists():
            if m.get("kind") == "scene":
                keys.append(m["key"])
    except Exception:  # noqa: BLE001
        pass
    return tuple(keys)


def default_detections_dict() -> Dict[str, bool]:
    d = {str(i): False for i in range(NUM_COCO_CLASSES)}
    for key in all_extension_keys():
        d[key] = False
    return d


def any_detection_enabled(detections: Optional[Dict[str, Any]]) -> bool:
    """是否勾选了至少一项检测类型（与流级 enabled 暂停开关无关）。"""
    if not detections:
        return False
    return any(bool(v) for v in detections.values())


def normalize_detections(raw: Optional[Dict[str, Any]]) -> Dict[str, bool]:
    """合并旧版配置键与新版「字符串类别 id」键，缺省全部为 False。"""
    out = default_detections_dict()
    allowed_ext = frozenset(all_extension_keys())
    if not raw:
        return out
    for k, v in raw.items():
        if v is None:
            continue
        key = str(k)
        # 内置 call 已下线；专模键（含将来自训的 phone_call）走 allowed_ext
        if key == CALL_KEY:
            continue
        if key in allowed_ext:
            out[key] = bool(v)
        elif key in out and key.isdigit():
            out[key] = bool(v)
        elif key in _LEGACY_DETECTION_KEY_TO_CLASS_ID:
            cid = _LEGACY_DETECTION_KEY_TO_CLASS_ID[key]
            out[str(cid)] = bool(v)
        elif key.isdigit() and 0 <= int(key) < NUM_COCO_CLASSES:
            out[key] = bool(v)
    return out


def label_zh_for_extension(key: str) -> str:
    if key in EXTENSION_LABELS_ZH:
        return EXTENSION_LABELS_ZH[key]
    return _specialist_label_map().get(key, key)


def catalog_items_for_api() -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    for i in range(NUM_COCO_CLASSES):
        items.append(
            {
                "key": str(i),
                "class_id": i,
                "name_en": COCO_NAMES[i],
                "name_zh": COCO_NAMES_ZH.get(i, COCO_NAMES[i]),
                "supported": True,
                "source": "coco",
                "deletable": False,
            }
        )
    for meta in EXTENSION_CATALOG_META:
        items.append(
            {
                "key": meta["key"],
                "class_id": None,
                "name_en": meta["name_en"],
                "name_zh": meta["name_zh"],
                "supported": True,
                "source": "builtin",
                "deletable": False,
            }
        )
    try:
        from visionai.config.specialists import catalog_items_for_specialists

        items.extend(catalog_items_for_specialists())
    except Exception:  # noqa: BLE001
        pass
    return items


def label_zh_for_class(class_id: int) -> str:
    return COCO_NAMES_ZH.get(class_id, COCO_NAMES.get(class_id, str(class_id)))
