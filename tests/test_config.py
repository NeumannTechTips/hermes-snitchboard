"""Settings defaults are neutral and validated (PRD section 7.8)."""

import unittest

from snitchboard import config


class Config(unittest.TestCase):
    def test_defaults_name_no_machine(self):
        cfg = config.load()
        for key in ("ai_process_names", "agent_accounts", "expected_services",
                    "provider_allowlist", "unattended_hours", "telemetry_destinations"):
            self.assertEqual(cfg[key], [], key)
        self.assertEqual(cfg["runs_dir"], "")

    def test_section_7_8_defaults(self):
        cfg = config.load()
        self.assertEqual(cfg["mode"], "auto")
        self.assertIs(cfg["redact_by_default"], True)
        self.assertEqual(cfg["retention_days"], 14)

    def test_thresholds_follow_section_7_4(self):
        cfg = config.load()
        self.assertEqual((cfg["beacon_min_contacts"], cfg["beacon_min_mean_s"],
                          cfg["beacon_max_mean_s"], cfg["beacon_max_jitter_pct"]),
                         (8, 20, 7200, 60.0))
        self.assertEqual((cfg["novelty_max_prior"], cfg["novelty_top"]), (48, 15))

    def test_unknown_key_is_refused(self):
        with self.assertRaisesRegex(ValueError, "unknown setting"):
            config.load({"beacon_min_contact": 5})

    def test_wrong_types_are_refused(self):
        for bad in ({"mode": "loud"}, {"unattended_hours": [24]},
                    {"redact_by_default": "yes"}, {"ai_process_names": "x"},
                    {"retention_days": -1}):
            with self.assertRaises(ValueError, msg=str(bad)):
                config.load(bad)

    def test_trimmed_max_bytes_defaults_to_8_kib(self):
        self.assertEqual(config.load()["trimmed_max_bytes"], 8192)
        self.assertIn("trimmed_max_bytes", config.PLUGIN_DEFAULTS)
        self.assertIn("telemetry_destinations", config.PLUGIN_DEFAULTS)
        self.assertNotIn("telemetry_destinations", config.ENGINE_DEFAULTS)

    def test_trimmed_max_bytes_is_bounded(self):
        for good in (1024, 8192, 200 * 1024):
            self.assertEqual(config.load({"trimmed_max_bytes": good})["trimmed_max_bytes"], good)
        for bad in (1023, 0, -1, 200 * 1024 + 1, True, 8192.0, "8192", None):
            with self.subTest(bad=bad), self.assertRaisesRegex(ValueError, "trimmed_max_bytes"):
                config.load({"trimmed_max_bytes": bad})

    def test_telemetry_destinations_must_be_strings(self):
        self.assertEqual(config.load({"telemetry_destinations": ["t.example.net"]})
                         ["telemetry_destinations"], ["t.example.net"])
        with self.assertRaisesRegex(ValueError, "telemetry_destinations"):
            config.load({"telemetry_destinations": [1]})

    def test_defaults_are_not_shared_between_loads(self):
        first = config.load()
        first["ai_process_names"].append("x")
        self.assertEqual(config.load()["ai_process_names"], [])


if __name__ == "__main__":
    unittest.main()
