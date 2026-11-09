"""Read-only plugin API (HSB-PRD-001 sections 6.3, 7.7 and 10).

The suite runs on the standard library alone. When FastAPI is not installed,
a minimal stand-in for the two names plugin_api imports is placed in
sys.modules first, and the route bodies are exercised directly. When FastAPI
and its test client are available, a second class drives the real routes
over HTTP, including percent-encoded traversal attempts.
"""

import importlib.util
import inspect
import json
import os
import shutil
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

REPO = Path(__file__).resolve().parent.parent
FIXTURES = REPO / "fixtures" / "runs"
HAVE_FASTAPI = importlib.util.find_spec("fastapi") is not None


def _install_fastapi_stand_in():
    module = types.ModuleType("fastapi")

    class HTTPException(Exception):
        def __init__(self, status_code, detail=None):
            super().__init__(status_code, detail)
            self.status_code = status_code
            self.detail = detail

    class APIRouter:
        def __init__(self):
            self.routes = []

        def get(self, path):
            def decorate(fn):
                self.routes.append((path, fn))
                return fn
            return decorate

    module.HTTPException = HTTPException
    module.APIRouter = APIRouter
    sys.modules["fastapi"] = module


def _load_plugin_api():
    if not HAVE_FASTAPI and "fastapi" not in sys.modules:
        _install_fastapi_stand_in()
    spec = importlib.util.spec_from_file_location(
        "snitchboard_plugin_api_under_test", REPO / "dashboard" / "plugin_api.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


api = _load_plugin_api()
HTTPException = sys.modules["fastapi"].HTTPException

FULL = "run-20261102T030002Z"
OLDER_FULL = "run-20261102T020002Z"
TRIMMED = "run-20261101T010002Z"


def size_of(payload):
    return len(json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode())


class RunsDirCase(unittest.TestCase):
    """Each test gets its own live runs directory seeded with the fixtures."""

    settings = {}

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="snitchboard-api-"))
        self.runs = self.tmp / "runs"
        shutil.copytree(FIXTURES, self.runs)
        api._summary_cache.clear()
        raw = {"runs_dir": str(self.runs), "mode": "live", **self.settings}
        patcher = mock.patch.object(api, "_read_raw_settings", return_value=(raw, "test"))
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(shutil.rmtree, self.tmp)

    def assertStatus(self, code, fn, *args):
        with self.assertRaises(HTTPException) as caught:
            fn(*args)
        self.assertEqual(caught.exception.status_code, code)

    def write(self, name, content):
        path = self.runs / name
        path.write_bytes(content if isinstance(content, bytes) else content.encode())
        return path


class Identifiers(RunsDirCase):
    def test_a_valid_identifier_is_served(self):
        body = api.run_body(FULL, None)
        self.assertFalse(body["malformed"])
        self.assertEqual(body["record"]["run_id"], FULL)

    def test_malformed_identifiers_are_rejected(self):
        for bad in ("", "latest2", "run-2026", "RUN-20261102T030002Z",
                    "run-20261102T030002z", "run-20261102T0300020Z",
                    FULL + "\n", FULL + " ", " " + FULL, FULL + ".json",
                    "run-٢٠٢٦١١٠٢T030002Z",
                    "run-" + "1" * 5000, None, 20261102):
            with self.subTest(bad=bad):
                self.assertStatus(400, api.run_body, bad, None)

    def test_an_unknown_but_well_formed_identifier_is_not_found(self):
        self.assertStatus(404, api.run_body, "run-20991231T235959Z", None)


class PathTraversal(RunsDirCase):
    def setUp(self):
        super().setUp()
        # A complete, valid record outside the runs directory. Nothing a
        # client sends may reach it.
        self.outside = self.tmp / "outside"
        self.outside.mkdir()
        shutil.copy(self.runs / f"{FULL}.json", self.outside / f"{FULL}.json")

    def test_traversal_strings_are_rejected_before_any_file_access(self):
        attempts = (
            "../outside/" + FULL, "..", "../..", "../../etc/passwd",
            "/etc/passwd", FULL + "/../" + FULL, "..%2F..%2Fetc%2Fpasswd",
            "..\\..\\outside", "run-20261102T030002Z\x00.json",
            "%2e%2e%2f" + FULL, "~/" + FULL, "file:///etc/passwd",
        )
        with mock.patch.object(api, "_read_record",
                               side_effect=AssertionError("file was read")):
            for attempt in attempts:
                with self.subTest(attempt=attempt):
                    self.assertStatus(400, api.run_body, attempt, None)

    def test_a_symbolic_link_in_the_runs_directory_is_not_followed(self):
        target = self.outside / f"{FULL}.json"
        link_id = "run-20261103T000002Z"
        os.symlink(target, self.runs / f"{link_id}.json")
        self.assertNotIn(link_id, [r["run_id"] for r in api.runs_body(200, 0)["runs"]])
        self.assertStatus(404, api.run_body, link_id, None)

    def test_the_file_opened_always_comes_from_the_directory_listing(self):
        opened = []
        real = api._read_record

        def spy(path):
            opened.append(path)
            return real(path)

        with mock.patch.object(api, "_read_record", side_effect=spy):
            api.run_body(FULL, None)
        self.assertEqual(len(opened), 1)
        self.assertEqual(Path(opened[0]).parent, self.runs)

    def test_a_relative_runs_dir_is_refused(self):
        with mock.patch.object(api, "_read_raw_settings",
                               return_value=({"runs_dir": "runs", "mode": "live"}, "test")):
            health = api.health_body()
        self.assertEqual(health["runs_dir"]["status"], "invalid")
        self.assertEqual(health["record_count"], 0)

    def test_no_route_but_health_reports_a_filesystem_path(self):
        bodies = [api.settings_body(), api.runs_body(5, 0), api.series_body(24),
                  api.verify_body(), api.latest_body(None), api.run_body(FULL, None)]
        for body in bodies:
            self.assertNotIn(str(self.tmp), json.dumps(body))
        # /health reports the resolved directory on purpose, so an operator
        # behind the dashboard auth gate can see it inside the tab.
        self.assertEqual(api.health_body()["runs_dir"]["path"], str(self.runs))


class Bounds(RunsDirCase):
    def test_runs_page_is_capped(self):
        body = api.runs_body(10_000, 0)
        self.assertEqual(body["limit"], api.RUNS_LIMIT_MAX)
        self.assertLessEqual(len(body["runs"]), api.RUNS_LIMIT_MAX)
        self.assertEqual(body["total"], 26)

    def test_runs_are_newest_first_and_paginate(self):
        first = api.runs_body(10, 0)["runs"]
        second = api.runs_body(10, 10)["runs"]
        ids = [r["run_id"] for r in first + second]
        self.assertEqual(ids, sorted(ids, reverse=True))
        self.assertEqual(ids[0], FULL)
        self.assertEqual(api.runs_body(10, 500)["runs"], [])

    def test_invalid_paging_values_are_rejected(self):
        for limit, offset in ((0, 0), (-1, 0), (5, -1), ("5", 0), (5, None)):
            with self.subTest(limit=limit, offset=offset):
                self.assertStatus(400, api.runs_body, limit, offset)

    def test_series_is_capped(self):
        body = api.series_body(10_000)
        self.assertEqual(body["n"], api.SERIES_MAX)
        self.assertEqual(len(body["points"]), 26)
        self.assertStatus(400, api.series_body, 0)
        points = api.series_body(24)["points"]
        self.assertEqual(len(points), 24)
        self.assertEqual(points[-1]["run_id"], FULL)

    def test_summaries_carry_no_record_content(self):
        for item in api.runs_body(200, 0)["runs"]:
            self.assertLessEqual(set(item), {
                "run_id", "malformed", "started_at", "window_start", "window_end",
                "status", "trimmed", "run_index", "severity_counts",
                "problem_count", "problems"})

    def test_an_oversized_file_is_not_read_past_the_cap(self):
        self.write("run-20261103T000002Z.json", b" " * (api.READ_CAP_BYTES + 10))
        record, problems = api._read_record(str(self.runs / "run-20261103T000002Z.json"))
        self.assertIsNone(record)
        self.assertIn("above", problems[0])

    def test_many_records_stay_within_count_and_size_bounds(self):
        source = (self.runs / f"{TRIMMED}.json").read_bytes()
        for i in range(400):
            self.write(f"run-2027{1 + i // 28:02d}{1 + i % 28:02d}T000000Z.json", source)
        listing = api.runs_body(10_000, 0)
        self.assertEqual(len(listing["runs"]), api.RUNS_LIMIT_MAX)
        self.assertLessEqual(size_of(listing), api.RESPONSE_MAX_BYTES)
        verdict = api.verify_body()
        self.assertLessEqual(len(verdict["links"]), api.VERIFY_LINKS_SHOWN)
        self.assertLessEqual(len(verdict["breaks"]), api.VERIFY_BREAKS_SHOWN)
        self.assertLessEqual(size_of(verdict), api.RESPONSE_MAX_BYTES)
        self.assertFalse(verdict["intact"])

    def test_the_record_count_is_capped(self):
        with mock.patch.object(api, "MAX_RECORDS", 10):
            health = api.health_body()
            self.assertEqual(health["record_count"], 10)
            self.assertTrue(health["records_truncated"])
            verdict = api.verify_body()
        self.assertFalse(verdict["complete"])
        self.assertIsNone(verdict["intact"])

    def test_verification_stops_inside_its_time_budget(self):
        with mock.patch.object(api, "VERIFY_BUDGET_S", -1.0):
            verdict = api.verify_body()
        self.assertFalse(verdict["complete"])
        self.assertIsNone(verdict["intact"])

    def test_an_oversized_payload_is_refused_rather_than_sent(self):
        with self.assertRaises(HTTPException) as caught:
            api._bounded({"blob": "x" * 2000}, limit=1000)
        self.assertEqual(caught.exception.status_code, 500)

    def test_every_route_fits_its_bound(self):
        for body, limit in ((api.health_body(), api.RESPONSE_MAX_BYTES),
                            (api.settings_body(), api.RESPONSE_MAX_BYTES),
                            (api.runs_body(200, 0), api.RESPONSE_MAX_BYTES),
                            (api.series_body(168), api.RESPONSE_MAX_BYTES),
                            (api.verify_body(), api.RESPONSE_MAX_BYTES),
                            (api.latest_body(None), api.RECORD_RESPONSE_MAX_BYTES),
                            (api.latest_body(True), api.RECORD_RESPONSE_MAX_BYTES)):
            self.assertLessEqual(size_of(body), limit)


class MalformedRecords(RunsDirCase):
    BAD = {
        "run-20261102T040002Z.json": b"{not json",
        "run-20261102T050002Z.json": json.dumps({"trimmed": False}).encode(),
        "run-20261102T060002Z.json": b'{"trimmed": NaN}',
        "run-20261102T070002Z.json": b"[" * 100_000 + b"]" * 100_000,
        "run-20261102T080002Z.json": b"\xff\xfe\x00",
    }

    def setUp(self):
        super().setUp()
        for name, content in self.BAD.items():
            self.write(name, content)

    def test_listing_reports_malformed_records_and_keeps_the_rest(self):
        body = api.runs_body(200, 0)
        by_id = {r["run_id"]: r for r in body["runs"]}
        self.assertEqual(body["total"], 26 + len(self.BAD))
        for name in self.BAD:
            entry = by_id[name[:-5]]
            self.assertTrue(entry["malformed"])
            self.assertTrue(entry["problems"])
        self.assertFalse(by_id[FULL]["malformed"])
        self.assertEqual(sum(not r["malformed"] for r in body["runs"]), 26)

    def test_latest_skips_newer_malformed_records(self):
        body = api.latest_body(None)
        self.assertEqual(body["run_id"], FULL)
        self.assertEqual(len(body["skipped_malformed"]), len(self.BAD))

    def test_a_malformed_record_is_served_as_a_report_not_as_data(self):
        body = api.run_body("run-20261102T050002Z", None)
        self.assertTrue(body["malformed"])
        self.assertIsNone(body["record"])
        self.assertGreater(body["problem_count"], 0)

    def test_a_record_under_the_wrong_file_name_is_malformed(self):
        self.write("run-20261102T090002Z.json", (self.runs / f"{FULL}.json").read_bytes())
        body = api.run_body("run-20261102T090002Z", None)
        self.assertTrue(body["malformed"])
        self.assertIsNone(body["record"])

    def test_series_and_verify_survive_malformed_records(self):
        points = api.series_body(168)["points"]
        self.assertEqual(sum(p["malformed"] for p in points), len(self.BAD))
        verdict = api.verify_body()
        self.assertTrue(verdict["complete"])
        self.assertFalse(verdict["intact"])
        self.assertEqual(verdict["first_break"]["run_id"], "run-20261102T040002Z")
        self.assertEqual(verdict["malformed_records"], len(self.BAD))

    def test_problem_text_is_masked(self):
        record = json.loads((self.runs / f"{FULL}.json").read_text())
        record["status"] = "203.0.113.77"
        self.write("run-20261102T090002Z.json", json.dumps(record))
        entry = api.run_body("run-20261102T090002Z", True)
        text = json.dumps(entry["problems"])
        self.assertNotIn("203.0.113.77", text)


class Verification(RunsDirCase):
    def test_the_fixture_chain_is_intact_and_names_trimmed_links(self):
        verdict = api.verify_body()
        self.assertTrue(verdict["complete"])
        self.assertTrue(verdict["intact"])
        self.assertEqual(verdict["checked"], 26)
        self.assertEqual(verdict["sealed_links"], 24)
        self.assertIn("not to the summary", verdict["trimmed_notice"])

    def test_an_edited_full_record_breaks_the_chain_at_that_run(self):
        path = self.runs / f"{OLDER_FULL}.json"
        record = json.loads(path.read_text())
        record["totals"]["denied"] += 1
        path.write_text(json.dumps(record))
        verdict = api.verify_body()
        self.assertFalse(verdict["intact"])
        self.assertEqual(verdict["first_break"]["run_id"], OLDER_FULL)

    def test_a_deleted_run_breaks_the_chain(self):
        os.remove(self.runs / "run-20261101T050002Z.json")
        verdict = api.verify_body()
        self.assertFalse(verdict["intact"])
        self.assertEqual(verdict["first_break"]["run_id"], "run-20261101T060002Z")


class Redaction(RunsDirCase):
    def raw_destination(self):
        record = json.loads((self.runs / f"{FULL}.json").read_text())
        return record["destinations"][0]

    def test_records_are_masked_by_default(self):
        body = api.latest_body(None)
        self.assertFalse(body["revealed"])
        self.assertNotIn(self.raw_destination(), json.dumps(body))

    def test_reveal_returns_the_stored_values(self):
        body = api.latest_body(True)
        self.assertTrue(body["revealed"])
        self.assertIn(self.raw_destination(), json.dumps(body))


class RevealDisabled(RunsDirCase):
    settings = {"allow_reveal": False}

    def test_reveal_is_refused_when_disabled(self):
        self.assertStatus(403, api.latest_body, True)
        self.assertStatus(403, api.run_body, FULL, True)
        self.assertFalse(api.latest_body(None)["revealed"])


class HealthPath(RunsDirCase):
    HOME_RUNS = "/home/test-user/runs"

    def health(self, reveal=None, **settings):
        raw = {"runs_dir": self.HOME_RUNS, "mode": "live", **settings}
        with mock.patch.object(api, "_read_raw_settings", return_value=(raw, "file")):
            return api.health_body(reveal)

    def test_a_home_path_is_masked_by_default(self):
        body = self.health()
        self.assertEqual(body["runs_dir"], {
            "location": "custom", "status": "missing",
            "path": "/home/[user]/runs", "path_masked": True})
        self.assertNotIn("test-user", json.dumps(body))
        self.assertEqual(body["settings_source"], "file")

    def test_reveal_shows_the_path(self):
        runs_dir = self.health(True)["runs_dir"]
        self.assertEqual(runs_dir["path"], self.HOME_RUNS)
        self.assertFalse(runs_dir["path_masked"])
        self.assertTrue(self.health(False)["runs_dir"]["path_masked"])

    def test_reveal_is_refused_when_disabled(self):
        with self.assertRaises(HTTPException) as caught:
            self.health(True, allow_reveal=False)
        self.assertEqual(caught.exception.status_code, 403)
        self.assertTrue(self.health(None, allow_reveal=False)["runs_dir"]["path_masked"])

    def test_redact_by_default_false_shows_the_path(self):
        runs_dir = self.health(None, redact_by_default=False)["runs_dir"]
        self.assertEqual(runs_dir["path"], self.HOME_RUNS)
        self.assertFalse(runs_dir["path_masked"])

    def test_the_default_location_is_reported_and_masked(self):
        with mock.patch.object(api, "_default_data_dir",
                               return_value=Path("/home/test-user/.hermes/plugin-data/x")):
            body = self.health(runs_dir="")
        self.assertEqual(body["runs_dir"]["location"], "default")
        self.assertEqual(body["runs_dir"]["path"], "/home/[user]/.hermes/plugin-data/x/runs")

    def test_a_relative_path_is_reported_as_configured(self):
        runs_dir = self.health(runs_dir="runs")["runs_dir"]
        self.assertEqual((runs_dir["status"], runs_dir["path"]), ("invalid", "runs"))

    def test_a_long_path_stays_within_bounds(self):
        body = self.health(True, runs_dir="/srv/" + "d" * 100_000)
        self.assertLessEqual(len(body["runs_dir"]["path"]), api.RUNS_DIR_CHARS)
        self.assertLessEqual(size_of(body), api.RESPONSE_MAX_BYTES)


class TrimmedCapSetting(RunsDirCase):
    def test_default_cap_keeps_trimmed_fixtures_valid(self):
        self.assertEqual(api.runs_body(200, 0)["malformed_on_page"], 0)

    def test_a_smaller_cap_makes_trimmed_records_malformed(self):
        with mock.patch.object(api, "_read_raw_settings", return_value=(
                {"runs_dir": str(self.runs), "mode": "live", "trimmed_max_bytes": 1024},
                "test")):
            body = api.runs_body(200, 0)
            by_id = {r["run_id"]: r for r in body["runs"]}
            self.assertTrue(by_id[TRIMMED]["malformed"])
            self.assertIn("above the cap of 1024", by_id[TRIMMED]["problems"][-1])
            self.assertFalse(by_id[FULL]["malformed"])
            self.assertEqual(body["malformed_on_page"], 24)
            self.assertTrue(api.run_body(TRIMMED, None)["malformed"])
            self.assertEqual(api.verify_body()["malformed_records"], 24)
        # The cached verdict under the smaller cap is not served afterwards.
        self.assertFalse(api.runs_body(200, 0)["runs"][-1]["malformed"])


class Modes(RunsDirCase):
    def test_auto_mode_uses_demonstration_data_when_no_records_exist(self):
        empty = self.tmp / "empty"
        empty.mkdir()
        with mock.patch.object(api, "_read_raw_settings",
                               return_value=({"runs_dir": str(empty)}, "test")):
            health = api.health_body()
            latest = api.latest_body(None)
        self.assertEqual(health["mode"], "demo")
        self.assertTrue(latest["demo"])
        self.assertEqual(health["record_count"], 26)

    def test_auto_mode_uses_live_records_when_present(self):
        with mock.patch.object(api, "_read_raw_settings",
                               return_value=({"runs_dir": str(self.runs)}, "test")):
            self.assertEqual(api.health_body()["mode"], "live")

    def test_live_mode_with_no_records_says_so_rather_than_showing_demo_data(self):
        missing = self.tmp / "missing"
        with mock.patch.object(api, "_read_raw_settings",
                               return_value=({"runs_dir": str(missing), "mode": "live"}, "test")):
            health = api.health_body()
            self.assertStatus(404, api.latest_body, None)
        self.assertEqual(health["mode"], "live")
        self.assertEqual(health["runs_dir"]["status"], "missing")

    def test_invalid_saved_settings_fall_back_to_defaults_and_are_reported(self):
        with mock.patch.object(api, "_read_raw_settings",
                               return_value=({"mode": "loud"}, "test")):
            body = api.settings_body()
        self.assertEqual(body["settings"]["mode"], "auto")
        self.assertTrue(body["problems"])

    def test_settings_expose_no_path(self):
        body = api.settings_body()
        self.assertEqual(body["settings"]["runs_dir"], "custom")
        self.assertEqual(body["settings"]["trimmed_max_bytes"], 8192)

    def test_settings_report_the_prd_1_1_settings_and_the_caps(self):
        raw = {"runs_dir": str(self.runs), "mode": "live", "trimmed_max_bytes": 16384,
               "telemetry_destinations": ["telemetry.example.net"]}
        with mock.patch.object(api, "_read_raw_settings", return_value=(raw, "test")):
            body = api.settings_body()
        self.assertEqual(body["settings"]["trimmed_max_bytes"], 16384)
        self.assertEqual(body["settings"]["telemetry_destinations"], ["telemetry.example.net"])
        self.assertEqual(body["caps"], {"rows": 120, "volume_rows": 45, "hosts": 20,
                                        "addrs": 15, "novel": 15, "beacons": 16,
                                        "aggregates": 20})
        self.assertEqual(set(body["settings"]), set(api.config.PLUGIN_DEFAULTS))


class Router(unittest.TestCase):
    def test_every_route_is_a_get_and_none_blocks(self):
        paths = []
        for route in api.router.routes:
            path = getattr(route, "path", None) or route[0]
            endpoint = getattr(route, "endpoint", None) or route[1]
            methods = getattr(route, "methods", {"GET"})
            self.assertEqual(set(methods) - {"HEAD"}, {"GET"}, path)
            self.assertTrue(inspect.iscoroutinefunction(endpoint), path)
            paths.append(path)
        self.assertEqual(paths, ["/health", "/settings", "/runs", "/runs/latest",
                                 "/runs/{run_id}", "/series", "/verify"])


@unittest.skipUnless(HAVE_FASTAPI and importlib.util.find_spec("httpx"),
                     "FastAPI and httpx are not installed")
class OverHttp(RunsDirCase):
    PREFIX = "/api/plugins/hermes-snitchboard"

    def setUp(self):
        super().setUp()
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        app = FastAPI()
        app.include_router(api.router, prefix=self.PREFIX)
        self.client = TestClient(app)

    def get(self, path):
        return self.client.get(self.PREFIX + path)

    def test_routes_answer(self):
        for path in ("/health", "/health?reveal=true", "/health?reveal=false", "/settings", "/runs?limit=3", "/runs/latest",
                     f"/runs/{FULL}", "/series?n=24", "/verify"):
            with self.subTest(path=path):
                self.assertEqual(self.get(path).status_code, 200)

    def test_encoded_traversal_never_reaches_a_file(self):
        with mock.patch.object(api, "_read_record",
                               side_effect=AssertionError("file was read")):
            for path in ("/runs/..%2F..%2Fetc%2Fpasswd", "/runs/%2e%2e",
                         "/runs/..%5C..%5Cetc", f"/runs/{FULL}%00",
                         f"/runs/{FULL}%0A", "/runs/%2Fetc%2Fpasswd"):
                with self.subTest(path=path):
                    self.assertIn(self.get(path).status_code, (400, 404, 422))

    def test_non_get_methods_are_refused(self):
        for method in ("post", "put", "delete", "patch"):
            with self.subTest(method=method):
                response = getattr(self.client, method)(self.PREFIX + "/runs/latest")
                self.assertEqual(response.status_code, 405)

    def test_health_reveal_over_http(self):
        masked = self.get("/health").json()["runs_dir"]
        shown = self.get("/health?reveal=true").json()["runs_dir"]
        self.assertTrue(masked["path_masked"])
        self.assertFalse(shown["path_masked"])
        self.assertEqual(shown["path"], str(self.runs))
        self.assertEqual(self.get("/health?reveal=maybe").status_code, 422)
        with mock.patch.object(api, "_read_raw_settings", return_value=(
                {"runs_dir": str(self.runs), "mode": "live", "allow_reveal": False}, "test")):
            self.assertEqual(self.get("/health?reveal=true").status_code, 403)

    def test_paging_type_errors_are_rejected(self):
        self.assertEqual(self.get("/runs?limit=abc").status_code, 422)
        self.assertEqual(self.get("/runs?limit=0").status_code, 400)


if __name__ == "__main__":
    unittest.main()
