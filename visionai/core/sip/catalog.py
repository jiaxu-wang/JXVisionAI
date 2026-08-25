"""GB28181 Catalog XML."""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from typing import Any, Dict, List


def _local(tag: str) -> str:
    if "}" in tag:
        return tag.rsplit("}", 1)[-1]
    return tag


def manscdp_cmd(body: str) -> str:
    m = re.search(r"<CmdType>\s*([^<]+)\s*</CmdType>", body or "", re.I)
    return (m.group(1).strip() if m else "")


def manscdp_sn(body: str) -> str:
    m = re.search(r"<SN>\s*([^<]+)\s*</SN>", body or "", re.I)
    return (m.group(1).strip() if m else "")


def manscdp_device_id(body: str) -> str:
    m = re.search(r"<DeviceID>\s*([^<]+)\s*</DeviceID>", body or "", re.I)
    return (m.group(1).strip() if m else "")


def parse_catalog_items(body: str) -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    if not (body or "").strip():
        return items
    try:
        root = ET.fromstring(body)
    except ET.ParseError:
        return _parse_catalog_regex(body)
    for el in root.iter():
        if _local(el.tag) != "Item":
            continue
        row: Dict[str, Any] = {}
        for child in list(el):
            row[_local(child.tag)] = (child.text or "").strip()
        cid = row.get("DeviceID") or ""
        if cid:
            items.append(
                {
                    "channel_id": cid,
                    "name": row.get("Name") or "",
                    "status": row.get("Status") or "",
                    "ptz_type": row.get("PTZType") or "",
                }
            )
    return items


def _parse_catalog_regex(body: str) -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    for block in re.findall(r"<Item>(.*?)</Item>", body, flags=re.I | re.S):
        did = re.search(r"<DeviceID>\s*([^<]+)\s*</DeviceID>", block, re.I)
        if not did:
            continue
        name = re.search(r"<Name>\s*([^<]+)\s*</Name>", block, re.I)
        st = re.search(r"<Status>\s*([^<]+)\s*</Status>", block, re.I)
        ptz = re.search(r"<PTZType>\s*([^<]+)\s*</PTZType>", block, re.I)
        items.append(
            {
                "channel_id": did.group(1).strip(),
                "name": name.group(1).strip() if name else "",
                "status": st.group(1).strip() if st else "",
                "ptz_type": ptz.group(1).strip() if ptz else "",
            }
        )
    return items


def catalog_query_xml(device_id: str, sn: int) -> str:
    return (
        '<?xml version="1.0" encoding="GB2312"?>\r\n'
        "<Query>\r\n"
        "<CmdType>Catalog</CmdType>\r\n"
        f"<SN>{sn}</SN>\r\n"
        f"<DeviceID>{device_id}</DeviceID>\r\n"
        "</Query>\r\n"
    )


def keepalive_ok(body: str) -> bool:
    cmd = manscdp_cmd(body).lower()
    return cmd == "keepalive"
