"""GB/T 28181 云台 PTZCmd（8 字节）与 DeviceControl XML。"""

from __future__ import annotations

from typing import Any, Dict, Optional, Tuple

# 方向 / 变倍（字节 3）。海康按附录常用位：bit0 右 bit1 左 bit2 上 bit3 下 bit4 放大 bit5 缩小。
# 若把 bit4/bit5 当左右，摄像机会把左右当成拉近/拉远，斜向组合会被丢弃。
_BIT_RIGHT = 0x01
_BIT_LEFT = 0x02
_BIT_UP = 0x04
_BIT_DOWN = 0x08
_BIT_ZOOM_IN = 0x10
_BIT_ZOOM_OUT = 0x20

# 聚焦 / 光圈
_BIT_IRIS_CLOSE = 0x01
_BIT_IRIS_OPEN = 0x02
_BIT_FOCUS_NEAR = 0x04
_BIT_FOCUS_FAR = 0x08

_MOVE = {
    "up": (0, 1, 0),
    "down": (0, -1, 0),
    "left": (-1, 0, 0),
    "right": (1, 0, 0),
    "upleft": (-1, 1, 0),
    "upright": (1, 1, 0),
    "downleft": (-1, -1, 0),
    "downright": (1, -1, 0),
    "zoom_in": (0, 0, 1),
    "zoom_out": (0, 0, -1),
}

_FI = {
    "focus_near": (1, 0),
    "focus_far": (-1, 0),
    "iris_open": (0, 1),
    "iris_close": (0, -1),
}


def clamp_ui_speed(speed: Any) -> int:
    try:
        n = int(speed)
    except (TypeError, ValueError):
        n = 4
    return max(1, min(8, n))


def speed_byte(speed: Any) -> int:
    """UI 1–8 → 0x1F…0xFF。"""
    return min(255, clamp_ui_speed(speed) * 32 - 1)


def _address(address: Any) -> int:
    try:
        n = int(address)
    except (TypeError, ValueError):
        n = 1
    return max(1, min(0xFFF, n))


def pack_frame(cmd: int, data1: int = 0, data2: int = 0, data3_hi: int = 0, *, address: int = 1) -> str:
    """组装 8 字节 PTZCmd 十六进制（大写）。"""
    addr = _address(address)
    b = [0] * 8
    b[0] = 0xA5
    b[2] = addr & 0xFF
    b[3] = int(cmd) & 0xFF
    b[4] = int(data1) & 0xFF
    b[5] = int(data2) & 0xFF
    b[6] = ((int(data3_hi) & 0x0F) << 4) | ((addr >> 8) & 0x0F)
    check1 = (
        (b[0] >> 4)
        + (b[0] & 0x0F)
        + (b[1] >> 4)
        + b[2]
        + b[3]
        + b[4]
        + b[5]
        + b[6]
    ) & 0x0F
    b[1] = check1
    b[7] = sum(b[:7]) & 0xFF
    return "".join(f"{x:02X}" for x in b)


def encode_stop(*, address: int = 1) -> str:
    return pack_frame(0, address=address)


def encode_move(pan: int, tilt: int, zoom: int, speed: Any = 4, *, address: int = 1) -> str:
    cmd = 0
    if pan < 0:
        cmd |= _BIT_LEFT
    elif pan > 0:
        cmd |= _BIT_RIGHT
    if tilt > 0:
        cmd |= _BIT_UP
    elif tilt < 0:
        cmd |= _BIT_DOWN
    if zoom > 0:
        cmd |= _BIT_ZOOM_IN
    elif zoom < 0:
        cmd |= _BIT_ZOOM_OUT
    sp = speed_byte(speed)
    pan_sp = sp if pan else 0
    tilt_sp = sp if tilt else 0
    zoom_hi = clamp_ui_speed(speed) if zoom else 0
    if not cmd:
        return encode_stop(address=address)
    return pack_frame(cmd, pan_sp, tilt_sp, zoom_hi, address=address)


def encode_fi(focus: int, iris: int, speed: Any = 4, *, address: int = 1) -> str:
    cmd = 0
    if focus > 0:
        cmd |= _BIT_FOCUS_NEAR
    elif focus < 0:
        cmd |= _BIT_FOCUS_FAR
    if iris > 0:
        cmd |= _BIT_IRIS_OPEN
    elif iris < 0:
        cmd |= _BIT_IRIS_CLOSE
    sp = speed_byte(speed)
    focus_sp = sp if focus else 0
    iris_sp = sp if iris else 0
    if not cmd:
        return encode_stop(address=address)
    return pack_frame(cmd, focus_sp, iris_sp, 0, address=address)


def control_xml(channel_id: str, sn: int, ptz_hex: str) -> str:
    cid = (channel_id or "").strip()
    hx = (ptz_hex or "").strip().upper()
    return (
        '<?xml version="1.0" encoding="GB2312"?>\r\n'
        "<Control>\r\n"
        "<CmdType>DeviceControl</CmdType>\r\n"
        f"<SN>{int(sn)}</SN>\r\n"
        f"<DeviceID>{cid}</DeviceID>\r\n"
        f"<PTZCmd>{hx}</PTZCmd>\r\n"
        "</Control>\r\n"
    )


def encode_action(spec: Optional[Dict[str, Any]] = None) -> Tuple[str, str]:
    """把 API action 编成 PTZCmd。返回 (hex, error)。"""
    spec = spec if isinstance(spec, dict) else {}
    action = str(spec.get("action") or "").strip().lower()
    address = spec.get("address") or 1
    speed = spec.get("speed")
    if not action:
        return "", "缺少 action"
    if action == "stop":
        return encode_stop(address=address), ""
    if action in _MOVE:
        pan, tilt, zoom = _MOVE[action]
        return encode_move(pan, tilt, zoom, speed, address=address), ""
    if action in _FI:
        focus, iris = _FI[action]
        return encode_fi(focus, iris, speed, address=address), ""
    return "", f"未知 action {action}"
