"""COCO 80 类与「打电话」扩展：与 Ultralytics 预训练 YOLOv8（COCO）类别索引一致。"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

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


def default_detections_dict() -> Dict[str, bool]:
    d = {str(i): False for i in range(NUM_COCO_CLASSES)}
    d[CALL_KEY] = False
    d[PHONE_PLAY_KEY] = False
    d[GATHER_KEY] = False
    d[SMOKE_KEY] = False
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
        if key == CALL_KEY:
            out[CALL_KEY] = bool(v)
        elif key == PHONE_PLAY_KEY:
            out[PHONE_PLAY_KEY] = bool(v)
        elif key == GATHER_KEY:
            out[GATHER_KEY] = bool(v)
        elif key == SMOKE_KEY:
            out[SMOKE_KEY] = bool(v)
        elif key in out and key.isdigit():
            out[key] = bool(v)
        elif key in _LEGACY_DETECTION_KEY_TO_CLASS_ID:
            cid = _LEGACY_DETECTION_KEY_TO_CLASS_ID[key]
            out[str(cid)] = bool(v)
        elif key.isdigit() and 0 <= int(key) < NUM_COCO_CLASSES:
            out[key] = bool(v)
    return out


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
    items.append(
        {
            "key": CALL_KEY,
            "class_id": None,
            "name_en": "calling (YOLO+COCO overlap + pose: phone near ear/head)",
            "name_zh": "打电话",
            "supported": True,
        }
    )
    items.append(
        {
            "key": PHONE_PLAY_KEY,
            "class_id": None,
            "name_en": "playing with phone (same overlap + pose: hands/in front)",
            "name_zh": "玩手机",
            "supported": True,
        }
    )
    items.append(
        {
            "key": GATHER_KEY,
            "class_id": None,
            "name_en": "crowd gathering (min persons in frame)",
            "name_zh": "人员聚集",
            "supported": True,
        }
    )
    items.append(
        {
            "key": SMOKE_KEY,
            "class_id": None,
            "name_en": "smoking (person crop + ONNX classifier)",
            "name_zh": "吸烟",
            "supported": True,
        }
    )
    return items


def label_zh_for_class(class_id: int) -> str:
    return COCO_NAMES_ZH.get(class_id, COCO_NAMES.get(class_id, str(class_id)))
