"""预览地址和推理地址分开。

``url`` 仍给预览和 ZLM 播放。``analyze_url`` 有值时，检测线程改拉这一路
（通常是子码流），播放代理继续用原来的流 ID。
"""

from __future__ import annotations

from typing import Any, Dict


def normalize_analyze_url(raw: Any) -> str:
    """只接受 rtsp/rtsps。空串表示跟预览同一路。"""
    s = str(raw or "").strip()
    if not s:
        return ""
    from visionai.utils.rtsp_url import normalize_rtsp_url

    url = normalize_rtsp_url(s)
    low = url.lower()
    if not low.startswith(("rtsp://", "rtsps://")):
        return ""
    return url


def inference_plan(stream: Dict[str, Any] | None) -> Dict[str, Any]:
    """推理拉流计划。没填分析地址时 key 固定为 primary，避免国标 RTP 地址变化被当成换源。"""
    info = stream or {}
    sid = str(info.get("id") or info.get("name") or "stream").strip() or "stream"
    analyze = normalize_analyze_url(info.get("analyze_url"))
    if analyze:
        return {
            "use_analyze": True,
            "source": analyze,
            "zlm_id": f"{sid}__an",
            "key": "analyze:" + analyze,
        }
    return {
        "use_analyze": False,
        "source": "",
        "zlm_id": sid,
        "key": "primary",
    }
