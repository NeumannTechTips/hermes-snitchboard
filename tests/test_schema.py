"""Strict schema validation (PRD sections 5.1, 7.3 and 10, SC7)."""

import copy
import unittest

from snitchboard import chain, schema

from tests.helpers import build, event, sealed_chain


def full_record_with_detection():
    return chain.seal(build([event(action="deny")]))


class Detections(unittest.TestCase):
    def test_missing_mandatory_field_is_rejected_with_a_useful_message(self):
        for field in schema.DETECTION_FIELDS:
            record = full_record_with_detection()
            del record["detections"][0][field]
            problems = schema.validate(record)
            self.assertIn(f"record.detections[0]: missing mandatory field '{field}'",
                          problems)

    def test_partial_form_from_the_reference_data_is_rejected(self):
        record = full_record_with_detection()
        det = record["detections"][0]
        record["detections"][0] = {"title": det["title"], "severity": det["severity"]}
        self.assertGreaterEqual(len(schema.validate(record)), 5)

    def test_empty_evidence_is_rejected(self):
        record = full_record_with_detection()
        record["detections"][0]["evidence"] = []
        self.assertTrue(any("at least one observed record" in p for p in schema.validate(record)))

    def test_unpermitted_technique_is_rejected(self):
        record = full_record_with_detection()
        record["detections"][0]["attack"]["technique_id"] = "T1059"
        self.assertTrue(any("not in the permitted table" in p for p in schema.validate(record)))

    def test_bad_severity_is_rejected(self):
        record = full_record_with_detection()
        record["detections"][0]["severity"] = "critical"
        self.assertTrue(any("severity" in p for p in schema.validate(record)))


class Shape(unittest.TestCase):
    def setUp(self):
        self.record = full_record_with_detection()

    def assert_problem(self, record, phrase):
        problems = schema.validate(record)
        self.assertTrue(any(phrase in p for p in problems), problems)

    def test_built_record_is_valid(self):
        self.assertEqual(schema.validate(self.record), [])

    def test_unknown_field_is_rejected(self):
        self.record["extra"] = 1
        self.assert_problem(self.record, "unexpected field 'extra'")

    def test_missing_top_level_field_is_rejected(self):
        del self.record["coverage"]
        self.assert_problem(self.record, "missing mandatory field 'coverage'")

    def test_unknown_form_is_rejected(self):
        del self.record["trimmed"]
        self.assert_problem(self.record, "form is unknown")

    def test_naive_timestamp_is_rejected(self):
        self.record["window_start"] = "2026-11-02T10:00:00"
        self.assert_problem(self.record, "offset")

    def test_unknown_status_is_rejected(self):
        self.record["status"] = "collection_unavailable"
        self.assert_problem(self.record, "status")
        self.assertEqual(schema.normalise_status("collection_unavailable"), "no_data")

    def test_run_id_must_match_its_pattern_and_start_time(self):
        record = copy.deepcopy(self.record)
        record["run_id"] = "../../etc/passwd"
        self.assert_problem(record, "pattern")
        record["run_id"] = "run-20200101T000000Z"
        self.assert_problem(record, "does not correspond")

    def test_coverage_needs_24_slots(self):
        self.record["coverage"]["slots"].pop()
        self.assert_problem(self.record, "exactly 24 slots")

    def test_rows_over_cap_are_rejected(self):
        self.record["rows"] = self.record["rows"] * 121
        self.assert_problem(self.record, "above the cap of 120")

    def test_volume_rows_without_measurement_are_rejected(self):
        self.record["volume"]["rows"] = [{
            "process": "p", "destination": "d.example.com", "sent_bytes": 1,
            "recv_bytes": 1, "flows": 1, "assessment": "x"}]
        self.assert_problem(self.record, "must be empty when volume is unavailable")

    def test_destinations_must_be_sorted(self):
        self.record["destinations"] = ["b.example.com", "a.example.com"]
        self.assert_problem(self.record, "sorted")

    def test_boolean_is_not_an_integer(self):
        self.record["totals"]["connections"] = True
        self.assert_problem(self.record, "totals.connections")

    def test_full_record_size_cap(self):
        self.record["note"] = "x" * (schema.CAPS["full_bytes"] + 1)
        self.assert_problem(self.record, "above the cap of 204800")


class TrimmedShape(unittest.TestCase):
    def setUp(self):
        self.record = chain.trim(sealed_chain(1)[0])

    def test_trimmed_record_must_keep_destinations(self):
        del self.record["destinations"]
        self.assertIn("record (trimmed form): missing mandatory field 'destinations'",
                      schema.validate(self.record))

    def test_trimmed_record_needs_its_sealed_digest(self):
        del self.record["integrity"]["sealed_sha256"]
        self.assertTrue(any("sealed_sha256" in p for p in schema.validate(self.record)))

    def test_trimmed_record_may_not_carry_detail(self):
        self.record["rows"] = []
        self.assertTrue(any("unexpected field 'rows'" in p for p in schema.validate(self.record)))

    def test_trimmed_size_cap(self):
        self.record["note"] = "x" * schema.CAPS["trimmed_bytes"]
        self.assertTrue(any("above the cap of 8192" in p for p in schema.validate(self.record)))

    def test_trimming_drops_detections_before_destinations(self):
        record = chain.seal(build([event(i, action="deny", host=f"d{i}.example.com")
                                   for i in range(40)]))
        trimmed = chain.trim(record)
        self.assertEqual(schema.validate(trimmed), [])
        self.assertEqual(len(trimmed["destinations"]), 40)
        self.assertLess(len(trimmed["detections"]), len(record["detections"]))
        self.assertIn("omitted at trimming", trimmed["note"])

    def test_destinations_that_cannot_fit_raise(self):
        record = chain.seal(build([event(i, host=f"{'d' * 40}{i}.example.com")
                                   for i in range(300)]))
        with self.assertRaises(chain.TrimError):
            chain.trim(record)


if __name__ == "__main__":
    unittest.main()
