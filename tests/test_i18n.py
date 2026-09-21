"""中英文词表 key 对齐（第一步覆盖的命名空间）。"""

from __future__ import annotations

import json
import unittest
from pathlib import Path

I18N_DIR = Path(__file__).resolve().parents[1] / "visionai" / "web" / "static" / "i18n"

PHASE1_NAMESPACES = (
    "nav",
    "login",
    "common",
    "overview",
    "access",
    "preview",
    "policy",
    "alerts",
    "modal",
    "msg",
    "faceLib",
    "plateLib",
    "onvif",
    "gb",
    "talkJs",
    "typesMap",
    "settings",
    "training",
)


def _flatten(obj, prefix=""):
    keys = set()
    if not isinstance(obj, dict):
        if prefix:
            keys.add(prefix)
        return keys
    if not obj:
        if prefix:
            keys.add(prefix)
        return keys
    for k, v in obj.items():
        path = f"{prefix}.{k}" if prefix else str(k)
        if isinstance(v, dict):
            keys |= _flatten(v, path)
        else:
            keys.add(path)
    return keys


def _load(name):
    return json.loads((I18N_DIR / name).read_text(encoding="utf-8"))


class I18nCatalogTests(unittest.TestCase):
    def test_zh_en_phase1_keys_match(self):
        zh = _load("zh.json")
        en = _load("en.json")
        for ns in PHASE1_NAMESPACES:
            self.assertIn(ns, zh)
            self.assertIn(ns, en)
            zh_keys = _flatten(zh[ns], ns)
            en_keys = _flatten(en[ns], ns)
            self.assertEqual(zh_keys, en_keys, f"key mismatch in {ns}")

    def test_full_catalog_keys_match(self):
        zh_keys = _flatten(_load("zh.json"))
        en_keys = _flatten(_load("en.json"))
        self.assertEqual(zh_keys, en_keys)

    def test_reserved_namespaces_present(self):
        zh = _load("zh.json")
        en = _load("en.json")
        self.assertIn("settings", zh)
        self.assertIn("training", zh)
        self.assertIn("settings", en)
        self.assertIn("training", en)


if __name__ == "__main__":
    unittest.main()
