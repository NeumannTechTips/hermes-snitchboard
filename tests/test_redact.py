"""Masking by default (PRD FR9)."""

import copy
import json
import re
import unittest

from snitchboard import chain, schema
from snitchboard.redact import redact

from tests.helpers import build, event


class Redact(unittest.TestCase):
    def setUp(self):
        self.record = chain.seal(build([
            event(action="deny", host="api.example.com", ip="203.0.113.7",
                  process="/home/test-user/bin/tool --token abc"),
            event(5, host=None, ip="2001:db8::7"),
            event(9, host="svc.example.com", ip="198.51.100.4"),
        ]))
        self.record["note"] = "Interface 00-00-5E-00-53-01 saw 192.0.2.44 and api.example.com."
        self.masked = redact(self.record)
        self.text = json.dumps(self.masked)

    def test_no_address_survives(self):
        for literal in ("203.0.113.7", "2001:db8::7", "198.51.100.4", "192.0.2.44",
                        "192.0.2.1"):
            self.assertNotIn(literal, self.text)

    def test_no_host_name_survives(self):
        self.assertNotIn("example.com", self.text)

    def test_hardware_address_is_masked(self):
        self.assertNotIn("00-00-5E-00-53-01", self.text)
        self.assertIn("mac-1", self.masked["note"])

    def test_process_arguments_and_home_directory_are_masked(self):
        procs = {r["process"] for r in self.masked["rows"]}
        self.assertIn("/home/[user]/bin/tool [arguments masked]", procs)
        self.assertNotIn("abc", self.text)
        self.assertNotIn("test-user/bin", self.text)

    def test_same_value_gets_the_same_pseudonym(self):
        row = next(r for r in self.masked["rows"] if r["action"] == "deny")
        self.assertIn(row["dst"], self.masked["note"])
        self.assertTrue(re.fullmatch(r"host-\d+", row["dst"]))

    def test_deterministic_and_input_untouched(self):
        before = copy.deepcopy(self.record)
        self.assertEqual(redact(self.record), self.masked)
        self.assertEqual(self.record, before)

    def test_digests_and_timestamps_are_kept(self):
        self.assertEqual(self.masked["integrity"], self.record["integrity"])
        self.assertEqual(self.masked["started_at"], self.record["started_at"])

    def test_masked_record_keeps_its_shape(self):
        self.assertEqual(schema.validate(self.masked), [])


if __name__ == "__main__":
    unittest.main()
