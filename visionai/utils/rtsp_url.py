"""RTSP/RTSPS 地址规范化：密码中含 `@` 时必须编码为 %40，否则与主机前的 `@` 冲突。"""

from __future__ import annotations

from urllib.parse import quote


def normalize_rtsp_url(url: str) -> str:
    """
    将 rtsp://user:password@host:port/... 中 password 的 `@` 编码为 %40。

    反例：rtsp://admin:inrico@123@192.168.2.72:554/... 中第二个 @ 会误解析到主机为 123@...，
    导致拉流/检测线程与 OpenCV 表现不一致（或一处成功一处失败）。

    若密码中无 `@` 或 scheme 非 rtsp，原样返回。
    """
    u = (url or "").strip()
    if not u or "://" not in u:
        return u
    parts = u.split("://", 1)
    if len(parts) != 2:
        return u
    scheme, rest = parts[0].lower(), parts[1]
    if scheme not in ("rtsp", "rtsps"):
        return u
    if "/" in rest:
        i = rest.find("/")
        authority, path = rest[:i], rest[i:]
    else:
        authority, path = rest, ""
    # 最后一个 @ 为「认证」与「主机:端口」分界（RFC 3986 中 userinfo 与 reg-name）
    at = authority.rfind("@")
    if at < 0:
        return u
    userinfo, hostport = authority[:at], authority[at + 1 :]
    colon = userinfo.find(":")
    if colon < 0:
        return u
    user, password = userinfo[:colon], userinfo[colon + 1 :]
    if "@" in password:
        enc = quote(password, safe="")
        return f"{scheme}://{user}:{enc}@{hostport}{path}"
    return u
