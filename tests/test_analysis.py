"""Analysis rules of PRD section 7.4, with the boundary values of section 10."""

import unittest
from datetime import timedelta

from snitchboard import analysis
from snitchboard.schema import HIGH, LOW, MEDIUM

from tests.helpers import (
    AI, APP, T0, at_offsets, build, cfg, cumulative, event, prior_run,
)


def beacons_for(offsets, settings=None, **kw):
    events = [analysis.normalise_event(e) for e in at_offsets(offsets, **kw)]
    return analysis.beaconing(events, settings or cfg())


class BeaconContacts(unittest.TestCase):
    def test_seven_contacts_are_not_enough(self):
        self.assertEqual(beacons_for([i * 60 for i in range(7)]), [])

    def test_eight_contacts_are_reported(self):
        found = beacons_for([i * 60 for i in range(8)])
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]["count"], 8)

    def test_port_53_is_excluded(self):
        self.assertEqual(beacons_for([i * 60 for i in range(20)], port=53), [])


class BeaconMeanInterval(unittest.TestCase):
    def test_exactly_twenty_seconds_is_reported(self):
        found = beacons_for([i * 20 for i in range(8)])
        self.assertEqual(found[0]["mean_interval"], 20)

    def test_just_below_twenty_seconds_is_not(self):
        self.assertEqual(beacons_for([i * 19 for i in range(8)]), [])

    def test_exactly_two_hours_is_reported(self):
        found = beacons_for([i * 7200 for i in range(8)])
        self.assertEqual(found[0]["mean_interval"], 7200)

    def test_just_above_two_hours_is_not(self):
        self.assertEqual(beacons_for([i * 7201 for i in range(8)]), [])


class BeaconJitter(unittest.TestCase):
    def test_confidence_thresholds(self):
        c = cfg()
        self.assertEqual(analysis.jitter_confidence(9.9, c), HIGH)
        self.assertEqual(analysis.jitter_confidence(10.0, c), MEDIUM)
        self.assertEqual(analysis.jitter_confidence(24.9, c), MEDIUM)
        self.assertEqual(analysis.jitter_confidence(25.0, c), LOW)

    def _alternating(self, spread):
        # Gaps of 100 - spread and 100 + spread give a mean of 100 s and a
        # population standard deviation of exactly `spread`.
        offsets = cumulative([100 - spread, 100 + spread] * 4)
        return beacons_for(offsets)[0]

    def test_end_to_end_9_9_per_cent_is_high(self):
        b = self._alternating(9.9)
        self.assertEqual((b["jitter_pct"], b["confidence"]), (9.9, HIGH))

    def test_end_to_end_10_0_per_cent_is_medium(self):
        b = self._alternating(10)
        self.assertEqual((b["jitter_pct"], b["confidence"]), (10.0, MEDIUM))

    def test_end_to_end_24_9_per_cent_is_medium(self):
        b = self._alternating(24.9)
        self.assertEqual((b["jitter_pct"], b["confidence"]), (24.9, MEDIUM))

    def test_end_to_end_25_0_per_cent_is_low(self):
        b = self._alternating(25)
        self.assertEqual((b["jitter_pct"], b["confidence"]), (25.0, LOW))

    def test_jitter_at_sixty_per_cent_is_not_reported(self):
        self.assertEqual(beacons_for(cumulative([40, 160] * 4)), [])

    def test_jitter_just_below_sixty_is_reported(self):
        found = beacons_for(cumulative([41, 159] * 4))
        self.assertEqual(found[0]["jitter_pct"], 59.0)

    def test_ordered_by_jitter(self):
        events = (at_offsets(cumulative([80, 120] * 4), host="b.example.com")
                  + at_offsets(cumulative([100] * 8), host="a.example.com")
                  + at_offsets(cumulative([95, 105] * 4), host="c.example.com"))
        found = analysis.beaconing([analysis.normalise_event(e) for e in events], cfg())
        self.assertEqual([b["destination"] for b in found],
                         ["a.example.com", "c.example.com", "b.example.com"])

    def test_capped_at_sixteen(self):
        events = []
        for i in range(20):
            events += at_offsets([j * 60 for j in range(8)], host=f"n{i}.example.com")
        found = analysis.beaconing([analysis.normalise_event(e) for e in events], cfg())
        self.assertEqual(len(found), 16)


class BeaconAssessment(unittest.TestCase):
    def test_every_assessment_names_both_readings(self):
        for settings in (cfg(), cfg(expected_services=["svc.example.com"])):
            b = beacons_for([i * 60 for i in range(8)], settings)[0]
            self.assertIn("Benign reading:", b["assessment"])
            self.assertIn("Malicious reading:", b["assessment"])

    def test_expected_service_is_labelled_not_flagged(self):
        settings = cfg(expected_services=["test-app"])
        record = build(at_offsets([i * 60 for i in range(8)]), settings=settings)
        self.assertTrue(record["beacons"][0]["assessment"].startswith("Expected service"))
        self.assertEqual(record["totals"]["beacon_candidates"], 0)
        self.assertFalse([d for d in record["detections"] if "Regular-interval" in d["title"]])

    def test_unexpected_beacon_is_flagged(self):
        record = build(at_offsets([i * 60 for i in range(8)]))
        self.assertEqual(record["totals"]["beacon_candidates"], 1)
        self.assertTrue([d for d in record["detections"] if "Regular-interval" in d["title"]])


class Novelty(unittest.TestCase):
    def _novel(self, events, baseline_runs):
        evs = [analysis.normalise_event(e) for e in events]
        baseline = analysis.baseline_from(baseline_runs, cfg())
        return {n["destination"]: n for n in analysis.novelty(evs, baseline, cfg())}

    def test_never_seen_scores_100(self):
        prior = [prior_run({"other.example.com"}, hour=-h) for h in range(1, 5)]
        n = self._novel([event()], prior)["svc.example.com"]
        self.assertEqual((n["rarity"], n["prior_runs_seen"]), (100, 0))

    def test_seen_in_every_prior_run_scores_0(self):
        prior = [prior_run({"svc.example.com"}, hour=-h) for h in range(1, 5)]
        n = self._novel([event()], prior)["svc.example.com"]
        self.assertEqual((n["rarity"], n["prior_runs_seen"]), (0, 4))

    def test_rarity_scales_between(self):
        prior = [prior_run({"svc.example.com"} if h == 1 else set(), hour=-h)
                 for h in range(1, 5)]
        self.assertEqual(self._novel([event()], prior)["svc.example.com"]["rarity"], 75)

    def test_no_prior_runs_scores_100_and_says_why(self):
        n = self._novel([event()], [])["svc.example.com"]
        self.assertEqual(n["rarity"], 100)
        self.assertIn("by definition", n["baseline_note"])

    def test_no_data_runs_are_left_out_of_the_baseline(self):
        prior = [prior_run({"svc.example.com"}, hour=-1),
                 prior_run(set(), status="no_data", hour=-2)]
        n = self._novel([event()], prior)["svc.example.com"]
        self.assertEqual((n["rarity"], n["prior_runs_seen"]), (0, 1))

    def test_only_the_48_most_recent_prior_runs_count(self):
        prior = [prior_run({"svc.example.com"} if h == 49 else set(), hour=-h)
                 for h in range(1, 50)]
        n = self._novel([event()], prior)["svc.example.com"]
        self.assertEqual((n["rarity"], n["prior_runs_seen"]), (100, 0))
        self.assertIn("of 48 prior", n["baseline_note"])

    def test_top_fifteen(self):
        events = [event(i, host=f"d{i}.example.com") for i in range(20)]
        self.assertEqual(len(self._novel(events, [])), 15)


class Coverage(unittest.TestCase):
    def _slots(self, runs, end=None):
        end = end or (T0 + timedelta(hours=24)).isoformat()
        return [s["covered"] for s in analysis.coverage(runs, end, cfg())["slots"]]

    def _hourly(self, skip=(), status=None):
        return [prior_run(set(), status=(status or {}).get(h, "ok"), hour=h)
                for h in range(24) if h not in skip]

    def test_twenty_four_hourly_ok_runs_cover_every_slot(self):
        self.assertEqual(self._slots(self._hourly()), [True] * 24)

    def test_hour_with_no_run_is_not_covered(self):
        slots = self._slots(self._hourly(skip={5}))
        self.assertFalse(slots[5])
        self.assertEqual(slots.count(True), 23)

    def test_runs_that_are_not_ok_do_not_cover(self):
        slots = self._slots(self._hourly(status={3: "no_data", 7: "partial"}))
        self.assertFalse(slots[3])
        self.assertFalse(slots[7])

    def test_no_runs_means_nothing_covered(self):
        self.assertEqual(self._slots([]), [False] * 24)

    def test_half_an_hour_is_not_covered(self):
        run = {"window_start": T0.isoformat(),
               "window_end": (T0 + timedelta(minutes=30)).isoformat(), "status": "ok"}
        self.assertFalse(self._slots([run])[0])

    def test_small_timer_drift_is_tolerated(self):
        run = {"window_start": (T0 + timedelta(seconds=60)).isoformat(),
               "window_end": (T0 + timedelta(hours=1)).isoformat(), "status": "ok"}
        self.assertTrue(self._slots([run])[0])

    def test_offset_is_kept(self):
        cov = analysis.coverage([], (T0 + timedelta(hours=24)).isoformat(), cfg())
        self.assertTrue(cov["from"].endswith("+01:00"))
        self.assertTrue(cov["to"].endswith("+01:00"))
        self.assertEqual(cov["slots"][0]["label"], "10:00")


class Volume(unittest.TestCase):
    def _volume(self, events):
        return analysis.volume([analysis.normalise_event(e) for e in events], cfg())[0]

    def test_unavailable_without_measured_bytes(self):
        vol = self._volume([event()])
        self.assertFalse(vol["available"])
        self.assertEqual(vol["rows"], [])
        self.assertIn("unavailable", vol["note"])

    def test_ranked_by_total_bytes(self):
        vol = self._volume([event(sent=10, recv=10, host="a.example.com"),
                            event(sent=500, recv=500, host="b.example.com")])
        self.assertEqual([r["destination"] for r in vol["rows"]],
                         ["b.example.com", "a.example.com"])

    def test_unmeasured_connections_are_not_estimated(self):
        vol = self._volume([event(sent=100, recv=50), event(host="other.example.com")])
        self.assertEqual([r["destination"] for r in vol["rows"]], ["svc.example.com"])
        self.assertIn("1 of 2", vol["note"])

    def test_unpaired_flow_is_labelled(self):
        vol = self._volume([event(sent=100, recv=50, paired=False)])
        self.assertIn("could not be paired", vol["rows"][0]["assessment"])

    def test_capped_at_45_rows(self):
        vol = self._volume([event(sent=i + 1, recv=1, host=f"v{i}.example.com")
                            for i in range(60)])
        self.assertEqual(len(vol["rows"]), 45)

    def test_assessment_follows_the_ratio(self):
        out = self._volume([event(sent=900, recv=100)])["rows"][0]["assessment"]
        inbound = self._volume([event(sent=100, recv=900)])["rows"][0]["assessment"]
        self.assertTrue(out.startswith("Outbound-dominant"))
        self.assertTrue(inbound.startswith("Inbound-dominant"))


class Agents(unittest.TestCase):
    def test_one_row_per_configured_process_and_account(self):
        settings = cfg(ai_process_names=["test-agent", "idle-agent"],
                       agent_accounts=["agent-acct"])
        record = build([event(process=AI, user="agent-acct", uid=1600)],
                       settings=settings)
        rows = record["agents"]
        self.assertEqual(len(rows), 3)
        self.assertEqual(rows[0]["connections"], 1)
        self.assertEqual(rows[1]["connections"], 0)
        self.assertIsNone(rows[1]["pid"])
        self.assertEqual(rows[2]["user"], "agent-acct")
        self.assertEqual(record["totals"]["agents_active"], 2)

    def test_root_is_called_out(self):
        settings = cfg(ai_process_names=["test-agent"])
        record = build([event(process=AI, uid=0, user="root")], settings=settings)
        self.assertIn("root", record["agents"][0]["privilege_note"])


class RecordShape(unittest.TestCase):
    def test_rows_capped_at_120_and_ranked_by_severity(self):
        events = [event(i) for i in range(150)] + [event(5, action="deny")]
        record = build(events)
        self.assertEqual(len(record["rows"]), 120)
        self.assertEqual(record["rows"][0]["severity"], HIGH)

    def test_no_data_run_carries_no_events(self):
        record = build([], status="no_data")
        self.assertEqual(record["totals"]["connections"], 0)
        self.assertFalse(record["volume"]["available"])
        with self.assertRaises(ValueError):
            build([event()], status="no_data")

    def test_naive_timestamp_is_refused(self):
        bad = event()
        bad["ts"] = "2026-11-02T10:00:00"
        with self.assertRaises(ValueError):
            build([bad])

    def test_local_timestamps_are_never_relabelled(self):
        record = build([event()])
        self.assertTrue(record["rows"][0]["ts"].endswith("+01:00"))
        self.assertTrue(record["window_start"].endswith("+01:00"))

    def test_aggregate_caps(self):
        events = [event(i, host=f"x{i}.example.com", ip=f"203.0.113.{i}") for i in range(30)]
        agg = build(events)["aggregates"]
        self.assertEqual(len(agg["hosts"]), 20)
        self.assertEqual(len(agg["addrs"]), 15)

    def test_sockets_are_ranked_before_the_cap(self):
        # The busiest sockets survive the cap whatever order the caller used.
        sockets = [{"what": f"tcp 192.0.2.1:{40000 + i} -> 203.0.113.5:443",
                    "hits": 1} for i in range(30)]
        sockets.append({"what": "udp 192.0.2.1:41000 -> 192.0.2.53:53", "hits": 9})
        sockets.append({"what": "tcp 192.0.2.1:39999 -> 203.0.113.9:443", "hits": 9})
        agg = build([event()], daemon={"sockets": sockets})["aggregates"]
        self.assertEqual(len(agg["sockets"]), 20)
        self.assertEqual([s["hits"] for s in agg["sockets"][:2]], [9, 9])
        self.assertEqual(agg["sockets"][0]["what"],
                         "tcp 192.0.2.1:39999 -> 203.0.113.9:443")
        reversed_agg = build([event()], daemon={"sockets": sockets[::-1]})["aggregates"]
        self.assertEqual(agg["sockets"], reversed_agg["sockets"])

    def test_node_counters_are_never_counted_from_the_window(self):
        # node.cons and cons_dropped are the daemon's lifetime counters only.
        events = [event(i) for i in range(5)] + [event(9, action="deny")]
        agg = build(events)["aggregates"]
        self.assertEqual((agg["node"]["cons"], agg["node"]["cons_dropped"]), (0, 0))
        self.assertEqual(agg["node"]["status"], "unknown")
        self.assertEqual((agg["total_connections"], agg["dropped"]), (6, 1))
        node = {"cons": 5000, "cons_dropped": 40, "status": "online"}
        agg = build(events, daemon={"node": node})["aggregates"]
        self.assertEqual((agg["node"]["cons"], agg["node"]["cons_dropped"]), (5000, 40))


if __name__ == "__main__":
    unittest.main()
