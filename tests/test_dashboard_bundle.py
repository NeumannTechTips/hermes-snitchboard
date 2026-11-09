"""Static checks on the dashboard bundle (HSB-PRD-001 sections 6.2, 6.3 and 7.10).

The bundle is hand-written and shipped as committed, so these checks read it
as text. They hold the front-end conventions in place: React elements only,
nothing loaded from another host, the plugin's full name wherever a reader
sees it, and the panel order set out in section 7.9.
"""

import re
import unittest
from pathlib import Path

from snitchboard import config, schema

REPO = Path(__file__).resolve().parent.parent
BUNDLE = REPO / "dashboard" / "dist" / "index.js"


def source():
    return BUNDLE.read_text(encoding="utf-8")


class ForbiddenSinks(unittest.TestCase):
    def test_no_raw_markup_sink(self):
        text = source()
        for sink in ("innerHTML", "outerHTML", "insertAdjacentHTML",
                     "dangerouslySetInnerHTML", "document.write", "eval(",
                     "new Function", "createContextualFragment", "DOMParser"):
            with self.subTest(sink=sink):
                self.assertNotIn(sink, text)

    def test_no_markup_from_template_strings(self):
        self.assertNotIn("`", source())

    def test_nothing_is_loaded_from_another_host(self):
        text = source()
        for marker in ("http://", "https://", "@import", "<link", "<script"):
            with self.subTest(marker=marker):
                self.assertNotIn(marker, text)
        # The only url() allowed is a reference to a pattern in the same SVG.
        for match in re.finditer(r"url\(", text):
            self.assertEqual(text[match.end()], "#", text[match.start():match.end() + 20])

    def test_no_em_dash(self):
        self.assertNotIn("\u2014", source())


class Naming(unittest.TestCase):
    ALLOWED = ("Hermes Snitchboard", "hermes-snitchboard", "data-snitchboard",
               "HermesSnitchboardTab", "__HERMES_SNITCHBOARD_TEST__")

    def test_the_short_name_never_reaches_a_reader(self):
        text = source()
        spans = [(m.start(), m.end()) for form in self.ALLOWED
                 for m in re.finditer(re.escape(form), text)]
        for match in re.finditer(r"snitchboard", text, re.IGNORECASE):
            context = text[max(0, match.start() - 20):match.end() + 10]
            with self.subTest(context=context):
                self.assertTrue(any(start <= match.start() and match.end() <= end
                                    for start, end in spans), context)

    def test_header_title_keeps_its_case(self):
        text = source()
        self.assertIn('"Hermes Snitchboard"', text)
        self.assertIn('textTransform: "none"', text)


class Panels(unittest.TestCase):
    def test_panel_order_follows_section_7_9(self):
        text = source()
        block = re.search(r"var panels = \[(.*?)\];", text, re.S)
        self.assertIsNotNone(block)
        names = re.findall(r'\[\s*"([^"]+)"\s*,\s*\w+\s*\]', block.group(1))
        expected = ["Summary", "Coverage", "Findings", "Beacons", "Novel destinations",
                    "Agents", "Connections", "Events", "Aggregates", "Volume",
                    "Daemon state", "Rules in force", "Sockets", "Integrity"]
        positions = [names.index(name) for name in expected]
        self.assertEqual(positions, sorted(positions), names)

    def test_trimmed_gap_says_not_held(self):
        self.assertIn('"Not held in this record."', source())


class Caps(unittest.TestCase):
    def test_fallback_caps_match_the_schema(self):
        block = re.search(r"var CAPS_FALLBACK = \{(.*?)\};", source(), re.S)
        self.assertIsNotNone(block)
        caps = {k: int(v) for k, v in re.findall(r"(\w+): (\d+)", block.group(1))}
        for key in ("rows", "volume_rows", "hosts", "addrs", "novel", "beacons"):
            with self.subTest(key=key):
                self.assertEqual(caps[key], schema.CAPS[key])
        self.assertEqual(caps["aggregates"], config.DEFAULTS["aggregate_cap"])


if __name__ == "__main__":
    unittest.main()
