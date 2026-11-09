"""Severity rules (PRD section 7.6) and the ATT&CK mapping (section 7.5)."""

import unittest

from snitchboard import attack, severity
from snitchboard.schema import HIGH, LOW, MEDIUM

from tests.helpers import AI, APP, at_offsets, build, cfg, event, prior_run

AI_CFG = dict(ai_process_names=["test-agent"])


def findings(record):
    return {(d["severity"], d["attack"]["technique_id"], d["title"]) for d in record["detections"]}


def titles_at(record, level):
    return [d["title"] for d in record["detections"] if d["severity"] == level]


class RuleTable(unittest.TestCase):
    def test_table_matches_section_7_6(self):
        expected = {
            "unattributed": HIGH, "ai_nonstandard_port": HIGH, "denied": HIGH,
            "ai_novel_unattended": HIGH, "agent_off_allowlist": HIGH,
            "outbound_transfer_unidentified": HIGH,
            "new_destination_known_process": MEDIUM, "ai_telemetry": MEDIUM,
            "beacon_high_confidence": MEDIUM,
            "beacon_candidate": LOW, "dns_volume": LOW, "many_destinations": LOW,
        }
        self.assertEqual({k: v[0] for k, v in severity.RULES.items()}, expected)


class HighRules(unittest.TestCase):
    def test_unattributed_connection(self):
        record = build([event(process=None, pid=None, uid=None, user=None)])
        self.assertEqual(titles_at(record, HIGH),
                         ["Connection with no attributable process to svc.example.com:443"])
        self.assertEqual(record["totals"]["unattributed"], 1)

    def test_ai_process_on_a_non_standard_port(self):
        record = build([event(process=AI, port=7000)], settings=cfg(**AI_CFG))
        self.assertIn((HIGH, "T1571"), {(s, t) for s, t, _ in findings(record)})

    def test_ai_process_on_a_standard_port_is_not_flagged(self):
        record = build([event(process=AI, port=443)], settings=cfg(**AI_CFG))
        self.assertEqual(record["detections"], [])

    def test_denied_connection(self):
        record = build([event(action="deny")])
        self.assertEqual(titles_at(record, HIGH),
                         [f"Denied connection from {APP} to svc.example.com:443"])

    def test_new_destination_for_ai_in_unattended_hours(self):
        settings = cfg(unattended_hours=[10], **AI_CFG)
        record = build([event(process=AI)], prior=[prior_run({"old.example.com"})],
                       settings=settings)
        self.assertEqual(titles_at(record, HIGH),
                         ["AI tooling reached new destination svc.example.com during "
                          "unattended hours"])
        self.assertEqual(titles_at(record, MEDIUM), [], "the medium rule is subsumed")

    def test_same_outside_unattended_hours_is_medium(self):
        settings = cfg(unattended_hours=[3], **AI_CFG)
        record = build([event(process=AI)], prior=[prior_run({"old.example.com"})],
                       settings=settings)
        self.assertEqual(titles_at(record, HIGH), [])
        self.assertEqual(len(titles_at(record, MEDIUM)), 1)

    def test_agent_account_off_allowlist_is_high(self):
        settings = cfg(agent_accounts=["agent-acct"], provider_allowlist=["*.example.net"])
        record = build([event(user="agent-acct")], settings=settings)
        self.assertIn((HIGH, "T1078"), {(s, t) for s, t, _ in findings(record)})

    def test_agent_account_on_allowlist_is_not_flagged(self):
        settings = cfg(agent_accounts=["agent-acct"], provider_allowlist=["*.example.com"])
        record = build([event(user="agent-acct")], settings=settings)
        self.assertEqual(record["detections"], [])

    def test_account_matched_by_uid(self):
        settings = cfg(agent_accounts=["1600"], provider_allowlist=["203.0.113.0/24"])
        record = build([event(uid=1600, host=None, ip="198.51.100.9")], settings=settings)
        self.assertEqual(len(titles_at(record, HIGH)), 1)

    def test_without_an_allowlist_every_agent_connection_is_flagged(self):
        settings = cfg(agent_accounts=["agent-acct"])
        record = build([event(user="agent-acct")], settings=settings)
        self.assertEqual(len(titles_at(record, HIGH)), 1)
        self.assertIn("no provider allowlist", record["agents"][0]["verdict"])

    def test_outbound_transfer_above_1_mb_to_unidentified_destination(self):
        record = build([event(host=None, ip="198.51.100.9", sent=1_000_001, recv=10)])
        self.assertIn((HIGH, "T1567"), {(s, t) for s, t, _ in findings(record)})

    def test_transfer_of_exactly_1_mb_is_not_above(self):
        record = build([event(host=None, ip="198.51.100.9", sent=1_000_000, recv=10)])
        self.assertEqual(titles_at(record, HIGH), [])

    def test_transfer_to_a_named_destination_is_not_this_rule(self):
        record = build([event(sent=5_000_000, recv=10)])
        self.assertEqual(titles_at(record, HIGH), [])

    def test_balanced_transfer_is_not_outbound_dominant(self):
        record = build([event(host=None, ip="198.51.100.9", sent=2_000_000, recv=1_500_000)])
        self.assertEqual(titles_at(record, HIGH), [])


class MediumAndLowRules(unittest.TestCase):
    def test_new_destination_for_a_known_process(self):
        record = build([event()], prior=[prior_run({"old.example.com"})])
        self.assertEqual(titles_at(record, MEDIUM), [f"New destination svc.example.com for {APP}"])

    def test_nothing_is_new_without_a_baseline(self):
        self.assertEqual(build([event()])["detections"], [])

    def test_telemetry_reached_by_ai(self):
        settings = cfg(telemetry_destinations=["*.example.com"], **AI_CFG)
        record = build([event(process=AI)], settings=settings)
        self.assertIn((MEDIUM, "T1567"), {(s, t) for s, t, _ in findings(record)})

    def test_high_confidence_beacon_is_medium(self):
        record = build(at_offsets([i * 60 for i in range(8)]))
        self.assertEqual([(s, t) for s, t, _ in findings(record)], [(MEDIUM, "T1071")])

    def test_lower_confidence_beacon_is_low(self):
        offsets = [0, 75, 200, 275, 400, 475, 600, 675]
        record = build(at_offsets(offsets))
        self.assertEqual([(s, t) for s, t, _ in findings(record)], [(LOW, "T1071")])

    def test_dns_volume(self):
        settings = cfg(dns_volume_threshold=5)
        record = build(at_offsets(range(6), port=53, proto="udp", host=None,
                                  ip="192.0.2.53"), settings=settings)
        self.assertIn((LOW, "T1071.004"), {(s, t) for s, t, _ in findings(record)})

    def test_many_destinations(self):
        settings = cfg(many_destinations_threshold=3)
        record = build([event(i, host=f"m{i}.example.com") for i in range(4)], settings=settings)
        self.assertIn((LOW, "T1568"), {(s, t) for s, t, _ in findings(record)})


class AttackMapping(unittest.TestCase):
    def test_permitted_set_is_exactly_section_7_5(self):
        self.assertEqual(attack.PERMITTED_TECHNIQUE_IDS, {
            "T1071", "T1071.001", "T1071.004", "T1568", "T1571", "T1048",
            "T1567", "T1078"})
        self.assertEqual(attack.PERMITTED_TACTIC_IDS, {"TA0011", "TA0010"})

    def test_non_standard_port_readings(self):
        self.assertEqual(attack.nonstandard_port_technique(False), "T1571")
        self.assertEqual(attack.nonstandard_port_technique(True), "T1048")

    def test_ai_non_standard_port_with_outbound_bytes_is_t1048(self):
        record = build([event(process=AI, port=7000, sent=90_000, recv=1_000)],
                       settings=cfg(**AI_CFG))
        self.assertIn((HIGH, "T1048"), {(s, t) for s, t, _ in findings(record)})

    def test_channel_technique_by_port(self):
        c = cfg()
        self.assertEqual(attack.channel_technique(53, c), "T1071.004")
        self.assertEqual(attack.channel_technique(443, c), "T1071.001")
        self.assertEqual(attack.channel_technique(123, c), "T1071")
        self.assertEqual(attack.channel_technique(9999, c), "T1571")

    def test_engine_emits_nothing_outside_the_permitted_set(self):
        settings = cfg(ai_process_names=["test-agent"], agent_accounts=["agent-acct"],
                       telemetry_destinations=["tel.example.net"], unattended_hours=[10],
                       dns_volume_threshold=1, many_destinations_threshold=1)
        events = (
            [event(process=None, pid=None, port=8080), event(action="deny", port=53),
             event(process=AI, port=7000, sent=3_000_000, recv=1, host=None,
                   ip="198.51.100.9"),
             event(process=AI, host="tel.example.net", user="agent-acct"),
             event(port=53, proto="udp", host=None, ip="192.0.2.53"),
             event(port=53, proto="udp", host=None, ip="192.0.2.54")]
            + at_offsets([i * 60 for i in range(10)], host="b.example.net"))
        record = build(events, prior=[prior_run({"old.example.com"})], settings=settings)
        emitted = {d["attack"]["technique_id"] for d in record["detections"]}
        self.assertTrue(emitted <= attack.PERMITTED_TECHNIQUE_IDS)
        self.assertGreaterEqual(len(emitted), 6)
        for d in record["detections"]:
            self.assertTrue(attack.is_permitted(d["attack"]), d["attack"])


if __name__ == "__main__":
    unittest.main()
