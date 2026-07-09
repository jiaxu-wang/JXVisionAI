"""config.ini 结构化读写（保留注释）与生效值快照。"""

from __future__ import annotations

import configparser
import os
import re
import shutil
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from jxvisionai.config.config_schema import CONFIG_UNITS, ConfigField, _KEY_TO_SETTINGS_ATTR
from jxvisionai.config.settings import _DEFAULT_INI, _ROOT, resolve_config_path, to_display_path

_ASSIGN_RE = re.compile(r"^(\s*)([A-Za-z_][\w]*)\s*=\s*(.*)$")
_COMMENT_ASSIGN_RE = re.compile(r"^\s*#\s*([A-Za-z_][\w]*)\s*=\s*(.*)$")

_SENSITIVE_KEYWORDS = ("secret", "password")


def config_file_path() -> str:
    return os.environ.get("VISIONAI_CONFIG", _DEFAULT_INI)


def _read_lines(path: str) -> List[str]:
    if not os.path.isfile(path):
        return []
    with open(path, "r", encoding="utf-8") as f:
        return f.readlines()


def _parse_ini_state(lines: List[str]) -> Tuple[Dict[str, str], Dict[str, str], Dict[str, int]]:
    """active 键值、仅注释出现的键、active 键所在行号（0-based）。"""
    active: Dict[str, str] = {}
    commented: Dict[str, str] = {}
    line_index: Dict[str, int] = {}
    for i, line in enumerate(lines):
        cm = _COMMENT_ASSIGN_RE.match(line)
        if cm:
            k = cm.group(1).lower()
            if k not in active:
                commented[k] = cm.group(2).strip()
            continue
        m = _ASSIGN_RE.match(line.rstrip("\n"))
        if not m:
            continue
        k = m.group(2).lower()
        active[k] = m.group(3).strip()
        line_index[k] = i
    return active, commented, line_index


def _effective_raw(key: str) -> Any:
    from jxvisionai.config import settings as s

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
            val = "环境变量 > config.ini > settings.py 内置默认值"
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

    return {
        "key": field.key,
        "label": field.label,
        "type": field.field_type,
        "editable": field.editable,
        "readonly": False,
        "comment": field.comment,
        "value": value,
        "in_file": in_active,
        "commented_only": (not in_active and in_comment),
        "effective_value": eff_display,
        "effective_readonly": True,
    }


def read_structured_units() -> List[Dict[str, Any]]:
    path = config_file_path()
    lines = _read_lines(path)
    active, commented, _ = _parse_ini_state(lines)

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
                "comment": "可由环境变量 VISIONAI_CONFIG 覆盖",
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


def patch_config_updates(updates: Dict[str, str]) -> str:
    """按字段更新 config.ini，保留注释与其余内容；返回保存路径。"""
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

    active, _, line_index = _parse_ini_state(lines)
    changed = set()

    replaced = set()
    for lk, new_val in norm.items():
        orig_key = lk
        for u in CONFIG_UNITS:
            for f in u.fields:
                if f.key.lower() == lk:
                    orig_key = f.key
                    break
        if lk in line_index:
            i = line_index[lk]
            m = _ASSIGN_RE.match(lines[i].rstrip("\n"))
            if m:
                lines[i] = f"{m.group(1)}{orig_key} = {new_val}\n"
                replaced.add(lk)
            continue
        for i, line in enumerate(lines):
            cm = _COMMENT_ASSIGN_RE.match(line)
            if cm and cm.group(1).lower() == lk:
                lines[i] = f"{orig_key} = {new_val}\n"
                replaced.add(lk)
                break

    to_append = [lk for lk in norm if lk not in replaced]
    if to_append:
        if lines and not lines[-1].endswith("\n"):
            lines[-1] += "\n"
        lines.append("\n# --- 由系统设置页写入 ---\n")
        for lk in sorted(to_append):
            # 恢复 schema 中的原始键名大小写
            orig_key = lk
            for u in CONFIG_UNITS:
                for f in u.fields:
                    if f.key.lower() == lk:
                        orig_key = f.key
                        break
            lines.append(f"{orig_key} = {norm[lk]}\n")

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
    if "visionai" not in cp:
        raise ValueError("缺少 [visionai] 节")


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
        "priority": "环境变量 > config.ini > settings.py 内置默认值",
        "restart_required": True,
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
                }
            )
        out.append({"title": u["title"], "items": items})
    return out
