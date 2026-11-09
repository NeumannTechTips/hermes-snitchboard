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

    def test_defaults_are_not_shared_between_loads(self):
        first = config.load()
        first["ai_process_names"].append("x")
        self.assertEqual(config.load()["ai_process_names"], [])


if __name__ == "__main__":
    unittest.main()
