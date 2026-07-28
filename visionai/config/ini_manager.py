"""config.ini 结构化读写（保留注释、多分节）与生效值快照。"""

from __future__ import annotations

import configparser
import os
import re
import shutil
from datetime import datetime
from typing import Any, Dict, List, Tuple

from visionai.config.config_schema import CONFIG_UNITS, ConfigField, _KEY_TO_SETTINGS_ATTR
from visionai.config.ini_sections import (
    canonicalize,
    has_valid_sections,
    normalize_section,
    preferred_ini_key,
    preferred_section,
    write_location,
)
from visionai.config.settings import _DEFAULT_INI, _ROOT, resolve_config_path, to_display_path

_ASSIGN_RE = re.compile(r"^(\s*)([A-Za-z_][\w]*)\s*=\s*(.*)$")
_COMMENT_ASSIGN_RE = re.compile(r"^\s*#\s*([A-Za-z_][\w]*)\s*=\s*(.*)$")
_SECTION_RE = re.compile(r"^\s*\[([^\]]+)\]\s*(?:#.*)?$")

_SENSITIVE_KEYWORDS = ("secret", "password")


def config_file_path() -> str:
    return os.environ.get("VISIONAI_CONFIG", _DEFAULT_INI)


def _read_lines(path: str) -> List[str]:
    if not os.path.isfile(path):
        return []
    with open(path, "r", encoding="utf-8") as f:
        return f.readlines()


def _parse_ini_state(
    lines: List[str],
) -> Tuple[Dict[str, str], Dict[str, str], Dict[str, int], Dict[str, str], Dict[str, int]]:
    """
    返回：
    - active: 规范键 → 值
    - commented: 规范键 → 注释中的值
    - line_index: 规范键 → 活动赋值行号
    - local_keys: 规范键 → 文件内键名（用于写回）
    - section_headers: 规范节名 → ``[section]`` 行号
    """
    active: Dict[str, str] = {}
    commented: Dict[str, str] = {}
    line_index: Dict[str, int] = {}
    local_keys: Dict[str, str] = {}
    section_headers: Dict[str, int] = {}
    current_section = ""

    for i, line in enumerate(lines):
        sm = _SECTION_RE.match(line.rstrip("\n"))
        if sm:
            current_section = normalize_section(sm.group(1))
            section_headers[current_section] = i
            continue

        cm = _COMMENT_ASSIGN_RE.match(line)
        if cm:
            raw_k = cm.group(1)
            canon = canonicalize(current_section, raw_k)
            if canon and canon not in active:
                commented[canon] = cm.group(2).strip()
            continue

        m = _ASSIGN_RE.match(line.rstrip("\n"))
        if not m:
            continue
        raw_k = m.group(2)
        canon = canonicalize(current_section, raw_k)
        if not canon:
            continue
        active[canon] = m.group(3).strip()
        line_index[canon] = i
        local_keys[canon] = raw_k
    return active, commented, line_index, local_keys, section_headers


def _effective_raw(key: str) -> Any:
    from visionai.config import settings as s

    attr = _KEY_TO_SETTINGS_ATTR.get(key, key.upper())
    return getattr(s, attr, None)


def _mask_value(key: str, value: Any) -> str:
    s = "" if value is None else str(value)
    lk = key.lower()
    if any(w in lk for w in _SENSITIVE_KEYWORDS):
        if not s:
            return ""
        if len(s) <= 4:
            return "****"
        return s[:2] + "****" + s[-2:]
    return s


def _field_payload(
    field: ConfigField,
    active: Dict[str, str],
    commented: Dict[str, str],
    *,
    include_effective: bool,
) -> Dict[str, Any]:
    if field.readonly:
        val = ""
        if field.key == "_priority":
            val = "环境变量 > config.ini（多分节）> settings.py 内置默认值"
        elif field.key == "_restart":
            val = "保存后重启服务生效"
        elif field.key == "_config_path":
            val = config_file_path()
        return {
            "key": field.key,
            "label": field.label,
            "type": field.field_type,
            "editable": False,
            "readonly": True,
            "comment": field.comment,
            "section": getattr(field, "section", "") or "",
            "ini_key": "",
            "value": val,
            "in_file": False,
            "commented_only": False,
        }

    k = field.key.lower()
    in_active = k in active
    in_comment = k in commented
    value = active.get(k, commented.get(k, ""))
    if field.relative_path and value.strip():
        value = to_display_path(resolve_config_path(value))
    eff = _effective_raw(field.key) if include_effective else None
    eff_display = None
    if include_effective and eff is not None:
        eff_display = _mask_value(field.key, eff)
        if field.relative_path and eff_display and "****" not in eff_display:
            eff_display = to_display_path(str(eff))

    sec, ini_k = write_location(k)
    return {
        "key": field.key,
        "label": field.label,
        "type": field.field_type,
        "editable": field.editable,
        "readonly": False,
        "comment": field.comment,
        "section": field.section or sec,
        "ini_key": field.ini_key or ini_k,
        "value": value,
        "in_file": in_active,
        "commented_only": (not in_active and in_comment),
        "effective_value": eff_display,
        "effective_readonly": True,
    }


def read_structured_units() -> List[Dict[str, Any]]:
    path = config_file_path()
    lines = _read_lines(path)
    active, commented, _, _, _ = _parse_ini_state(lines)

    units: List[Dict[str, Any]] = []
    meta_unit = {
        "id": "meta",
        "title": "配置说明",
        "description": CONFIG_UNITS[0].description,
        "fields": [
            _field_payload(CONFIG_UNITS[0].fields[0], active, commented, include_effective=False),
            _field_payload(CONFIG_UNITS[0].fields[1], active, commented, include_effective=False),
            {
                "key": "_config_path",
                "label": "配置文件路径",
                "type": "readonly",
                "editable": False,
                "readonly": True,
                "comment": "可由环境变量 VISIONAI_CONFIG 覆盖；节：[basic]/[redis]/[minio]/[email]/[models]",
                "value": path,
                "in_file": False,
                "commented_only": False,
            },
        ],
    }
    units.append(meta_unit)

    for unit in CONFIG_UNITS:
        if unit.id == "meta":
            continue
        fields = [
            _field_payload(f, active, commented, include_effective=True) for f in unit.fields
        ]
        units.append(
            {
                "id": unit.id,
                "title": unit.title,
                "description": unit.description,
                "fields": fields,
            }
        )
    return units


def _format_value(key: str, value: str) -> str:
    v = (value or "").strip()
    if v.lower() in ("true", "false"):
        return v.lower()
    return v


def _schema_orig_key(lk: str) -> str:
    for u in CONFIG_UNITS:
        for f in u.fields:
            if f.key.lower() == lk:
                return f.key
    return lk


def _ensure_section(lines: List[str], section: str, section_headers: Dict[str, int]) -> int:
    """确保节存在，返回可在其后追加键的插入行号（节标题下一行起）。"""
    sec = normalize_section(section)
    if sec in section_headers:
        return section_headers[sec] + 1

    if lines and not lines[-1].endswith("\n"):
        lines[-1] += "\n"
    if lines and lines[-1].strip():
        lines.append("\n")
    lines.append(f"[{sec}]\n")
    section_headers[sec] = len(lines) - 1
    return len(lines)


def patch_config_updates(updates: Dict[str, str]) -> str:
    """按规范键更新 config.ini，写入对应分节；保留注释与其余内容。"""
    if not updates:
        raise ValueError("没有可保存的配置项")

    allowed = {
        f.key.lower()
        for u in CONFIG_UNITS
        for f in u.fields
        if f.editable and not f.readonly
    }
    norm: Dict[str, str] = {}
    for k, v in updates.items():
        lk = str(k).lower().strip()
        if lk not in allowed:
            continue
        norm[lk] = _format_value(lk, str(v))

    if not norm:
        raise ValueError("提交的配置项无效")

    path = config_file_path()
    lines = _read_lines(path)
    if not lines:
        raise ValueError("config.ini 不存在或为空")

    active, _, line_index, local_keys, section_headers = _parse_ini_state(lines)
    replaced = set()

    for lk, new_val in norm.items():
        file_key = local_keys.get(lk) or preferred_ini_key(lk)
        if lk in line_index:
            i = line_index[lk]
            m = _ASSIGN_RE.match(lines[i].rstrip("\n"))
            if m:
                lines[i] = f"{m.group(1)}{file_key} = {new_val}\n"
                replaced.add(lk)
                continue
        # 注释行取消注释并写入
        current_section = ""
        for i, line in enumerate(lines):
            sm = _SECTION_RE.match(line.rstrip("\n"))
            if sm:
                current_section = normalize_section(sm.group(1))
                continue
            cm = _COMMENT_ASSIGN_RE.match(line)
            if not cm:
                continue
            canon = canonicalize(current_section, cm.group(1))
            if canon == lk:
                lines[i] = f"{preferred_ini_key(lk)} = {new_val}\n"
                replaced.add(lk)
                break

    to_append = [lk for lk in norm if lk not in replaced]
    # 按目标节分组追加
    by_section: Dict[str, List[str]] = {}
    for lk in to_append:
        sec = preferred_section(lk)
        by_section.setdefault(sec, []).append(lk)

    for sec, keys in sorted(by_section.items()):
        # 重新解析节头（可能刚插入过）
        _, _, _, _, section_headers = _parse_ini_state(lines)
        insert_at = _ensure_section(lines, sec, section_headers)
        # 找节尾：下一节标题之前
        end = len(lines)
        for j in range(insert_at, len(lines)):
            if _SECTION_RE.match(lines[j].rstrip("\n")):
                end = j
                break
        block = []
        for lk in sorted(keys):
            block.append(f"{preferred_ini_key(lk)} = {norm[lk]}\n")
        lines[end:end] = block

    content = "".join(lines)
    validate_config_text(content)

    if os.path.isfile(path):
        shutil.copy2(path, path + ".bak")
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        f.write(content)
    os.replace(tmp, path)
    return path


def read_config_text() -> Tuple[str, str]:
    path = config_file_path()
    return path, "".join(_read_lines(path))


def validate_config_text(content: str) -> None:
    if not content or not content.strip():
        raise ValueError("配置内容不能为空")
    cp = configparser.ConfigParser(interpolation=None)
    cp.read_string(content)
    if not has_valid_sections(cp.sections()):
        raise ValueError(
            "缺少有效配置节：需要 [basic]/[redis]/[minio]/[email]/[models] 之一，"
            "或旧版 [visionai]"
        )


def write_config_text(content: str) -> str:
    validate_config_text(content)
    path = config_file_path()
    if os.path.isfile(path):
        shutil.copy2(path, path + ".bak")
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        f.write(content)
        if not content.endswith("\n"):
            f.write("\n")
    os.replace(tmp, path)
    return path


def config_meta() -> Dict[str, Any]:
    path = config_file_path()
    mtime = None
    if os.path.isfile(path):
        mtime = datetime.fromtimestamp(os.path.getmtime(path)).isoformat(timespec="seconds")
    env_override = os.environ.get("VISIONAI_CONFIG", "")
    return {
        "path": path,
        "project_root": _ROOT,
        "mtime": mtime,
        "env_config_override": env_override or None,
        "priority": "环境变量 > config.ini（多分节）> settings.py 内置默认值",
        "restart_required": True,
        "sections": ["basic", "redis", "minio", "email", "models", "preview"],
    }


def effective_settings_groups() -> List[Dict[str, Any]]:
    """兼容旧接口：扁平分组。"""
    units = read_structured_units()
    out: List[Dict[str, Any]] = []
    for u in units:
        if u["id"] == "meta":
            continue
        items = []
        for f in u.get("fields", []):
            if f.get("readonly"):
                continue
            items.append(
                {
                    "key": f["key"],
                    "value": f.get("effective_value") or f.get("value", ""),
                    "sensitive": any(w in f["key"].lower() for w in _SENSITIVE_KEYWORDS),
                    "section": f.get("section"),
                }
            )
        out.append({"title": u["title"], "items": items})
    return out
