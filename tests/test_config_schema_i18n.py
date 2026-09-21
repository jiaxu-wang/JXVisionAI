"""系统设置 schema 双语字段与 [ui] language 映射。"""

from __future__ import annotations

import unittest

from visionai.config.config_schema import CONFIG_UNITS
from visionai.config.ini_sections import canonicalize, write_location


class ConfigSchemaI18nTests(unittest.TestCase):
    def test_every_unit_and_field_has_en(self):
        for unit in CONFIG_UNITS:
            self.assertTrue(unit.title_en, unit.id)
            self.assertTrue(unit.description_en, unit.id)
            for field in unit.fields:
                self.assertTrue(field.label_en, field.key)
                if field.comment:
                    self.assertTrue(field.comment_en, field.key)

    def test_ui_language_writes_ui_section(self):
        self.assertEqual(write_location("ui_language"), ("ui", "language"))
        self.assertEqual(canonicalize("ui", "language"), "ui_language")

    def test_label_zh_unchanged_for_compat(self):
        security = next(u for u in CONFIG_UNITS if u.id == "security")
        tz = next(f for f in security.fields if f.key == "timezone")
        self.assertEqual(tz.label, "应用时区")
        self.assertEqual(tz.label_en, "App timezone")

    def test_platform_embed_url_in_integration(self):
        unit = next(u for u in CONFIG_UNITS if u.id == "integration")
        keys = [f.key for f in unit.fields]
        self.assertIn("platform_embed_url", keys)
        self.assertEqual(write_location("platform_embed_url"), ("integration", "platform_embed_url"))


if __name__ == "__main__":
    unittest.main()
