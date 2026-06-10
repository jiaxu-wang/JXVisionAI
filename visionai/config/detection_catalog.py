"""COCO 80 类与「打电话」扩展：与 Ultralytics 预训练 YOLOv8（COCO）类别索引一致。"""

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
SMOKE_KEY = "smoking"
FACE_KEY = "face"
FALL_KEY = "fall"
FLAME_KEY = "flame"
LICENSE_PLATE_KEY = "license_plate"
MASK_KEY = "mask"
REFLECTIVE_VEST_KEY = "reflective_vest"
ROAD_WATERLOGGING_KEY = "road_waterlogging"
SAFETY_HELMET_KEY = "safety_helmet"
SLEEPING_KEY = "sleeping"

EXTENSION_KEYS: Tuple[str, ...] = (
    CALL_KEY,
    PHONE_PLAY_KEY,
    GATHER_KEY,
    SMOKE_KEY,
    FACE_KEY,
    FALL_KEY,
    FLAME_KEY,
    LICENSE_PLATE_KEY,
    MASK_KEY,
    REFLECTIVE_VEST_KEY,
    ROAD_WATERLOGGING_KEY,
    SAFETY_HELMET_KEY,
    SLEEPING_KEY,
)

EXTENSION_LABELS_ZH: Dict[str, str] = {
    CALL_KEY: "打电话",
    PHONE_PLAY_KEY: "玩手机",
    GATHER_KEY: "人员聚集",
    SMOKE_KEY: "吸烟",
    FACE_KEY: "人脸",
    FALL_KEY: "跌倒",
    FLAME_KEY: "火焰",
    LICENSE_PLATE_KEY: "车牌",
    MASK_KEY: "未戴口罩",
    REFLECTIVE_VEST_KEY: "未穿反光衣",
    ROAD_WATERLOGGING_KEY: "道路积水",
    SAFETY_HELMET_KEY: "未戴安全帽",
    SLEEPING_KEY: "睡觉",
}

EXTENSION_CATALOG_META: List[Dict[str, str]] = [
    {
        "key": CALL_KEY,
        "name_en": "calling (make_call.onnx dedicated detector)",
        "name_zh": "打电话（make_call.onnx）",
    },
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
        "key": SMOKE_KEY,
        "name_en": "smoking (smoking_detection.pt dedicated detector)",
        "name_zh": "吸烟（smoking_detection.pt）",
    },
    {"key": FACE_KEY, "name_en": "face detection", "name_zh": EXTENSION_LABELS_ZH[FACE_KEY]},
    {"key": FALL_KEY, "name_en": "fall detection", "name_zh": EXTENSION_LABELS_ZH[FALL_KEY]},
    {"key": FLAME_KEY, "name_en": "fire and smoke", "name_zh": EXTENSION_LABELS_ZH[FLAME_KEY]},
    {
        "key": LICENSE_PLATE_KEY,
        "name_en": "license plate detection",
        "name_zh": EXTENSION_LABELS_ZH[LICENSE_PLATE_KEY],
    },
    {
        "key": MASK_KEY,
        "name_en": "face without mask",
        "name_zh": EXTENSION_LABELS_ZH[MASK_KEY],
    },
    {
        "key": REFLECTIVE_VEST_KEY,
        "name_en": "person without reflective vest",
        "name_zh": EXTENSION_LABELS_ZH[REFLECTIVE_VEST_KEY],
    },
    {
        "key": ROAD_WATERLOGGING_KEY,
        "name_en": "road waterlogging / puddle",
        "name_zh": EXTENSION_LABELS_ZH[ROAD_WATERLOGGING_KEY],
    },
    {
        "key": SAFETY_HELMET_KEY,
        "name_en": "person without safety helmet",
        "name_zh": EXTENSION_LABELS_ZH[SAFETY_HELMET_KEY],
    },
    {"key": SLEEPING_KEY, "name_en": "sleeping", "name_zh": EXTENSION_LABELS_ZH[SLEEPING_KEY]},
]

PERSON_BEHAVIOR_KEYS: Tuple[str, ...] = (
    CALL_KEY,
    SMOKE_KEY,
    FALL_KEY,
    MASK_KEY,
    REFLECTIVE_VEST_KEY,
    SAFETY_HELMET_KEY,
    SLEEPING_KEY,
)

SCENE_BEHAVIOR_KEYS: Tuple[str, ...] = (
    FACE_KEY,
    FLAME_KEY,
    LICENSE_PLATE_KEY,
    ROAD_WATERLOGGING_KEY,
)


def default_detections_dict() -> Dict[str, bool]:
    d = {str(i): False for i in range(NUM_COCO_CLASSES)}
    for key in EXTENSION_KEYS:
        d[key] = False
    return d


def normalize_detections(raw: Optional[Dict[str, Any]]) -> Dict[str, bool]:
    """合并旧版配置键与新版「字符串类别 id」键，缺省全部为 False。"""
    out = default_detections_dict()
    if not raw:
        return out
    for k, v in raw.items():
        if v is None:
            continue
        key = str(k)
        if key in EXTENSION_KEYS:
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
    return EXTENSION_LABELS_ZH.get(key, key)


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
            }
        )
    return items


def label_zh_for_class(class_id: int) -> str:
    return COCO_NAMES_ZH.get(class_id, COCO_NAMES.get(class_id, str(class_id)))
