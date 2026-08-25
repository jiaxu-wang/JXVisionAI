"""视频流接入方式（可扩展）。

与检测/告警策略分离：``access_method`` 描述如何接入，``url`` 仍为下游拉流地址。
"""

from __future__ import annotations

from typing import Any, Dict, Optional

# 稳定枚举；UI / 跳转 / 过滤依赖这些值
ACCESS_RTSP_URL = "rtsp_url"
ACCESS_RTMP_URL = "rtmp_url"  # 兼容旧数据；UI 不再提供 RTMP 直连
ACCESS_ONVIF = "onvif"
ACCESS_GB28181 = "gb28181"

ACCESS_METHODS = (
    ACCESS_RTSP_URL,
    ACCESS_RTMP_URL,
    ACCESS_ONVIF,
    ACCESS_GB28181,
)

ACCESS_LABELS = {
    ACCESS_RTSP_URL: "RTSP直连",
    ACCESS_RTMP_URL: "RTMP(已停用)",
    ACCESS_ONVIF: "ONVIF",
    ACCESS_GB28181: "国标 28181",
}

# 管理端「设备接入」内 Tab key（#page=access&tab=...）
ACCESS_PAGE_KEYS = {
    ACCESS_RTSP_URL: "direct",
    ACCESS_ONVIF: "onvif",
    ACCESS_GB28181: "gb28181",
}

DIRECT_ACCESS_METHODS = frozenset({ACCESS_RTSP_URL})


def infer_access_method(stream: Optional[Dict[str, Any]]) -> str:
    """从已有字段推断接入方式（兼容旧数据）。"""
    if not isinstance(stream, dict):
        return ACCESS_RTSP_URL
    raw = (stream.get("access_method") or "").strip().lower()
    if raw in ACCESS_METHODS:
        return raw
    if stream.get("gb28181") and isinstance(stream.get("gb28181"), dict):
        return ACCESS_GB28181
    onvif = stream.get("onvif")
    if isinstance(onvif, dict) and (
        (onvif.get("host") or "").strip() or (onvif.get("profile_token") or "").strip()
    ):
        return ACCESS_ONVIF
    return ACCESS_RTSP_URL


def normalize_access_method(
    value: Any = None, *, stream: Optional[Dict[str, Any]] = None
) -> str:
    """规范化 access_method；无效时按 stream 推断。"""
    raw = (str(value).strip().lower() if value is not None else "")
    if raw in ACCESS_METHODS:
        return raw
    return infer_access_method(stream)


def access_label(method: str) -> str:
    return ACCESS_LABELS.get(method, method or "未知")


def access_page_key(method: str) -> str:
    return ACCESS_PAGE_KEYS.get(normalize_access_method(method), "direct")


def apply_access_fields(stream: Dict[str, Any]) -> Dict[str, Any]:
    """就地写入规范化后的 access_method（及展示用 label）。"""
    method = normalize_access_method(stream.get("access_method"), stream=stream)
    stream["access_method"] = method
    stream["access_label"] = access_label(method)
    stream["access_page"] = access_page_key(method)
    return stream


def is_analysis_joined(stream: Optional[Dict[str, Any]]) -> bool:
    """是否已接入 AI 分析。缺省 True，兼容旧数据（旧流已在检测列表中）。"""
    if not isinstance(stream, dict):
        return False
    if "analyze" not in stream or stream.get("analyze") is None:
        return True
    value = stream.get("analyze")
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true", "yes")
    return bool(value)


def stream_should_analyze(stream: Optional[Dict[str, Any]]) -> bool:
    """检测线程是否应拉流分析：已接入分析且未暂停。"""
    if not isinstance(stream, dict):
        return False
    if not stream.get("enabled", True):
        return False
    return is_analysis_joined(stream)


def apply_analyze_field(
    stream: Dict[str, Any], *, default: Optional[bool] = None
) -> Dict[str, Any]:
    """规范化 analyze 字段。default 仅在字段缺失时使用。"""
    if "analyze" not in stream or stream.get("analyze") is None:
        stream["analyze"] = True if default is None else bool(default)
    else:
        stream["analyze"] = is_analysis_joined(stream)
    return stream
