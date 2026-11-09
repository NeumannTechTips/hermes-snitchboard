"""Manifest files agree with each other and with the engine defaults.

plugin.yaml is read with a narrow line parser because the test suite may not
import anything outside the standard library.
"""

import importlib.util
import json
import re
import unittest
from pathlib import Path

from snitchboard import config

REPO = Path(__file__).resolve().parent.parent


def schema_entries():
    text = (REPO / "plugin.yaml").read_text(encoding="utf-8")
    body = text.split("\nconfig_schema:\n", 1)[1]
    entries, current = {}, None
    for line in body.splitlines():
        key = re.match(r"^  (\w+):$", line)
        field = re.match(r"^    (type|default): (.*)$", line)
        if key:
            current = entries.setdefault(key.group(1), {})
        elif field and current is not None:
            current[field.group(1)] = field.group(2).strip()
    return text, entries


class PluginYaml(unittest.TestCase):
    def test_identity_and_floor(self):
        text, _ = schema_entries()
        self.assertIn("\nname: hermes-snitchboard\n", "\n" + text)
        self.assertIn('\nrequires_hermes: ">=0.23.0"\n', text)
        self.assertIn("\nversion: 0.1.0\n", text)

    def test_capability_lists_are_empty(self):
        text, _ = schema_entries()
        for key in ("provides_tools", "provides_hooks", "provides_middleware", "requires_env"):
            self.assertIn(f"\n{key}: []\n", text)

    def test_config_schema_matches_section_7_8_and_the_engine(self):
        _, entries = schema_entries()
        self.assertEqual(set(entries), set(config.PLUGIN_DEFAULTS))
        kinds = {str: "str", bool: "bool", int: "int", list: "list"}
        for key, default in config.PLUGIN_DEFAULTS.items():
            self.assertEqual(entries[key]["type"], kinds[type(default)], key)
            literal = json.dumps(default) if not isinstance(default, str) else (default or '""')
            self.assertEqual(entries[key]["default"], literal, key)


class DashboardManifest(unittest.TestCase):
    def test_fields(self):
        manifest = json.loads((REPO / "dashboard" / "manifest.json").read_text())
        self.assertEqual(manifest, {
            "name": "hermes-snitchboard", "label": "Hermes Snitchboard",
            "icon": "Shield", "tab": {"path": "/hermes-snitchboard"},
            "entry": "dist/index.js", "api": "plugin_api.py"})


class EntryPoint(unittest.TestCase):
    def test_register_registers_nothing(self):
        spec = importlib.util.spec_from_file_location("plugin_root", REPO / "__init__.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        class Recorder:
            def __getattr__(self, name):
                raise AssertionError(f"register() touched ctx.{name}")

        self.assertIsNone(module.register(Recorder()))


if __name__ == "__main__":
    unittest.main()
