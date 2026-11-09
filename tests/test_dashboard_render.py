"""Render the dashboard panels against the fixtures (HSB-PRD-001 section 10).

The work is done by dashboard_render_smoke.js under Node, with a minimal
stand-in for React, so no package is installed and nothing leaves the
machine. The test is skipped where Node is not available.
"""

import shutil
import subprocess
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
NODE = shutil.which("node")


@unittest.skipUnless(NODE, "node is not on PATH")
class RenderSmoke(unittest.TestCase):
    def test_every_panel_renders_against_the_fixtures(self):
        result = subprocess.run(
            [NODE, str(HERE / "dashboard_render_smoke.js")],
            capture_output=True, text=True, timeout=60, check=False)
        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)


if __name__ == "__main__":
    unittest.main()
