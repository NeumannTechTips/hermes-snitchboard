"""The hourly collector (collector/snitchboard_collect.py), tested black-box.

Every test builds a small OpenSnitch database in a temporary directory from
tests/fixtures/opensnitch_sample.sql, runs main(argv, now=..., sleep=...) and
reads back the files it wrote. Nothing touches the network or a real database.

OpenSnitch writes naive local times, so every timestamp here starts life as a
naive local datetime: the string stored in the database and the aware `now`
and --window-end passed to the collector are both derived from it, which keeps
the tests correct in any timezone. The day used is clear of DST changes in
the common zones.
"""

import contextlib
import importlib.util
import io
import json
import os
import pwd
import sqlite3
import stat
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from snitchboard import chain, config, schema

REPO = Path(__file__).resolve().parent.parent
COLLECTOR = REPO / "collector" / "snitchboard_collect.py"
SQL = (Path(__file__).resolve().parent / "fixtures" / "opensnitch_sample.sql").read_text(
    encoding="utf-8")

# Naive local time at the start of window 0. Window h covers
# [BASE + h hours, BASE + h + 1 hours).
BASE = datetime(2026, 11, 2, 10, 0, 0)

CONNECTION_COLUMNS = (
    "time", "node", "action", "protocol", "src_ip", "src_port", "dst_ip",
    "dst_host", "dst_port", "uid", "pid", "process", "process_args",
    "process_cwd", "rule",
)
SOCKET_COLUMNS = (
    "id", "last_seen", "node", "src_port", "src_ip", "dst_ip", "dst_port",
    "proto", "uid", "inode", "iface", "family", "state", "cookies", "rqueue",
    "wqueue", "expires", "retrans", "timer", "mark", "proc_pid", "proc_comm",
    "proc_path",
)
HUGE = 1_000_000  # every fixture lifetime counter is far above this

SECRET_ARGS = "/usr/bin/test-app --token=TESTSECRET0001"
LEAKS = ("192.0.2", "203.0.113", "198.51.100", "2001:db8", "example.",
         "/usr/", "/home/")

_module = None


def collector():
    global _module
    if _module is None:
        spec = importlib.util.spec_from_file_location("snitchboard_collect", COLLECTOR)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        _module = mod
    return _module


# ------------------------------------------------------------------ time

def naive_at(hours=0, minutes=0, seconds=0, micro=0):
    return BASE + timedelta(hours=hours, minutes=minutes, seconds=seconds,
                            microseconds=micro)


def stamp(naive):
    """Format as OpenSnitch does: str(datetime), so no fraction when zero."""
    return str(naive)


def aware(naive):
    return naive.astimezone()


def window_end(h=0):
    """The aware end of window h."""
    return aware(naive_at(hours=h + 1))


def now_after(h=0, minutes=2):
    return aware(naive_at(hours=h + 1, minutes=minutes))


# ------------------------------------------------------------- database

def conn_row(naive=None, *, time=None, host="svc.example.com", ip="203.0.113.5",
             port="443", action="allow", proto="tcp", process="/usr/bin/test-app",
             args=None, cwd="/home/test-user", uid="1000", pid="3001",
             node="unix:/local", src="192.0.2.1"):
    return {
        "time": time if time is not None else stamp(naive), "node": node,
        "action": action, "protocol": proto, "src_ip": src, "src_port": "40100",
        "dst_ip": ip, "dst_host": host, "dst_port": port, "uid": uid,
        "pid": pid, "process": process, "process_args": args or process,
        "process_cwd": cwd, "rule": "allow-test-app",
    }


def socket_row(naive, *, proto="tcp", src="192.0.2.1", sport="40100",
               dst="203.0.113.5", dport="443"):
    row = dict.fromkeys(SOCKET_COLUMNS, "0")
    row.update(id="2", last_seen=stamp(naive), node="unix:/local", src_port=sport,
               src_ip=src, dst_ip=dst, dst_port=dport, proto=proto,
               family="AF_INET", state="ESTABLISHED", proc_comm="test-app",
               proc_path="/usr/bin/test-app")
    return row


def make_db(path, rows=(), *, sockets=(), drop=(), connection_columns=None,
            keep_samples=True, sql_after=()):
    con = sqlite3.connect(str(path))
    try:
        con.executescript(SQL)
        if not keep_samples:
            con.execute("DELETE FROM connections")
        for table in drop:
            con.execute(f"DROP TABLE {table}")
        if connection_columns is not None:
            con.execute("DROP TABLE connections")
            con.execute("CREATE TABLE connections ("
                        + ", ".join(f"{c} TEXT" for c in connection_columns) + ")")
        for statement in sql_after:
            con.execute(statement)
        tables = {r[0] for r in con.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'")}
        for table, items in (("connections", rows), ("sockets", sockets)):
            if table not in tables:
                continue
            cols = [r[1] for r in con.execute(f"PRAGMA table_info({table})")]
            for item in items:
                use = [c for c in cols if c in item]
                con.execute(
                    f"INSERT INTO {table} ({', '.join(use)}) VALUES "
                    f"({', '.join('?' for _ in use)})", [item[c] for c in use])
        con.commit()
    finally:
        con.close()


def clean_rows():
    """Window 0 traffic plus rows either side of it."""
    return [
        # Outside the window: just before it, exactly at its end, and later.
        conn_row(naive_at(minutes=-1, micro=500000), host="other.example.com"),
        conn_row(naive_at(hours=1), host="other.example.com"),
        conn_row(naive_at(hours=2, minutes=30), host="other.example.com"),
        # Inside: both time forms OpenSnitch writes, with and without a fraction.
        conn_row(naive_at(minutes=5, micro=123456)),
        conn_row(naive_at(minutes=20)),
        conn_row(naive_at(minutes=35, micro=1), host="api.example.net",
                 ip="198.51.100.7", port="53", proto="udp", action="deny",
                 process="/usr/local/bin/test-agent", pid="3002"),
        conn_row(naive_at(minutes=50, seconds=7), host="", ip="2001:db8::5",
                 port="8443", src="2001:db8::1"),
    ]


# ---------------------------------------------------------------- tests

class CollectorTestCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        (self.tmp / "db").mkdir()
        self.db = self.tmp / "db" / "opensnitch.sqlite3"
        self.runs = self.tmp / "runs"
        self.sleeps = []
        self.validate_on_teardown = True
        self.mod = collector()

    def tearDown(self):
        if self.validate_on_teardown and self.runs.is_dir():
            self.records()

    # helpers

    def run_collector(self, *extra, now, window=None, db=None, runs=None,
                      with_window=True):
        argv = ["--db", str(db or self.db), "--runs-dir", str(runs or self.runs)]
        if with_window:
            end = window if window is not None else window_end(0)
            argv += ["--window-end", end.isoformat()]
        argv += list(extra)
        return self.invoke(argv, now=now)

    def invoke(self, argv, *, now):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                code = self.mod.main(argv, now=now, sleep=self.sleeps.append)
            except SystemExit as exc:
                code = exc.code
        return code, out.getvalue(), err.getvalue()

    def files(self, runs=None):
        runs = runs or self.runs
        return sorted(p for p in runs.glob("run-*.json")) if runs.is_dir() else []

    def assert_valid(self, record):
        problems = schema.validate(
            record, aggregate_cap=config.DEFAULTS["aggregate_cap"],
            trimmed_cap=config.DEFAULTS["trimmed_max_bytes"])
        self.assertEqual(problems, [], record.get("run_id"))

    def records(self, runs=None):
        out = []
        for path in self.files(runs):
            text = path.read_text(encoding="utf-8")
            record = json.loads(text)
            self.assert_valid(record)
            self.assertEqual(path.name, record["run_id"] + ".json")
            self.assertEqual(
                text, json.dumps(record, indent=1, sort_keys=True, ensure_ascii=False) + "\n")
            out.append(record)
        return sorted(out, key=lambda r: r["run_id"])

    def collect_one(self, rows=(), *, now=None, window=None, **db_kw):
        make_db(self.db, rows, **db_kw)
        code, out, err = self.run_collector(now=now or now_after(0), window=window)
        self.assertEqual(code, 0, err)
        records = self.records()
        self.assertEqual(len(records), 1)
        return records[0], out, err

    def assert_no_leak(self, text):
        for needle in LEAKS + (str(self.db), str(self.runs), str(self.tmp)):
            self.assertNotIn(needle, text)


class CleanWindow(CollectorTestCase):
    def test_one_ok_record_from_window_rows_only(self):
        sockets = [socket_row(naive_at(minutes=10)),
                   socket_row(naive_at(hours=3), dport="8443")]
        record, out, err = self.collect_one(clean_rows(), sockets=sockets)
        self.assertEqual(record["status"], schema.STATUS_OK, record["note"])
        self.assertFalse(record["trimmed"])
        self.assertEqual(parse(record["window_start"]), aware(naive_at()))
        self.assertEqual(parse(record["window_end"]), window_end(0))
        self.assertEqual(record["run_id"], schema.run_id_for(record["started_at"]))
        self.assertEqual(parse(record["started_at"]), now_after(0))
        self.assertEqual(record["integrity"]["run_index"], 0)
        self.assertEqual(record["integrity"]["prev_sha256"], schema.GENESIS_SHA256)

        # Both time forms are counted; rows outside the window are not.
        self.assertEqual(record["totals"]["connections"], 4)
        self.assertEqual(record["totals"]["denied"], 1)
        self.assertNotIn("other.example.com", record["destinations"])
        self.assertEqual(sorted(record["destinations"]),
                         ["2001:db8::5", "api.example.net", "svc.example.com"])

        self.assertIs(record["volume"]["available"], False)
        self.assertEqual(record["volume"]["rows"], [])

        agg = record["aggregates"]
        self.assertEqual(agg["hosts"], [{"what": "svc.example.com", "hits": 2},
                                        {"what": "api.example.net", "hits": 1}])
        self.assertEqual(sum(a["hits"] for a in agg["addrs"]), 4)
        for name in schema.AGGREGATE_LISTS:
            for item in agg[name]:
                self.assertLess(item["hits"], HUGE, name)
        self.assertEqual(agg["total_connections"], 4)
        self.assertEqual(agg["dropped"], 1)

        # Daemon panels come from nodes / rules / sockets.
        self.assertEqual(agg["node"]["hostname"], "node1.example.com")
        self.assertEqual(agg["node"]["daemon_uptime"], 93784)  # 1 day, 2:03:04
        self.assertEqual(agg["daemon_uptime"], 93784)
        self.assertEqual(agg["node"]["cons"], 4242)
        self.assertEqual(agg["rules"], 2)
        by_name = {r["name"]: r for r in agg["rules_detail"]}
        self.assertIs(by_name["allow-test-app"]["enabled"], True)
        self.assertIs(by_name["allow-test-app"]["precedence"], False)
        self.assertIs(by_name["deny-test-agent"]["precedence"], True)
        self.assertEqual(agg["sockets"],
                         [{"what": "tcp 192.0.2.1:40100 -> 203.0.113.5:443", "hits": 1}])

        # The journal output names no address, host or path.
        self.assertIn(record["run_id"], out)
        self.assert_no_leak(out + err)

    def test_quiet_prints_nothing_on_success(self):
        make_db(self.db, clean_rows())
        code, out, _ = self.run_collector("--quiet", now=now_after(0))
        self.assertEqual(code, 0)
        self.assertEqual(out, "")
        self.assertEqual(len(self.records()), 1)

    def test_default_window_is_the_hour_before_now(self):
        make_db(self.db, clean_rows())
        code, _, err = self.run_collector(now=now_after(0, minutes=37), with_window=False)
        self.assertEqual(code, 0, err)
        record = self.records()[0]
        self.assertEqual(parse(record["window_end"]), window_end(0))
        self.assertEqual(parse(record["window_start"]), aware(naive_at()))
        self.assertEqual(record["totals"]["connections"], 4)

    def test_empty_sockets_table_is_still_ok(self):
        record, _, _ = self.collect_one(clean_rows(), sql_after=["DELETE FROM sockets"])
        self.assertEqual(record["status"], schema.STATUS_OK, record["note"])
        self.assertEqual(record["aggregates"]["sockets"], [])

    def test_unparseable_daemon_uptime_does_not_make_the_run_partial(self):
        record, _, _ = self.collect_one(clean_rows(), sql_after=[
            "UPDATE nodes SET daemon_uptime = '2026-11-01 09:00:00'"])
        self.assertEqual(record["status"], schema.STATUS_OK, record["note"])
        self.assertIsInstance(record["aggregates"]["node"]["daemon_uptime"], int)

    def test_long_operator_data_is_capped_and_marked(self):
        cap = self.mod.OPERATOR_DATA_MAX_CHARS
        long_data = ",".join(f"203.0.113.{i % 250}" for i in range(2000))
        record, _, _ = self.collect_one(clean_rows(), sql_after=[
            f"UPDATE rules SET operator_data = '{long_data}' "
            "WHERE name = 'deny-test-agent'"])
        self.assertEqual(record["status"], schema.STATUS_OK, record["note"])
        by_name = {r["name"]: r for r in record["aggregates"]["rules_detail"]}
        cut = by_name["deny-test-agent"]["operator_data"]
        self.assertTrue(cut.startswith(long_data[:cap]))
        self.assertTrue(cut.endswith(f" [truncated from {len(long_data)} characters]"))
        self.assertLess(len(cut), cap + 60)
        # A short operand is left exactly as it was.
        self.assertEqual(by_name["allow-test-app"]["operator_data"], "/usr/bin/test-app")
        self.assertIn("truncated", record["note"])

    def test_reject_is_deny_and_process_args_are_never_stored(self):
        rows = [conn_row(naive_at(minutes=10), action="reject", args=SECRET_ARGS,
                         cwd="/home/test-user/secret-project"),
                conn_row(naive_at(minutes=11), action="ALLOW", args=SECRET_ARGS)]
        record, _, _ = self.collect_one(rows)
        self.assertEqual(record["totals"]["denied"], 1)
        self.assertEqual(record["totals"]["allowed"], 1)
        self.assertEqual(sorted(r["action"] for r in record["rows"]), ["allow", "deny"])
        text = self.files()[0].read_text(encoding="utf-8")
        self.assertNotIn("TESTSECRET0001", text)
        self.assertNotIn("--token", text)
        self.assertNotIn("secret-project", text)


class NoData(CollectorTestCase):
    def assert_no_data(self, record):
        self.assertEqual(record["status"], schema.STATUS_NO_DATA)
        self.assertTrue(record["note"].strip())
        self.assertEqual(record["totals"]["connections"], 0)
        self.assertNotIn(str(self.db), record["note"])
        self.assertNotIn(str(self.tmp), record["note"])

    def test_window_with_no_rows(self):
        # Only the fixture's October rows exist.
        record, _, _ = self.collect_one()
        self.assert_no_data(record)

    def test_empty_connections_table(self):
        record, _, _ = self.collect_one(keep_samples=False)
        self.assert_no_data(record)

    def test_unrecognised_time_format(self):
        rows = [conn_row(time="yesterday at noon"), conn_row(time="yesterday at noon")]
        record, _, _ = self.collect_one(rows, keep_samples=False)
        self.assert_no_data(record)
        self.assertIn("format", record["note"].lower())

    def test_missing_connections_table(self):
        record, _, _ = self.collect_one(drop=["connections"])
        self.assert_no_data(record)

    def test_missing_required_column(self):
        cols = [c for c in CONNECTION_COLUMNS if c != "dst_port"]
        record, _, _ = self.collect_one(clean_rows(), connection_columns=cols)
        self.assert_no_data(record)

    def test_missing_database_file(self):
        code, out, err = self.run_collector(now=now_after(0))
        self.assertEqual(code, 0, err)
        self.assert_no_data(self.records()[0])
        self.assert_no_leak(out + err)

    def test_file_that_is_not_a_database(self):
        self.db.write_bytes(b"this is not an sqlite database\n" * 64)
        code, _, err = self.run_collector(now=now_after(0))
        self.assertEqual(code, 0, err)
        self.assert_no_data(self.records()[0])

    def test_busy_database_is_retried_then_reported(self):
        make_db(self.db, clean_rows())
        holder = sqlite3.connect(str(self.db), isolation_level=None)
        try:
            holder.execute("BEGIN EXCLUSIVE")
            code, _, err = self.run_collector(now=now_after(0))
        finally:
            holder.execute("ROLLBACK")
            holder.close()
        self.assertEqual(code, 0, err)
        self.assert_no_data(self.records()[0])
        self.assertTrue(self.sleeps, "busy retries should back off through sleep")
        self.assertIn("busy", self.records()[0]["note"].lower())


class Partial(CollectorTestCase):
    def test_missing_sockets_table(self):
        record, _, _ = self.collect_one(clean_rows(), drop=["sockets"])
        self.assertEqual(record["status"], schema.STATUS_PARTIAL)
        self.assertTrue(record["note"].strip())
        self.assertEqual(record["aggregates"]["sockets"], [])
        self.assertEqual(record["totals"]["connections"], 4)

    def test_missing_nodes_or_rules_table(self):
        for table in ("nodes", "rules"):
            with self.subTest(table=table):
                if self.runs.exists():
                    for p in self.runs.iterdir():
                        p.unlink()
                if self.db.exists():
                    self.db.unlink()
                record, _, _ = self.collect_one(clean_rows(), drop=[table])
                self.assertEqual(record["status"], schema.STATUS_PARTIAL)
                self.assertTrue(record["note"].strip())
                self.assertEqual(record["totals"]["connections"], 4)

    def test_missing_unread_column_is_noted_but_stays_ok(self):
        # The collector never reads these, so their absence changes nothing in
        # the record and must not turn every hour into a coverage gap.
        for column in ("process_cwd", "process_args", "rule", "src_port"):
            with self.subTest(column=column):
                for p in self.runs.glob("*") if self.runs.exists() else ():
                    p.unlink()
                if self.db.exists():
                    self.db.unlink()
                cols = [c for c in CONNECTION_COLUMNS if c != column]
                record, _, _ = self.collect_one(clean_rows(), connection_columns=cols)
                self.assertEqual(record["status"], schema.STATUS_OK)
                self.assertIn(column, record["note"])
                self.assertEqual(record["totals"]["connections"], 4)

    def test_missing_read_column_is_partial_and_named(self):
        cols = [c for c in CONNECTION_COLUMNS if c != "dst_host"]
        record, _, _ = self.collect_one(clean_rows(), connection_columns=cols)
        self.assertEqual(record["status"], schema.STATUS_PARTIAL)
        self.assertIn("dst_host", record["note"])
        self.assertEqual(record["totals"]["connections"], 4)
        self.assertEqual(record["aggregates"]["hosts"], [])

    def test_unusable_rows_are_skipped(self):
        rows = [
            conn_row(naive_at(minutes=1), action="maybe"),
            conn_row(naive_at(minutes=2), port="https"),
            conn_row(naive_at(minutes=3), port="-1"),
            conn_row(naive_at(minutes=4), proto=""),
            conn_row(naive_at(minutes=5), ip=""),
            # Bad uid / pid are kept, with the value left out.
            conn_row(naive_at(minutes=6), uid="not-a-uid", pid=""),
            conn_row(naive_at(minutes=7)),
        ]
        record, _, _ = self.collect_one(rows)
        self.assertEqual(record["status"], schema.STATUS_PARTIAL)
        self.assertTrue(record["note"].strip())
        self.assertEqual(record["totals"]["connections"], 2)
        self.assertIn(None, [r["uid"] for r in record["rows"]])


class Chain(CollectorTestCase):
    def test_two_consecutive_windows_form_a_chain(self):
        rows = clean_rows() + [conn_row(naive_at(hours=1, minutes=15),
                                        host="next.example.com")]
        make_db(self.db, rows)
        self.assertEqual(self.run_collector(now=now_after(0), window=window_end(0))[0], 0)
        self.assertEqual(self.run_collector(now=now_after(1), window=window_end(1))[0], 0)
        first, second = self.records()
        self.assertTrue(chain.verify([first, second])["intact"])
        self.assertEqual(second["integrity"]["prev_sha256"],
                         first["integrity"]["content_sha256"])
        self.assertEqual([first["integrity"]["run_index"],
                          second["integrity"]["run_index"]], [0, 1])
        self.assertEqual(parse(second["window_start"]), parse(first["window_end"]))
        # The exact-end row belongs to window 1, not window 0.
        self.assertIn("other.example.com", second["destinations"])
        self.assertIn("next.example.com", second["destinations"])

    def test_same_window_twice_is_refused(self):
        make_db(self.db, clean_rows())
        self.assertEqual(self.run_collector(now=now_after(0))[0], 0)
        before = [p.read_bytes() for p in self.files()]
        code, out, err = self.run_collector(now=now_after(0, minutes=3))
        self.assertEqual(code, 1)
        self.assertEqual([p.read_bytes() for p in self.files()], before)
        self.assert_no_leak(out + err)

    def test_overlapping_window_is_refused(self):
        make_db(self.db, clean_rows())
        self.assertEqual(self.run_collector(now=now_after(0))[0], 0)
        code, _, _ = self.run_collector(
            now=now_after(0, minutes=40),
            window=aware(naive_at(hours=1, minutes=30)))
        self.assertEqual(code, 1)
        self.assertEqual(len(self.files()), 1)

    def test_clock_behind_newest_record_is_refused(self):
        make_db(self.db, clean_rows())
        self.assertEqual(self.run_collector(now=now_after(2), window=window_end(2))[0], 0)
        code, _, _ = self.run_collector(now=now_after(0), window=window_end(0))
        self.assertEqual(code, 1)
        self.assertEqual(len(self.files()), 1)

    def test_window_end_in_the_future_is_refused(self):
        make_db(self.db, clean_rows())
        code, _, _ = self.run_collector(now=now_after(0), window=window_end(3))
        self.assertEqual(code, 1)
        self.assertEqual(self.files(), [])

    def test_unreadable_chain_head_is_refused(self):
        self.validate_on_teardown = False
        make_db(self.db, clean_rows())
        self.runs.mkdir()
        earlier = (now_after(0) - timedelta(hours=5)).astimezone(timezone.utc)
        head = self.runs / ("run-" + earlier.strftime("%Y%m%dT%H%M%SZ") + ".json")
        head.write_text("{ not json", encoding="utf-8")
        code, out, err = self.run_collector(now=now_after(0))
        self.assertEqual(code, 1)
        self.assertEqual(self.files(), [head])
        self.assert_no_leak(out + err)

    def test_old_records_are_trimmed_after_retention(self):
        settings = self.tmp / "settings.json"
        settings.write_text(json.dumps({"retention_days": 1, "runs_dir": "ignored",
                                        "mode": "live"}), encoding="utf-8")
        rows = clean_rows() + [conn_row(naive_at(hours=72, minutes=10))]
        make_db(self.db, rows)
        code, _, err = self.run_collector("--settings", str(settings), now=now_after(0))
        self.assertEqual(code, 0, err)
        (original,) = self.records()
        self.assertFalse(original["trimmed"])

        code, out, err = self.run_collector("--settings", str(settings),
                                            now=now_after(72), window=window_end(72))
        self.assertEqual(code, 0, err)
        old, new = self.records()
        self.assertEqual(old["run_id"], original["run_id"])
        self.assertIs(old["trimmed"], True)
        self.assertIs(new["trimmed"], False)
        self.assertEqual(old["destinations"], original["destinations"])
        self.assertEqual(old["integrity"]["sealed_sha256"],
                         original["integrity"]["content_sha256"])
        self.assertEqual(schema.validate(
            old, trimmed_cap=config.DEFAULTS["trimmed_max_bytes"]), [])
        self.assertEqual(new["integrity"]["prev_sha256"],
                         original["integrity"]["content_sha256"])
        self.assertEqual(new["integrity"]["run_index"], 1)
        self.assertTrue(chain.verify([old, new])["intact"])
        self.assertEqual(stat.S_IMODE(self.files()[0].stat().st_mode), 0o640)
        self.assert_no_leak(out + err)


class Safety(CollectorTestCase):
    def test_missing_db_argument_is_a_usage_error(self):
        code, _, _ = self.invoke(["--runs-dir", str(self.runs),
                                  "--window-end", window_end(0).isoformat()],
                                 now=now_after(0))
        self.assertEqual(code, 2)
        self.assertFalse(self.runs.exists())

    def test_invalid_settings_is_a_usage_error(self):
        make_db(self.db, clean_rows())
        # Engine thresholds such as aggregate_cap are not collector settings:
        # only the plugin keys are accepted.
        for content in ('{"no_such_setting": 1}', "not json", '{"retention_days": -1}',
                        '{"aggregate_cap": 50}', '["retention_days"]'):
            with self.subTest(content=content):
                settings = self.tmp / "bad-settings.json"
                settings.write_text(content, encoding="utf-8")
                code, out, err = self.run_collector("--settings", str(settings),
                                                    now=now_after(0))
                self.assertEqual(code, 2)
                self.assertEqual(self.files(), [])
                self.assertNotIn(str(settings), out + err)

    def test_dry_run_writes_nothing_and_leaks_nothing(self):
        rows = clean_rows()
        uid = os.getuid()
        rows.append(conn_row(naive_at(minutes=40), uid=str(uid)))
        make_db(self.db, rows)
        code, out, err = self.run_collector("--dry-run", now=now_after(0))
        self.assertEqual(code, 0, err)
        self.assertFalse(self.runs.exists())
        self.assertIn("run-", out)
        self.assert_no_leak(out + err)
        try:
            name = pwd.getpwuid(uid).pw_name
        except KeyError:
            name = ""
        if len(name) >= 4:
            self.assertNotIn(name, out + err)

    def test_dry_run_leaves_an_existing_runs_dir_untouched(self):
        settings = self.tmp / "settings.json"
        settings.write_text('{"retention_days": 1}', encoding="utf-8")
        rows = clean_rows() + [conn_row(naive_at(hours=72, minutes=10))]
        make_db(self.db, rows)
        self.assertEqual(self.run_collector("--settings", str(settings),
                                            now=now_after(0))[0], 0)
        snapshot = {p.name: (p.read_bytes(), p.stat().st_mtime_ns)
                    for p in self.runs.iterdir()}
        code, out, err = self.run_collector("--dry-run", "--settings", str(settings),
                                            now=now_after(72), window=window_end(72))
        self.assertEqual(code, 0, err)
        self.assertEqual({p.name: (p.read_bytes(), p.stat().st_mtime_ns)
                          for p in self.runs.iterdir()}, snapshot)
        self.assert_no_leak(out + err)

    def test_database_is_not_modified(self):
        make_db(self.db, clean_rows())
        db_dir = self.db.parent
        before = (self.db.read_bytes(), self.db.stat().st_mtime_ns,
                  sorted(os.listdir(db_dir)))
        self.assertEqual(self.run_collector(now=now_after(0))[0], 0)
        self.assertEqual(self.run_collector("--dry-run", now=now_after(1),
                                            window=window_end(1))[0], 0)
        after = (self.db.read_bytes(), self.db.stat().st_mtime_ns,
                 sorted(os.listdir(db_dir)))
        self.assertEqual(after, before)
        self.assertEqual(after[2], [self.db.name])  # no -wal, -shm or -journal

    def test_lock_held_refuses_and_is_left_alone(self):
        make_db(self.db, clean_rows())
        self.runs.mkdir()
        self.assertEqual(self.mod.LOCK_NAME, ".snitchboard-collect.lock")
        lock = self.runs / self.mod.LOCK_NAME
        lock.write_text("12345\n", encoding="utf-8")
        code, out, err = self.run_collector(now=now_after(0))
        self.assertEqual(code, 1)
        self.assertEqual(self.files(), [])
        self.assertTrue(lock.exists(), "another collector's lock must not be removed")
        self.assertIn("lock", (out + err).lower())
        self.assert_no_leak(out + err)

    def test_lock_is_removed_after_a_normal_run(self):
        make_db(self.db, clean_rows())
        self.assertEqual(self.run_collector(now=now_after(0))[0], 0)
        self.assertFalse((self.runs / self.mod.LOCK_NAME).exists())
        # No temporary files are left behind either.
        self.assertEqual(sorted(p.name for p in self.runs.iterdir()),
                         [p.name for p in self.files()])

    def test_file_and_created_dir_modes(self):
        make_db(self.db, clean_rows())
        self.assertEqual(self.run_collector(now=now_after(0))[0], 0)
        self.assertEqual(stat.S_IMODE(self.runs.stat().st_mode), 0o750)
        (path,) = self.files()
        self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o640)

    def test_existing_runs_dir_mode_is_kept(self):
        make_db(self.db, clean_rows())
        self.runs.mkdir()
        os.chmod(self.runs, 0o700)
        self.assertEqual(self.run_collector(now=now_after(0))[0], 0)
        self.assertEqual(stat.S_IMODE(self.runs.stat().st_mode), 0o700)

    def test_runs_dir_parent_is_not_created(self):
        make_db(self.db, clean_rows())
        deep = self.tmp / "missing-parent" / "runs"
        code, _, _ = self.run_collector(now=now_after(0), runs=deep)
        self.assertNotEqual(code, 0)
        self.assertFalse(deep.parent.exists())


def parse(value):
    return schema.parse_timestamp(value)


if __name__ == "__main__":
    unittest.main()
