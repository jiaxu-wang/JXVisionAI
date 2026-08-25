"""国标 GB/T 28181：平台参数 + 设备端 SIP 接入账号（Redis）。

配置分三组，互不回退：
  A. SIP 信令（服务器 ID/域/监听/对外地址）
  B. 媒体收流（仅 Invite / ZLM）
  C. 设备账号与通道（sip_user / auth_id / 通道编码）
"""

from __future__ import annotations

import json
import logging
import socket
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

DEFAULT_PLATFORM: Dict[str, Any] = {
    "enabled": False,
    "server_id": "34020000002000000001",
    "domain": "3402000000",
    "realm": "",
    "bind_host": "0.0.0.0",
    "bind_port": 15060,
    "public_host": "",
    "public_port": 15060,
    "transport": "tcp",
    "protocol_version": "GB/T28181-2022",
    "register_expires_sec": 3600,
    "keepalive_interval_sec": 60,
    "keepalive_timeout_count": 3,
    "password": "",
    "device_password_mode": "per_device",
    "media_ip": "",
    "media_port": 10000,
    "media_port_end": 10200,
    "remark": "",
}

_PLATFORM_KEYS = frozenset(DEFAULT_PLATFORM.keys()) | {
    "sip_host",
    "sip_port",
}


def _prefix(redis_manager) -> str:
    from visionai.config.settings import REDIS_KEY_PREFIX

    return REDIS_KEY_PREFIX


def platform_key(redis_manager) -> str:
    return f"{_prefix(redis_manager)}gb28181/platform"


def devices_key(redis_manager) -> str:
    return f"{_prefix(redis_manager)}gb28181/devices"


def runtime_key(redis_manager) -> str:
    """SIP 运行时状态（由信令服务写入）：field=device_id。"""
    return f"{_prefix(redis_manager)}gb28181/runtime"


def sip_alive_key(redis_manager) -> str:
    return f"{_prefix(redis_manager)}gb28181/sip_alive"


def cmd_key(redis_manager) -> str:
    return f"{_prefix(redis_manager)}gb28181/cmd"


def cmd_result_key(redis_manager, request_id: str) -> str:
    return f"{_prefix(redis_manager)}gb28181/cmd_result:{request_id}"


def _now_str() -> str:
    try:
        from visionai.utils.timeutil import app_now

        return app_now().isoformat(sep=" ", timespec="seconds")
    except Exception:  # noqa: BLE001
        return ""


def _is_usable_ipv4(ip: str) -> bool:
    if not ip or ip in ("0.0.0.0", "255.255.255.255"):
        return False
    if ip.startswith("127.") or ip.startswith("169.254."):
        return False
    return True


def _score_local_ipv4(ip: str) -> int:
    """越大越像摄像机所在局域网地址。"""
    if not _is_usable_ipv4(ip):
        return -1
    if ip.startswith("192.168."):
        return 100
    if ip.startswith("10."):
        return 80
    # Docker / 常见网桥，低于普通 172.16/12
    if ip.startswith("172.17.") or ip.startswith("172.18."):
        return 15
    try:
        a, b = (int(x) for x in ip.split(".")[:2])
    except (TypeError, ValueError):
        return 20
    if a == 172 and 16 <= b <= 31:
        return 50
    return 30


def _ips_from_interfaces() -> List[str]:
    ips: List[str] = []
    try:
        import fcntl
        import struct

        for _idx, name in socket.if_nameindex():
            if name.startswith(("lo", "docker", "br-", "veth", "virbr", "cni", "flannel")):
                continue
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            try:
                raw = fcntl.ioctl(
                    sock.fileno(),
                    0x8915,  # SIOCGIFADDR
                    struct.pack("256s", name.encode("utf-8")[:15]),
                )
                ip = socket.inet_ntoa(raw[20:24])
            except OSError:
                continue
            finally:
                sock.close()
            if _is_usable_ipv4(ip):
                ips.append(ip)
    except Exception:  # noqa: BLE001
        pass
    return ips


def _ip_from_udp_route() -> str:
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.settimeout(0.2)
        sock.connect(("8.8.8.8", 80))
        ip = sock.getsockname()[0]
        sock.close()
        return ip if _is_usable_ipv4(ip) else ""
    except Exception:  # noqa: BLE001
        return ""


def guess_local_ipv4() -> str:
    """选一个本机 IPv4，优先 192.168/10，避免 127.0.0.1。"""
    found = _ips_from_interfaces()
    routed = _ip_from_udp_route()
    if routed:
        found.append(routed)
    best = ""
    best_score = -1
    seen = set()
    for ip in found:
        if ip in seen:
            continue
        seen.add(ip)
        score = _score_local_ipv4(ip)
        if score > best_score:
            best_score = score
            best = ip
    return best if best_score >= 0 else ""


def _port(raw: Any, default: int) -> int:
    try:
        return max(1, min(65535, int(raw)))
    except (TypeError, ValueError):
        return default


def parse_media_port_range(
    raw: Any,
    *,
    start: Any = 10000,
    end: Any = 10200,
) -> Tuple[int, int]:
    """解析「10000-10200」或单一端口；旧配置只有 media_port 时补一段范围。"""
    text = str(raw or "").strip().replace("～", "-").replace("—", "-").replace("~", "-")
    text = "".join(text.split())
    if "-" in text:
        a, b = text.split("-", 1)
        lo = _port(a, 10000)
        hi = _port(b, 10200)
    elif text:
        lo = _port(text, 10000)
        hi = _port(end, max(lo, 10200))
        if hi < lo:
            hi = min(65535, lo + 200)
    else:
        lo = _port(start, 10000)
        hi = _port(end, 10200)
        # 旧数据只有单端口 10000、未配结束端口 → 默认扩到 10200
        if raw in (None, "") and end in (None, "") and hi == lo:
            hi = min(65535, lo + 200)
    if hi < lo:
        lo, hi = hi, lo
    if hi - lo > 5000:
        hi = lo + 5000
    return lo, hi


def normalize_platform(data: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    base = dict(DEFAULT_PLATFORM)
    src = data if isinstance(data, dict) else {}
    for k in _PLATFORM_KEYS:
        if k in src and src[k] is not None:
            base[k] = src[k]

    # 旧字段 sip_host/sip_port 只迁到 bind_*，绝不当成对外地址或媒体 IP
    if "bind_host" not in src and src.get("sip_host"):
        base["bind_host"] = str(src.get("sip_host") or "").strip() or "0.0.0.0"
    base["enabled"] = bool(base.get("enabled"))
    base["server_id"] = str(base.get("server_id") or DEFAULT_PLATFORM["server_id"]).strip()
    base["domain"] = str(base.get("domain") or DEFAULT_PLATFORM["domain"]).strip()
    # Digest realm 与 SIP 域相同，不单独配置（摄像机国标页也只有「域」）
    base["realm"] = base["domain"]
    base["bind_host"] = str(base.get("bind_host") or "0.0.0.0").strip() or "0.0.0.0"
    # 监听端口与对外端口同一值（摄像机「SIP服务器端口」）
    if src.get("public_port") is not None:
        sip_port = _port(src.get("public_port"), 15060)
    elif src.get("bind_port") is not None:
        sip_port = _port(src.get("bind_port"), 15060)
    elif src.get("sip_port") is not None:
        sip_port = _port(src.get("sip_port"), 15060)
    else:
        sip_port = 15060
    base["bind_port"] = sip_port
    public_host = str(base.get("public_host") or "").strip()
    if not public_host or public_host in ("0.0.0.0", "127.0.0.1", "localhost"):
        public_host = guess_local_ipv4()
    base["public_host"] = public_host
    base["public_port"] = sip_port
    base["password"] = str(base.get("password") or "")
    transport = str(base.get("transport") or "tcp").strip().lower()
    base["transport"] = transport if transport in ("udp", "tcp", "both") else "tcp"
    ver = str(base.get("protocol_version") or DEFAULT_PLATFORM["protocol_version"]).strip()
    base["protocol_version"] = ver or DEFAULT_PLATFORM["protocol_version"]
    try:
        base["register_expires_sec"] = max(60, min(86400, int(base.get("register_expires_sec") or 3600)))
    except (TypeError, ValueError):
        base["register_expires_sec"] = 3600
    try:
        base["keepalive_interval_sec"] = max(10, min(600, int(base.get("keepalive_interval_sec") or 60)))
    except (TypeError, ValueError):
        base["keepalive_interval_sec"] = 60
    try:
        base["keepalive_timeout_count"] = max(1, min(20, int(base.get("keepalive_timeout_count") or 3)))
    except (TypeError, ValueError):
        base["keepalive_timeout_count"] = 3
    mode = str(base.get("device_password_mode") or "per_device").strip()
    base["device_password_mode"] = mode if mode in ("platform", "per_device") else "per_device"
    base["media_ip"] = str(base.get("media_ip") or "").strip()
    lo, hi = parse_media_port_range(
        src.get("media_port_range"),
        start=src.get("media_port", base.get("media_port")),
        end=src.get("media_port_end", base.get("media_port_end")),
    )
    base["media_port"] = lo
    base["media_port_end"] = hi
    base["media_port_range"] = f"{lo}-{hi}"
    base["remark"] = str(base.get("remark") or "")[:500]
    # 兼容旧读取方：sip_host/sip_port 仅表示监听，不等于对外地址
    base["sip_host"] = base["bind_host"]
    base["sip_port"] = base["bind_port"]
    return base


def get_platform(redis_manager) -> Dict[str, Any]:
    if not redis_manager or not redis_manager.is_connected():
        return normalize_platform(None)
    try:
        raw = redis_manager._redis_client.get(platform_key(redis_manager))
        if not raw:
            return normalize_platform(None)
        return normalize_platform(json.loads(raw))
    except Exception as e:  # noqa: BLE001
        logger.warning("read gb28181 platform failed: %s", e)
        return normalize_platform(None)


def save_platform(redis_manager, data: Dict[str, Any]) -> Dict[str, Any]:
    plat = normalize_platform(data)
    if not redis_manager or not redis_manager.is_connected():
        raise RuntimeError("Redis未连接")
    redis_manager._redis_client.set(
        platform_key(redis_manager),
        json.dumps(plat, ensure_ascii=False),
    )
    return plat


# 国标编码类型（设备/通道）——GB/T 28181 附录类型码常见取值
# 海康等前端校验：视频通道第 11–13 位须为 131/132；137 为语音输出通道，填到「视频通道」会报错
_TYPE_IPC = "132"  # 网络球机 / 设备 SIP 用户
_TYPE_CHANNEL = "131"  # 视频通道（网络摄像机通道）


def domain_center_code(platform: Dict[str, Any]) -> str:
    """取 10 位中心编码：优先 domain，否则取 server_id 前 10 位。"""
    domain = str(platform.get("domain") or "").strip()
    if len(domain) >= 10 and domain[:10].isdigit():
        return domain[:10]
    sid = str(platform.get("server_id") or "").strip()
    if len(sid) >= 10 and sid[:10].isdigit():
        return sid[:10]
    return "3402000000"


def _max_serial_for_prefix(redis_manager, prefix: str) -> int:
    """prefix = 10位中心码 + 3位类型码，序号为末 7 位。"""
    max_n = 0
    for d in list_devices(redis_manager):
        for key in ("sip_user", "device_id", "channel_id", "auth_id"):
            uid = str(d.get(key) or "").strip()
            if len(uid) == 20 and uid.startswith(prefix) and uid[13:].isdigit():
                max_n = max(max_n, int(uid[13:]))
            for ch in d.get("channels") or []:
                if not isinstance(ch, dict):
                    continue
                cid = str(ch.get("channel_id") or "").strip()
                if len(cid) == 20 and cid.startswith(prefix) and cid[13:].isdigit():
                    max_n = max(max_n, int(cid[13:]))
    return max_n


def allocate_sip_ids(
    redis_manager,
    *,
    channel_id: str = "",
) -> Dict[str, str]:
    """按 GB/T 28181 20 位编码规则自动分配 SIP 用户名、认证 ID。

    格式：中心编码(10) + 类型码(3) + 序号(7)
    - 设备/SIP 用户：类型 132（网络摄像机）
    - 认证 ID：与 SIP 用户名相同（设备侧常见配置）
    - channel_id：可选兼容字段；通道请用 allocate_channel_id / 通道配置管理
    """
    plat = get_platform(redis_manager)
    center = domain_center_code(plat)
    if not center.isdigit() or len(center) != 10:
        raise ValueError("平台域/服务器 ID 无法解析出 10 位中心编码，请先保存合法国标平台参数")

    dev_prefix = f"{center}{_TYPE_IPC}"
    next_serial = _max_serial_for_prefix(redis_manager, dev_prefix) + 1
    ch_prefix = f"{center}{_TYPE_CHANNEL}"
    next_serial = max(next_serial, _max_serial_for_prefix(redis_manager, ch_prefix) + 1)
    if next_serial > 9_999_999:
        raise ValueError("该中心编码下设备序号已满，请更换平台域或清理旧账号")

    sip_user = f"{dev_prefix}{next_serial:07d}"
    auth_id = sip_user
    ch = (channel_id or "").strip()
    if not ch:
        ch = f"{ch_prefix}{next_serial:07d}"
    elif not ch.isdigit():
        ch = f"{ch_prefix}{next_serial:07d}"
    return {
        "sip_user": sip_user,
        "auth_id": auth_id,
        "channel_id": ch,
        "center_code": center,
        "serial": f"{next_serial:07d}",
    }


def allocate_channel_id(redis_manager) -> str:
    """分配下一个未占用的 20 位视频通道编码（类型 131）。"""
    plat = get_platform(redis_manager)
    center = domain_center_code(plat)
    if not center.isdigit() or len(center) != 10:
        raise ValueError("平台域/服务器 ID 无法解析出 10 位中心编码，请先保存合法国标平台参数")
    ch_prefix = f"{center}{_TYPE_CHANNEL}"
    next_serial = _max_serial_for_prefix(redis_manager, ch_prefix) + 1
    if next_serial > 9_999_999:
        raise ValueError("该中心编码下通道序号已满")
    return f"{ch_prefix}{next_serial:07d}"


def normalize_channel(
    ch: Optional[Dict[str, Any]],
    *,
    index: int = 1,
    default_status: str = "offline",
) -> Optional[Dict[str, Any]]:
    if not isinstance(ch, dict):
        return None
    cid = str(ch.get("channel_id") or "").strip()
    if not cid:
        return None
    st = str(ch.get("status") or default_status).strip().lower()
    if st not in ("online", "offline", "unknown"):
        st = default_status if default_status in ("online", "offline", "unknown") else "offline"
    alias = str(ch.get("alias") or ch.get("name") or "").strip() or cid
    try:
        idx = int(ch.get("index") if ch.get("index") is not None else index)
    except (TypeError, ValueError):
        idx = index
    if idx < 1:
        idx = index
    return {
        "index": idx,
        "channel_id": cid,
        "alias": alias,
        "name": alias,  # 兼容旧字段
        "status": st,
    }


def normalize_channels(
    channels_in: Any,
    *,
    default_status: str = "offline",
) -> List[Dict[str, Any]]:
    if not isinstance(channels_in, list):
        return []
    out: List[Dict[str, Any]] = []
    seen = set()
    for i, ch in enumerate(channels_in, start=1):
        row = normalize_channel(ch, index=i, default_status=default_status)
        if not row:
            continue
        cid = row["channel_id"]
        if cid in seen:
            continue
        seen.add(cid)
        out.append(row)
    # 按序号排序并重编号，保证连续
    out.sort(key=lambda x: (int(x.get("index") or 0), str(x.get("channel_id") or "")))
    for i, row in enumerate(out, start=1):
        row["index"] = i
    return out


def normalize_device(data: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    d = data if isinstance(data, dict) else {}
    # SIP 用户名：国标设备编码（20 位常见）
    sip_user = str(
        d.get("sip_user") or d.get("device_id") or d.get("username") or ""
    ).strip()
    auth_id = str(d.get("auth_id") or d.get("sip_auth_id") or sip_user).strip()
    status = str(d.get("status") or "offline").strip().lower()
    if status not in ("online", "offline", "unknown"):
        status = "offline"

    if "channels" in d and isinstance(d.get("channels"), list):
        channels = normalize_channels(d.get("channels"), default_status=status)
    else:
        # 旧数据：单 channel_id → 一条通道
        legacy_cid = str(d.get("channel_id") or "").strip()
        if legacy_cid:
            channels = normalize_channels(
                [
                    {
                        "index": 1,
                        "channel_id": legacy_cid,
                        "alias": str(d.get("name") or legacy_cid).strip(),
                        "status": status,
                    }
                ],
                default_status=status,
            )
        else:
            channels = []

    primary_channel = channels[0]["channel_id"] if channels else str(d.get("channel_id") or "").strip()
    return {
        "device_id": sip_user,
        "sip_user": sip_user,
        "auth_id": auth_id or sip_user,
        "password": str(d.get("password") or ""),
        "name": str(d.get("name") or sip_user).strip(),
        "channel_id": primary_channel,
        "channels": channels,
        "channel_count": len(channels),
        "status": status,
        "last_register_at": str(d.get("last_register_at") or ""),
        "last_keepalive_at": str(d.get("last_keepalive_at") or ""),
        "remote_ip": str(d.get("remote_ip") or ""),
        "source": str(d.get("source") or "provisioned"),
        "updated_at": str(d.get("updated_at") or ""),
        "status_note": str(d.get("status_note") or "")[:300],
        "remark": str(d.get("remark") or "")[:200],
    }


def list_devices(redis_manager) -> List[Dict[str, Any]]:
    if not redis_manager or not redis_manager.is_connected():
        return []
    try:
        raw = redis_manager._redis_client.hgetall(devices_key(redis_manager)) or {}
        out: List[Dict[str, Any]] = []
        for _k, v in raw.items():
            try:
                d = json.loads(v)
                if isinstance(d, dict):
                    out.append(normalize_device(d))
            except Exception:  # noqa: BLE001
                pass
        out.sort(key=lambda x: str(x.get("sip_user") or x.get("device_id") or ""))
        return out
    except Exception as e:  # noqa: BLE001
        logger.warning("list gb28181 devices failed: %s", e)
        return []


def get_device(redis_manager, device_id: str) -> Optional[Dict[str, Any]]:
    device_id = (device_id or "").strip()
    if not device_id or not redis_manager or not redis_manager.is_connected():
        return None
    try:
        raw = redis_manager._redis_client.hget(devices_key(redis_manager), device_id)
        if not raw:
            return None
        return normalize_device(json.loads(raw))
    except Exception:  # noqa: BLE001
        return None


def find_device_for_channel(redis_manager, channel_or_user: str) -> Optional[Dict[str, Any]]:
    """From / DeviceID 可能是通道编码，映射回 SIP 账号。"""
    key = (channel_or_user or "").strip()
    if not key:
        return None
    hit = get_device(redis_manager, key)
    if hit:
        return hit
    for d in list_devices(redis_manager):
        for ch in normalize_channels(d.get("channels") or []):
            if str(ch.get("channel_id") or "") == key:
                return d
    return None


def upsert_device(redis_manager, device: Dict[str, Any]) -> Dict[str, Any]:
    if not redis_manager or not redis_manager.is_connected():
        raise RuntimeError("Redis未连接")
    data = device if isinstance(device, dict) else {}
    # 新建：未传 sip_user 时按国标自动分配用户名与认证 ID
    auto = bool(data.get("auto_allocate", True))
    sip_in = str(
        data.get("sip_user") or data.get("device_id") or data.get("username") or ""
    ).strip()
    allocated: Optional[Dict[str, str]] = None
    if not sip_in and auto:
        allocated = allocate_sip_ids(redis_manager)
        data = {
            **data,
            "sip_user": allocated["sip_user"],
            "device_id": allocated["sip_user"],
            "auth_id": allocated["auth_id"],
        }
        # 新建默认无通道，由「通道配置」单独维护；兼容显式传入 channels / channel_id
        if "channels" not in data:
            legacy_cid = str(data.get("channel_id") or "").strip()
            data["channels"] = (
                [{"index": 1, "channel_id": legacy_cid, "alias": str(data.get("name") or "").strip(), "status": "offline"}]
                if legacy_cid
                else []
            )
    # 更新时未传 channels：保留原通道列表
    prev_peek = get_device(redis_manager, sip_in) if sip_in else None
    if prev_peek and "channels" not in data:
        data = {**data, "channels": prev_peek.get("channels") or []}

    row = normalize_device(data)
    if not row["sip_user"]:
        raise ValueError("缺少 SIP 用户名（设备国标编码）")
    if not row["auth_id"]:
        row["auth_id"] = row["sip_user"]
    # 新建时强制认证 ID = 用户名（国标设备侧常见）
    if allocated is not None:
        row["auth_id"] = row["sip_user"]
    # 保留已有运行时状态（新建时不覆盖 online 字段，除非显式传入）
    prev = get_device(redis_manager, row["sip_user"])
    if prev and "status" not in data:
        row["status"] = prev.get("status") or "offline"
        row["last_register_at"] = prev.get("last_register_at") or ""
        row["last_keepalive_at"] = prev.get("last_keepalive_at") or ""
        row["remote_ip"] = prev.get("remote_ip") or ""
        row["status_note"] = prev.get("status_note") or ""
    if prev and "password" in data and data.get("password") == "":
        # 空密码表示不改密
        row["password"] = prev.get("password") or ""
    if prev and "remark" not in data:
        row["remark"] = prev.get("remark") or ""
    row["device_id"] = row["sip_user"]
    row["source"] = "provisioned"
    row["updated_at"] = _now_str()
    redis_manager._redis_client.hset(
        devices_key(redis_manager),
        row["sip_user"],
        json.dumps(row, ensure_ascii=False),
    )
    try:
        sync_analysis_stream_names(redis_manager, row)
    except Exception:  # noqa: BLE001
        logger.exception("同步分析流名称失败 sip_user=%s", row.get("sip_user"))
    return row


def replace_channels(
    redis_manager,
    device_id: str,
    channels: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """整表替换某 SIP 账号下的通道列表。"""
    prev = get_device(redis_manager, device_id)
    if not prev:
        raise ValueError("账号不存在")
    normalized = normalize_channels(channels, default_status=str(prev.get("status") or "offline"))
    # 校验通道 ID 不与其他设备冲突
    mine = set(c["channel_id"] for c in normalized)
    for d in list_devices(redis_manager):
        other = str(d.get("sip_user") or "")
        if other == (prev.get("sip_user") or device_id):
            continue
        for ch in d.get("channels") or []:
            cid = str((ch or {}).get("channel_id") or "").strip()
            if cid and cid in mine:
                raise ValueError(f"通道 ID {cid} 已被账号 {other} 使用")
    payload = {
        **prev,
        "channels": normalized,
        "channel_id": normalized[0]["channel_id"] if normalized else "",
        "auto_allocate": False,
    }
    return upsert_device(redis_manager, payload)


def add_channel(
    redis_manager,
    device_id: str,
    *,
    channel_id: str = "",
    alias: str = "",
    auto_allocate: bool = True,
) -> Dict[str, Any]:
    prev = get_device(redis_manager, device_id)
    if not prev:
        raise ValueError("账号不存在")
    cid = (channel_id or "").strip()
    if not cid and auto_allocate:
        cid = allocate_channel_id(redis_manager)
    if not cid:
        raise ValueError("缺少通道 ID")
    channels = list(prev.get("channels") or [])
    for ch in channels:
        if str((ch or {}).get("channel_id") or "") == cid:
            raise ValueError(f"通道 ID {cid} 已存在")
    channels.append(
        {
            "index": len(channels) + 1,
            "channel_id": cid,
            "alias": (alias or "").strip() or f"通道{len(channels) + 1}",
            "status": "offline",
        }
    )
    return replace_channels(redis_manager, device_id, channels)


def update_channel(
    redis_manager,
    device_id: str,
    channel_id: str,
    *,
    new_channel_id: Optional[str] = None,
    alias: Optional[str] = None,
    index: Optional[int] = None,
) -> Dict[str, Any]:
    prev = get_device(redis_manager, device_id)
    if not prev:
        raise ValueError("账号不存在")
    channel_id = (channel_id or "").strip()
    channels = list(prev.get("channels") or [])
    found = False
    for ch in channels:
        if str((ch or {}).get("channel_id") or "") != channel_id:
            continue
        found = True
        if new_channel_id is not None and str(new_channel_id).strip():
            nid = str(new_channel_id).strip()
            if nid != channel_id:
                for other in channels:
                    if str((other or {}).get("channel_id") or "") == nid:
                        raise ValueError(f"通道 ID {nid} 已存在")
                ch["channel_id"] = nid
        if alias is not None:
            ch["alias"] = str(alias).strip() or ch.get("alias") or ch["channel_id"]
            ch["name"] = ch["alias"]
        if index is not None:
            try:
                ch["index"] = max(1, int(index))
            except (TypeError, ValueError):
                pass
        break
    if not found:
        raise ValueError("通道不存在")
    return replace_channels(redis_manager, device_id, channels)


def delete_channel(redis_manager, device_id: str, channel_id: str) -> Dict[str, Any]:
    prev = get_device(redis_manager, device_id)
    if not prev:
        raise ValueError("账号不存在")
    channel_id = (channel_id or "").strip()
    channels = [
        ch
        for ch in (prev.get("channels") or [])
        if str((ch or {}).get("channel_id") or "") != channel_id
    ]
    if len(channels) == len(prev.get("channels") or []):
        raise ValueError("通道不存在")
    return replace_channels(redis_manager, device_id, channels)


def delete_device(redis_manager, device_id: str) -> bool:
    if not redis_manager or not redis_manager.is_connected():
        return False
    device_id = (device_id or "").strip()
    if not device_id:
        return False
    try:
        redis_manager._redis_client.hdel(runtime_key(redis_manager), device_id)
    except Exception:  # noqa: BLE001
        pass
    return bool(redis_manager._redis_client.hdel(devices_key(redis_manager), device_id))


def get_runtime_map(redis_manager) -> Dict[str, Dict[str, Any]]:
    if not redis_manager or not redis_manager.is_connected():
        return {}
    try:
        raw = redis_manager._redis_client.hgetall(runtime_key(redis_manager)) or {}
        out: Dict[str, Dict[str, Any]] = {}
        for k, v in raw.items():
            try:
                d = json.loads(v)
                if isinstance(d, dict):
                    out[str(k)] = d
            except Exception:  # noqa: BLE001
                pass
        return out
    except Exception as e:  # noqa: BLE001
        logger.warning("read gb28181 runtime failed: %s", e)
        return {}


def is_sip_alive(redis_manager) -> bool:
    if not redis_manager or not redis_manager.is_connected():
        return False
    try:
        return bool(redis_manager._redis_client.get(sip_alive_key(redis_manager)))
    except Exception:  # noqa: BLE001
        return False


def touch_sip_alive(redis_manager, *, ttl_sec: int = 15) -> None:
    if not redis_manager or not redis_manager.is_connected():
        return
    try:
        redis_manager._redis_client.set(
            sip_alive_key(redis_manager),
            json.dumps({"updated_at": _now_str()}, ensure_ascii=False),
            ex=max(5, int(ttl_sec)),
        )
    except Exception as e:  # noqa: BLE001
        logger.debug("touch sip_alive failed: %s", e)


def write_runtime(redis_manager, device_id: str, data: Dict[str, Any]) -> None:
    if not redis_manager or not redis_manager.is_connected() or not device_id:
        return
    try:
        redis_manager._redis_client.hset(
            runtime_key(redis_manager),
            device_id,
            json.dumps(data, ensure_ascii=False),
        )
    except Exception as e:  # noqa: BLE001
        logger.warning("write gb28181 runtime failed: %s", e)
        return
    # 账号列表读的是 devices，必须同步，否则页面一直离线
    try:
        raw = redis_manager._redis_client.hget(devices_key(redis_manager), device_id)
        if not raw:
            return
        row = json.loads(raw)
        if not isinstance(row, dict):
            return
        st = str(data.get("status") or "offline").lower()
        if st not in ("online", "offline", "unknown"):
            st = "offline"
        row["status"] = st
        if data.get("last_register_at"):
            row["last_register_at"] = data.get("last_register_at")
        if data.get("last_keepalive_at"):
            row["last_keepalive_at"] = data.get("last_keepalive_at")
        row["remote_ip"] = str(data.get("remote_ip") or "")
        row["status_note"] = str(data.get("note") or "")[:300]
        for ch in row.get("channels") or []:
            if isinstance(ch, dict):
                ch["status"] = st
        row["updated_at"] = _now_str()
        redis_manager._redis_client.hset(
            devices_key(redis_manager),
            device_id,
            json.dumps(row, ensure_ascii=False),
        )
    except Exception as e:  # noqa: BLE001
        logger.debug("sync device status from runtime failed: %s", e)


def _runtime_ts(rt: Dict[str, Any]) -> float:
    """解析运行时时间戳（秒）。"""
    best = 0.0
    tz = None
    try:
        from visionai.utils.timeutil import app_now

        tz = app_now().tzinfo
    except Exception:  # noqa: BLE001
        tz = None
    for key in ("last_keepalive_at", "last_register_at", "updated_at"):
        raw = str(rt.get(key) or "").strip().replace("T", " ")[:19]
        if not raw:
            continue
        try:
            dt = datetime.strptime(raw, "%Y-%m-%d %H:%M:%S")
            if tz is not None:
                dt = dt.replace(tzinfo=tz)
            best = max(best, dt.timestamp())
        except ValueError:
            continue
    return best


def runtime_is_fresh(rt: Optional[Dict[str, Any]], plat: Optional[Dict[str, Any]] = None) -> bool:
    """Redis 里的 online 是否仍有效。信令重启后旧记录必须判失效。"""
    if not isinstance(rt, dict) or str(rt.get("status") or "").lower() != "online":
        return False
    plat = plat or {}
    interval = float(plat.get("keepalive_interval_sec") or 60)
    max_miss = int(plat.get("keepalive_timeout_count") or 3)
    limit = max(90.0, interval * max(1, max_miss) * 1.5)
    ts = _runtime_ts(rt)
    if ts <= 0:
        return False
    try:
        from visionai.utils.timeutil import app_now

        now = app_now().timestamp()
    except Exception:  # noqa: BLE001
        now = datetime.now().timestamp()
    return (now - ts) <= limit


def mark_all_runtime_offline(redis_manager, *, note: str = "信令进程已重启，等待重新注册") -> int:
    """信令进程启动时清掉上次的在线缓存，避免列表显示在线但内存无会话。"""
    n = 0
    for did, rt in get_runtime_map(redis_manager).items():
        if str((rt or {}).get("status") or "").lower() != "online":
            continue
        write_runtime(
            redis_manager,
            did,
            {
                "status": "offline",
                "note": note,
                "remote_ip": str((rt or {}).get("remote_ip") or ""),
                "remote_port": (rt or {}).get("remote_port") or 0,
                "transport": str((rt or {}).get("transport") or ""),
            },
        )
        n += 1
    if n:
        logger.info("SIP 启动：已将 %s 路运行时状态置为离线", n)
    return n


def overlay_sip_runtime(
    devices: List[Dict[str, Any]],
    runtime: Dict[str, Dict[str, Any]],
    plat: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    """用 SIP 运行时覆盖账号在线状态（不写 Redis）。"""
    out: List[Dict[str, Any]] = []
    for src in devices:
        d = dict(src)
        did = str(d.get("sip_user") or d.get("device_id") or "")
        rt = runtime.get(did) if did else None
        if isinstance(rt, dict) and rt:
            st = str(rt.get("status") or "offline").lower()
            if st not in ("online", "offline", "unknown"):
                st = "offline"
            note = str(rt.get("note") or "")
            if st == "online" and not runtime_is_fresh(rt, plat):
                st = "offline"
                note = "心跳已过期，等待摄像机重新注册"
            d["status"] = st
            d["last_register_at"] = str(rt.get("last_register_at") or d.get("last_register_at") or "")
            d["last_keepalive_at"] = str(rt.get("last_keepalive_at") or d.get("last_keepalive_at") or "")
            d["remote_ip"] = str(rt.get("remote_ip") or "") if st == "online" else ""
            d["status_note"] = (note or ("来自 SIP 运行时" if st == "online" else "未在 SIP 侧注册"))[:300]
            for ch in d.get("channels") or []:
                if isinstance(ch, dict):
                    ch["status"] = st
        else:
            d["status"] = "offline"
            d["remote_ip"] = ""
            d["status_note"] = "未在 SIP 侧注册（或信令未接通）"
            for ch in d.get("channels") or []:
                if isinstance(ch, dict):
                    ch["status"] = "offline"
        out.append(d)
    return out


def list_devices_live(redis_manager) -> List[Dict[str, Any]]:
    """账号列表 + 当前 SIP 在线状态。"""
    plat = get_platform(redis_manager)
    runtime = get_runtime_map(redis_manager)
    if not is_sip_alive(redis_manager):
        forced: Dict[str, Dict[str, Any]] = {}
        for did, rt in runtime.items():
            row = dict(rt) if isinstance(rt, dict) else {}
            row["status"] = "offline"
            row["note"] = "信令进程未运行"
            forced[did] = row
        runtime = forced
    return overlay_sip_runtime(list_devices(redis_manager), runtime, plat)


def refresh_device_statuses(redis_manager) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """合并 SIP 运行时状态到账号列表。"""
    devices = list_devices_live(redis_manager)
    plat = get_platform(redis_manager)
    sip_ready = is_sip_alive(redis_manager)
    meta = {
        "sip_ready": sip_ready,
        "refreshed_at": _now_str(),
        "message": "",
    }
    if not plat.get("enabled"):
        meta["message"] = "平台未启用：账号可预建，设备无法注册上线。"
    elif not sip_ready:
        meta["message"] = "信令进程未运行：已刷新本地状态（无 heartbeat 的账号显示离线）。"

    updated: List[Dict[str, Any]] = []
    for d in devices:
        did = d.get("sip_user") or d.get("device_id") or ""
        d["updated_at"] = _now_str()
        if redis_manager and redis_manager.is_connected() and did:
            redis_manager._redis_client.hset(
                devices_key(redis_manager),
                did,
                json.dumps(d, ensure_ascii=False),
            )
        updated.append(d)

    if sip_ready and any(d.get("status") == "online" for d in updated):
        meta["message"] = "已根据 SIP 运行时刷新在线状态。"
    elif sip_ready:
        meta["message"] = "信令进程在线，暂无已注册设备。"
    return updated, meta


def effective_password(platform: Dict[str, Any], device: Dict[str, Any]) -> str:
    if str(platform.get("device_password_mode") or "") == "platform":
        return str(platform.get("password") or "")
    return str(device.get("password") or "")


def copy_errors(platform: Dict[str, Any], device: Dict[str, Any]) -> List[str]:
    errs: List[str] = []
    if not str(platform.get("public_host") or "").strip():
        errs.append("请先填写 SIP 对外地址（public_host），不要用媒体收流 IP 代替")
    if not effective_password(platform, device):
        errs.append("缺少 SIP 用户认证密码")
    channels = normalize_channels(device.get("channels") or [])
    if not channels:
        errs.append("请先在通道配置中添加视频通道编码 ID")
    return errs


def device_camera_hint(platform: Dict[str, Any], device: Dict[str, Any]) -> Dict[str, Any]:
    """生成设备国标页对照清单。SIP 服务器地址只用 public_host，不用 media_ip。"""
    platform = normalize_platform(platform)
    channels = normalize_channels(device.get("channels") or [])
    primary = channels[0]["channel_id"] if channels else str(device.get("channel_id") or "")
    transport = str(platform.get("transport") or "tcp").upper()
    if transport == "BOTH":
        transport = "TCP"
    password = effective_password(platform, device)
    hint = {
        "enabled": True,
        "protocol_version": str(platform.get("protocol_version") or "GB/T28181-2022"),
        "sip_server_id": str(platform.get("server_id") or ""),
        "sip_domain": str(platform.get("domain") or ""),
        "sip_server_host": str(platform.get("public_host") or ""),
        "sip_server_port": str(platform.get("public_port") or ""),
        "sip_transport": transport,
        "sip_user": str(device.get("sip_user") or device.get("device_id") or ""),
        "sip_auth_id": str(device.get("auth_id") or ""),
        "sip_password": password,
        "register_expires_sec": int(platform.get("register_expires_sec") or 3600),
        "keepalive_interval_sec": int(platform.get("keepalive_interval_sec") or 60),
        "keepalive_timeout_count": int(platform.get("keepalive_timeout_count") or 3),
        "channel_id": primary,
        "channels": channels,
        "copy_errors": copy_errors(platform, device),
    }
    hint["copy_ok"] = not hint["copy_errors"]
    hint["copy_text"] = format_camera_copy_text(hint) if hint["copy_ok"] else ""
    return hint


def format_camera_copy_text(hint: Dict[str, Any]) -> str:
    ch_lines = []
    for i, ch in enumerate(hint.get("channels") or [], start=1):
        cid = str((ch or {}).get("channel_id") or "")
        alias = str((ch or {}).get("alias") or (ch or {}).get("name") or "")
        extra = f"  别名: {alias}" if alias and alias != cid else ""
        ch_lines.append(f"通道号 {i}: {cid}{extra}")
    if not ch_lines:
        ch_lines.append("(未配置通道)")
    return "\n".join(
        [
            "【上级平台】",
            "启用: 开",
            f"协议版本: {hint.get('protocol_version') or 'GB/T28181-2022'}",
            f"传输协议: {hint.get('sip_transport') or 'TCP'}",
            f"SIP服务器ID: {hint.get('sip_server_id') or ''}",
            f"SIP服务器域: {hint.get('sip_domain') or ''}",
            f"SIP服务器地址: {hint.get('sip_server_host') or ''}",
            f"SIP服务器端口: {hint.get('sip_server_port') or ''}",
            "",
            "【本机注册】",
            f"SIP用户名: {hint.get('sip_user') or ''}",
            f"SIP用户认证ID: {hint.get('sip_auth_id') or ''}",
            f"SIP用户认证密码: {hint.get('sip_password') or ''}",
            f"注册有效期: {hint.get('register_expires_sec') or 3600}",
            f"心跳周期: {hint.get('keepalive_interval_sec') or 60}",
            f"最大心跳超时次数: {hint.get('keepalive_timeout_count') or 3}",
            "",
            "【视频通道编码ID】",
            *ch_lines,
            "",
            "【设备侧保持默认】",
            "本地SIP端口: 5060（设备本机监听，不是平台端口）",
            "28181码流索引: 主码流",
        ]
    )


def merge_catalog_channels(
    redis_manager,
    device_id: str,
    items: List[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    """将 Catalog 上报通道合并进本地列表（保留 alias；新通道默认离线且不加入监控）。"""
    prev = get_device(redis_manager, device_id)
    if not prev:
        return None
    local = list(prev.get("channels") or [])
    by_id = {
        str(c.get("channel_id") or "").strip(): c
        for c in local
        if isinstance(c, dict) and str(c.get("channel_id") or "").strip()
    }
    for it in items:
        if not isinstance(it, dict):
            continue
        cid = str(it.get("channel_id") or it.get("DeviceID") or "").strip()
        if not cid or cid == (prev.get("sip_user") or device_id):
            continue
        name = str(it.get("name") or it.get("Name") or "").strip()
        st = str(it.get("status") or it.get("Status") or "offline").strip().lower()
        if st in ("on", "online", "ok"):
            st = "online"
        elif st in ("off", "offline"):
            st = "offline"
        else:
            st = "unknown"
        if cid in by_id:
            if name and not by_id[cid].get("alias"):
                by_id[cid]["alias"] = name
            by_id[cid]["status"] = st
        else:
            local.append(
                {
                    "index": len(local) + 1,
                    "channel_id": cid,
                    "alias": name or cid,
                    "status": st,
                }
            )
            by_id[cid] = local[-1]
    return replace_channels(redis_manager, device_id, local)


def rtp_stream_id(device_id: str, channel_id: str) -> str:
    return f"{device_id}_{channel_id}".replace(" ", "")


def ssrc_for_channel(channel_id: str, serial: str = "") -> str:
    _ = serial
    digits = "".join(ch for ch in str(channel_id or "") if ch.isdigit())[-9:] or "1"
    return f"0{int(digits) % 1000000000:09d}"


def ssrc_stream_names(ssrc: str) -> List[str]:
    names = [str(ssrc or "")]
    try:
        n = int(ssrc)
        names.append(f"{n:X}")
        names.append(f"{n:08X}")
    except (TypeError, ValueError):
        pass
    out: List[str] = []
    seen = set()
    for n in names:
        if n and n not in seen:
            seen.add(n)
            out.append(n)
    return out


def rtp_name_candidates(device_id: str, channel_id: str) -> List[str]:
    named = rtp_stream_id(device_id, channel_id)
    return [named, *ssrc_stream_names(ssrc_for_channel(channel_id))]


def rtp_pull_url(stream_name: str) -> str:
    try:
        from visionai.config.settings import ZLM_PULL_HOST, ZLM_PULL_RTSP_PORT

        host = (ZLM_PULL_HOST or "").strip() or "127.0.0.1"
        port = int(ZLM_PULL_RTSP_PORT or 554)
    except Exception:  # noqa: BLE001
        host, port = "127.0.0.1", 554
    name = str(stream_name or "").strip() or "stream"
    return f"rtsp://{host}:{port}/rtp/{name}"


def worker_rtp_url(device_id: str, channel_id: str) -> str:
    return rtp_pull_url(rtp_stream_id(device_id, channel_id))


def find_stream_for_channel(streams: List[Dict[str, Any]], device_id: str, channel_id: str):
    device_id = str(device_id or "")
    channel_id = str(channel_id or "")
    if not device_id or not channel_id:
        return None
    for s in streams or []:
        gb = s.get("gb28181") if isinstance(s.get("gb28181"), dict) else {}
        did = str(gb.get("device_id") or gb.get("sip_user") or "")
        cid = str(gb.get("channel_id") or "")
        if did == device_id and cid == channel_id:
            return s
    return None


def sync_analysis_stream_names(redis_manager, device: Dict[str, Any]) -> int:
    """通道别名变更后，同步已接入分析的 streamlist 名称（检测配置读这个字段）。"""
    if not redis_manager or not redis_manager.is_connected():
        return 0
    streams = redis_manager.get_streams() or []
    did = str((device or {}).get("sip_user") or (device or {}).get("device_id") or "")
    if not did:
        return 0
    n = 0
    for ch in normalize_channels((device or {}).get("channels") or []):
        cid = str(ch.get("channel_id") or "")
        alias = str(ch.get("alias") or ch.get("name") or "").strip()
        if not cid or not alias:
            continue
        found = find_stream_for_channel(streams, did, cid)
        if not found:
            continue
        old = str(found.get("name") or "").strip()
        if old == alias:
            continue
        found["name"] = alias
        if not redis_manager.save_stream(found):
            continue
        n += 1
        try:
            from visionai.core.state_manager import get_stream_status, set_stream_status

            set_stream_status(alias, get_stream_status(old, "离线"))
        except Exception:  # noqa: BLE001
            pass
        logger.info(
            "已同步分析流名称 %s → %s (device=%s channel=%s)",
            old,
            alias,
            did,
            cid,
        )
    return n


def attach_monitor_status(
    device: Dict[str, Any], streams: Optional[List[Dict[str, Any]]] = None
) -> Dict[str, Any]:
    """给设备/通道打上是否已写入检测配置（streamlist）的标记。"""
    out = dict(device or {})
    did = str(out.get("sip_user") or out.get("device_id") or "")
    chs = normalize_channels(out.get("channels") or [])
    annotated: List[Dict[str, Any]] = []
    monitored_count = 0
    first_stream_id = ""
    for c in chs:
        row = dict(c)
        cid = str(row.get("channel_id") or "")
        found = find_stream_for_channel(streams or [], did, cid)
        if found:
            row["monitored"] = True
            row["stream_id"] = str(found.get("id") or "")
            monitored_count += 1
            if not first_stream_id:
                first_stream_id = str(found.get("id") or "")
        else:
            row["monitored"] = False
            row["stream_id"] = ""
        annotated.append(row)
    out["channels"] = annotated
    out["monitored_count"] = monitored_count
    out["monitor_stream_id"] = first_stream_id
    return out


def suggested_play_url(device_id: str, channel_id: str, *, rtsp_port: int = 18554) -> str:
    return f"rtsp://127.0.0.1:{rtsp_port}/rtp/{rtp_stream_id(device_id, channel_id)}"
