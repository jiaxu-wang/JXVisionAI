"""告警类型展示名：Redis 仍用中文协议值，推送文案跟随 [ui] language。"""

from __future__ import annotations

from typing import Dict, List, Optional, Sequence, Tuple

from visionai.config.detection_catalog import EXTENSION_LABELS_EN, EXTENSION_LABELS_ZH

# 类型后缀 / 疲劳原因（出现在 unit.label 里，一并按默认语言翻译）
_TAIL_EN: Dict[str, str] = {
    "库内": "known",
    "陌生车牌": "unknown plate",
    "陌生人": "stranger",
    "闭眼占比高": "high PERCLOS",
    "打哈欠": "yawning",
    "低头": "nodding",
}


def alert_ui_locale() -> str:
    """当前告警推送使用的默认语言（读 ini，不经过 worker 内存快照）。"""
    try:
        from visionai.config.ini_manager import read_ui_language

        return read_ui_language()
    except Exception:  # noqa: BLE001
        return "zh"


def _zh_to_en_map() -> Dict[str, str]:
    out: Dict[str, str] = {}
    try:
        from visionai.config.detection_catalog import catalog_items_for_api

        for item in catalog_items_for_api():
            zh = str(item.get("name_zh") or "").strip()
            en = str(item.get("name_en") or "").strip()
            if zh and en:
                out[zh] = en
    except Exception:  # noqa: BLE001
        pass
    for key, zh in EXTENSION_LABELS_ZH.items():
        en = EXTENSION_LABELS_EN.get(key)
        if zh and en:
            out[zh] = en
    return out


def _split_colon(label: str) -> Tuple[str, str, str]:
    for sep in (":", "："):
        i = label.find(sep)
        if i >= 0:
            return label[:i].strip(), sep, label[i + len(sep) :]
    return label, "", ""


def _lookup_en(zh: str, mapping: Dict[str, str]) -> Optional[str]:
    s = (zh or "").strip()
    if not s:
        return None
    if s in mapping:
        return mapping[s]
    best = ""
    mapped = ""
    for key, en in mapping.items():
        if key and s.startswith(key) and len(key) > len(best):
            best = key
            mapped = en
    if not best:
        return None
    rest = s[len(best) :]
    return mapped + rest


def _localize_tail(raw: str, locale: str) -> str:
    if locale != "en":
        return raw
    leading = ""
    body = raw
    while body[:1].isspace():
        leading += body[:1]
        body = body[1:]
    if not body:
        return raw
    parts = [p.strip() for p in body.split("/")]
    out = [_TAIL_EN.get(p, p) for p in parts]
    return leading + "/".join(out)


def display_type_label(zh_label: str, locale: str = "zh") -> str:
    """把中文协议类型（可带 :后缀 / ·疲劳原因）转成当前默认语言的展示名。"""
    s = (zh_label or "").strip()
    if not s or locale != "en":
        return s
    mapping = _zh_to_en_map()
    mid = " · "
    if mid in s:
        head, rest = s.split(mid, 1)
        en_head = _lookup_en(head.strip(), mapping)
        if en_head:
            reasons = [_TAIL_EN.get(p.strip(), p.strip()) for p in rest.split("/")]
            return en_head + mid + "/".join(reasons)
    prefix, _sep, suffix = _split_colon(s)
    en = _lookup_en(prefix, mapping)
    if not en:
        return s
    tail = _localize_tail(suffix, locale).strip()
    if not tail:
        return en
    return f"{en}: {tail}"


def display_detection_types(
    types: Sequence[str],
    locale: Optional[str] = None,
) -> List[str]:
    loc = locale or alert_ui_locale()
    return [display_type_label(x, loc) for x in types]
