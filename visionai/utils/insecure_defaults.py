"""Known-public / placeholder secrets that must not be used in production."""

from __future__ import annotations

from typing import Iterable

# Historical values that appeared in git or docs. Treat as compromised.
KNOWN_INSECURE_SECRETS = frozenset(
    {
        "123456-bb6b-4889-a715-d9eb2d1925cc",
        "VisionAI@2026",
        "minioadmin",
        "jxvisionai-zlm-a7f3c91e4b2d6e80",
        "changeme",
        "password",
        "secret",
        "admin",
    }
)


def is_insecure_secret(value: str) -> bool:
    s = (value or "").strip()
    if not s:
        return False
    if s in KNOWN_INSECURE_SECRETS:
        return True
    return s.lower() in KNOWN_INSECURE_SECRETS


def warn_insecure_secrets(pairs: Iterable[tuple[str, str]], log) -> None:
    for name, value in pairs:
        if is_insecure_secret(value):
            log.warning(
                "安全警告: %s 使用了已公开的演示/历史口令，生产环境必须轮换",
                name,
            )


def require_login_secret(secret: str) -> None:
    """Refuse to bind a public API listener without a login secret."""
    if not (secret or "").strip():
        raise SystemExit(
            "VISIONAI_SECRET / [basic] visionai_secret is required; refusing to serve"
        )
