"""Canonical hashing and chain verification (PRD sections 7.3 and 10, SC6)."""

import copy
import json
import unittest

from snitchboard import chain, schema
from snitchboard.canonical import canonical_bytes, sha256_of

from tests.helpers import sealed_chain


class Canonical(unittest.TestCase):
    def test_key_order_does_not_change_the_digest(self):
        self.assertEqual(sha256_of({"b": 1, "a": [1, 2]}), sha256_of({"a": [1, 2], "b": 1}))

    def test_no_whitespace_and_utf8(self):
        self.assertEqual(canonical_bytes({"k": "é", "a": 1}), '{"a":1,"k":"é"}'.encode("utf-8"))

    def test_non_finite_numbers_are_refused(self):
        with self.assertRaises(ValueError):
            canonical_bytes({"x": float("nan")})


class Verify(unittest.TestCase):
    def setUp(self):
        self.records = sealed_chain(6)

    def assert_breaks_at(self, records, position, phrase):
        result = chain.verify(records)
        self.assertFalse(result["intact"])
        self.assertEqual(result["first_break"]["position"], position)
        self.assertEqual(result["first_break"]["run_id"], records[position]["run_id"])
        self.assertIn(phrase, result["first_break"]["note"])
        self.assertIn(records[position]["run_id"], result["summary"])

    def test_round_trip(self):
        result = chain.verify(self.records)
        self.assertTrue(result["intact"])
        self.assertEqual(result["checked"], 6)
        reloaded = [json.loads(json.dumps(r, indent=2)) for r in self.records]
        self.assertTrue(chain.verify(reloaded)["intact"])

    def test_single_edited_field_is_detected(self):
        records = copy.deepcopy(self.records)
        records[3]["totals"]["connections"] += 1
        self.assert_breaks_at(records, 3, "content does not match")

    def test_edit_with_recomputed_digest_breaks_the_next_link(self):
        records = copy.deepcopy(self.records)
        records[2]["note"] = "edited"
        records[2]["integrity"]["content_sha256"] = chain.content_digest(records[2])
        self.assert_breaks_at(records, 3, "prev_sha256 does not name the preceding run")

    def test_deleted_run_is_detected(self):
        records = self.records[:2] + self.records[3:]
        self.assert_breaks_at(records, 2, "prev_sha256")

    def test_deleted_first_run_is_detected(self):
        self.assert_breaks_at(self.records[1:], 0, "genesis")

    def test_two_reordered_runs_are_detected(self):
        records = list(self.records)
        records[2], records[3] = records[3], records[2]
        self.assert_breaks_at(records, 2, "reordered")

    def test_every_fault_is_listed_not_just_the_first(self):
        records = copy.deepcopy(self.records)
        records[1]["note"] = "x"
        records[4]["note"] = "y"
        broken = [l["position"] for l in chain.verify(records)["links"]
                  if l["status"] == chain.LINK_BROKEN]
        self.assertEqual(broken, [1, 4])

    def test_empty_chain_is_not_reported_intact(self):
        self.assertFalse(chain.verify([])["intact"])


class TrimmedLinks(unittest.TestCase):
    def setUp(self):
        self.records = sealed_chain(5)
        self.records[2] = chain.trim(self.records[2])

    def test_trimmed_record_mid_chain_is_a_sealed_link(self):
        result = chain.verify(self.records)
        self.assertTrue(result["intact"])
        self.assertEqual(result["sealed_links"], 1)
        statuses = [l["status"] for l in result["links"]]
        self.assertEqual(statuses, ["verified", "verified", "sealed", "verified", "verified"])
        self.assertIn("cannot be re-derived", result["links"][2]["note"])
        self.assertIn("cannot be re-derived", result["summary"])

    def test_verification_continues_past_a_trimmed_link(self):
        self.records[4]["note"] = "edited"
        result = chain.verify(self.records)
        self.assertEqual(result["first_break"]["position"], 4)
        self.assertEqual(result["links"][2]["status"], chain.LINK_SEALED)

    def test_trimmed_record_keeps_the_original_digest(self):
        original = sealed_chain(5)[2]
        trimmed = self.records[2]["integrity"]
        self.assertEqual(trimmed["sealed_sha256"], original["integrity"]["content_sha256"])
        self.assertNotEqual(trimmed["content_sha256"], trimmed["sealed_sha256"])

    def test_edit_after_trimming_is_detected(self):
        self.records[2]["destinations"].append("added.example.com")
        result = chain.verify(self.records)
        self.assertEqual(result["first_break"]["position"], 2)
        self.assertIn("after trimming", result["first_break"]["note"])

    def test_altered_sealed_digest_breaks_the_next_link(self):
        self.records[2]["integrity"]["sealed_sha256"] = "f" * 64
        self.assertEqual(chain.verify(self.records)["first_break"]["position"], 3)

    def test_trimmed_form_validates_and_keeps_destinations(self):
        trimmed = self.records[2]
        self.assertEqual(schema.validate(trimmed), [])
        self.assertTrue(trimmed["trimmed"])
        self.assertEqual(trimmed["destinations"], ["h2.example.com"])
        self.assertNotIn("rows", trimmed)

    def test_altered_full_record_is_not_sealed_into_a_trimmed_form(self):
        record = sealed_chain(1)[0]
        record["note"] = "edited"
        with self.assertRaises(ValueError):
            chain.trim(record)

    def test_trimming_twice_is_refused(self):
        with self.assertRaises(ValueError):
            chain.trim(self.records[2])


if __name__ == "__main__":
    unittest.main()
