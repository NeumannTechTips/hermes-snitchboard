#!/usr/bin/env python3
"""Reference collector: one hour of OpenSnitch connections in, one sealed run record out.

The collector reads the OpenSnitch statistics database read-only, analyses one
window of connections with the snitchboard engine, seals the result into the
hash chain and writes it atomically into the runs directory. Full records
older than retention_days are then trimmed, never deleted, so the chain
survives. Hermes never runs this script: the owner runs it under their own
account, normally from the systemd user timer in collector/systemd/.

Usage:
    snitchboard_collect.py --db PATH --runs-dir PATH [--window-end ISO8601]
                           [--settings PATH] [--dry-run] [--quiet]

The window is the hour that ends at --window-end, which defaults to the top
of the current hour. One run is written per window: a window that was already
collected, or that overlaps an earlier run, is refused.

Exit status: 0 when a record was written (whatever its status) or a dry run
finished, 1 when the run was refused or failed, 2 for a usage error.

Output carries counts, the run id and plain status words only. It never names
an address, host, path, user or the text of an exception, because the journal
it lands in may be read by others.
"""

import argparse
import errno
import json
import os
import pwd
import re
import signal
import sqlite3
import stat
import sys
import tempfile
import time
import urllib.parse
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from snitchboard import analysis, chain, config, schema  # noqa: E402

LOCK_NAME = ".snitchboard-collect.lock"
WINDOW = timedelta(hours=1)

# The busy handler waits this long inside SQLite before a statement gives up;
# the retry loop below then backs off and tries the whole read again.
CONNECT_TIMEOUT_S = 1.0
BUSY_ATTEMPTS = 3
BUSY_BACKOFF_S = 1.0

# Records are pretty-printed, so a file is larger than its canonical form.
# Anything far beyond the full-record cap cannot be valid and is not read.
MAX_RECORD_FILE_BYTES = 8 * schema.CAPS["full_bytes"]
MAX_SETTINGS_BYTES = 1024 * 1024

# Rows are prefiltered in SQL by date with this margin on each side, then
# filtered exactly in Python. The margin exceeds any UTC offset, so a lexical
# comparison of local wall-clock text cannot lose a row from the window.
PREFILTER_MARGIN = timedelta(days=1)

RECORD_FILE = re.compile(r"\A(run-\d{8}T\d{6}Z)\.json\Z", re.ASCII)

CONNECTION_REQUIRED = ("time", "action", "protocol", "dst_ip", "dst_port")
# Optional columns the collector reads. Losing one empties a field in the
# record, so the run is partial.
CONNECTION_OPTIONAL_READ = ("node", "src_ip", "dst_host", "uid", "pid", "process")
# Optional columns the collector never reads. Their absence changes nothing in
# the record, so it is noted but the status is not lowered: coverage counts
# only ok runs, and an older database would otherwise show every hour as a gap.
CONNECTION_OPTIONAL_UNREAD = ("src_port", "process_args", "process_cwd", "rule")
# process_args is deliberately never selected: arguments can carry secrets,
# and data minimisation says what is not needed is not stored.
CONNECTION_SELECTED = ("time", "node", "action", "protocol", "src_ip", "dst_ip",
                       "dst_host", "dst_port", "uid", "pid", "process")
# operator_data can hold an inline list of any length. Uncapped, one large rule
# could push every record past the full-record cap and stop collection.
OPERATOR_DATA_MAX_CHARS = 512
NODE_COLUMNS = ("addr", "hostname", "daemon_version", "daemon_uptime",
                "daemon_rules", "cons", "cons_dropped", "version", "status",
                "last_connection")
NODE_COUNTERS = ("daemon_rules", "cons", "cons_dropped")
RULE_COLUMNS = ("name", "enabled", "precedence", "action", "duration",
                "operator_type", "operator_operand", "operator_data", "created")
SOCKET_COLUMNS = ("last_seen", "proto", "src_ip", "src_port", "dst_ip", "dst_port")

NO_DATA_PREFIX = "Collection unavailable: "


class Refused(Exception):
    """The run must not go ahead; the message is plain and names no path."""


class Failed(Exception):
    """The run went wrong part way; the message is plain and names no path."""


class UsageError(Exception):
    """Bad settings or arguments; reported with exit status 2."""


# ------------------------------------------------------------------ times

_WALL = r"(\d{4}-\d{2}-\d{2})[ T](\d{2}:\d{2}:\d{2})(?:\.(\d{1,6}))?"
_NAIVE = re.compile(r"\A" + _WALL + r"\Z", re.ASCII)
_WITH_OFFSET = re.compile(r"\A" + _WALL + r"(Z|[+-]\d{2}:\d{2})\Z", re.ASCII)
_EPOCH_S = re.compile(r"\A\d{9,10}(\.\d+)?\Z", re.ASCII)
_EPOCH_MS = re.compile(r"\A\d{12,13}(\.\d+)?\Z", re.ASCII)


def _wall_clock(day, clock, fraction):
    # strptime is used rather than fromisoformat because Python 3.9 accepts
    # only three or six fractional digits there, and OpenSnitch drops the
    # fraction altogether when the microseconds happen to be zero.
    value = datetime.strptime(f"{day} {clock}", "%Y-%m-%d %H:%M:%S")
    if fraction:
        value = value.replace(microsecond=int(fraction.ljust(6, "0")))
    return value


def _parse_naive_local(text):
    """F1: naive wall-clock text, as str(datetime) writes it.

    It is read as the collector machine's local time, with that zone's own
    rules for the date in question, on the assumption that the firewall GUI
    and the collector share a time zone. The README says so.
    """
    match = _NAIVE.fullmatch(text)
    if not match:
        return None
    try:
        return _wall_clock(*match.groups()).astimezone()
    except (ValueError, OverflowError, OSError):
        return None


def _parse_with_offset(text):
    """F2: ISO 8601 with an explicit offset or Z, which is kept as written."""
    match = _WITH_OFFSET.fullmatch(text)
    if not match:
        return None
    day, clock, fraction, offset = match.groups()
    try:
        value = _wall_clock(day, clock, fraction)
        if offset == "Z":
            zone = timezone.utc
        else:
            sign = -1 if offset[0] == "-" else 1
            zone = timezone(sign * timedelta(hours=int(offset[1:3]),
                                             minutes=int(offset[4:6])))
        return value.replace(tzinfo=zone)
    except (ValueError, OverflowError):
        return None


def _epoch_parser(pattern, scale):
    def parse(text):
        if not pattern.fullmatch(text):
            return None
        try:
            return datetime.fromtimestamp(float(text) / scale, timezone.utc).astimezone()
        except (ValueError, OverflowError, OSError):
            return None
    return parse


# Order matters only for readability: the patterns do not overlap.
TIME_FORMATS = {
    "offset": _parse_with_offset,
    "naive_local": _parse_naive_local,
    "epoch_s": _epoch_parser(_EPOCH_S, 1),
    "epoch_ms": _epoch_parser(_EPOCH_MS, 1000),
}


def classify_time(text):
    """Name the format of one sample time value, or None if unrecognised."""
    text = _text(text)
    for name, parse in TIME_FORMATS.items():
        if parse(text) is not None:
            return name
    return None


def parse_any_time(text, preferred=None):
    text = _text(text)
    names = ([preferred] if preferred else []) + [n for n in TIME_FORMATS if n != preferred]
    for name in names:
        value = TIME_FORMATS[name](text)
        if value is not None:
            return value
    return None


def _window_filter(column, fmt, start, end):
    """A generous SQL prefilter for rows near the window.

    Text formats all begin with YYYY-MM-DD, so comparing against bare dates
    is safe whatever the separator, fraction or offset that follows.
    """
    quoted = f'"{column}"'
    if fmt in ("naive_local", "offset"):
        low = (start.astimezone(timezone.utc) - PREFILTER_MARGIN).strftime("%Y-%m-%d")
        high = (end.astimezone(timezone.utc) + PREFILTER_MARGIN
                + timedelta(days=1)).strftime("%Y-%m-%d")
        return f"{quoted} >= ? AND {quoted} < ?", (low, high)
    scale = 1000 if fmt == "epoch_ms" else 1
    margin = PREFILTER_MARGIN.total_seconds()
    low = (start.timestamp() - margin) * scale
    high = (end.timestamp() + margin) * scale
    return (f"CAST({quoted} AS REAL) >= ? AND CAST({quoted} AS REAL) < ?",
            (low, high))


# ----------------------------------------------------------- field helpers

def _text(value):
    """SQLite is dynamically typed, so a TEXT column can still hold anything."""
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", "replace").strip()
    return str(value).strip()


def _count(value):
    """A non-negative integer from text, or None."""
    text = _text(value)
    if re.fullmatch(r"\d+", text, re.ASCII):
        return int(text)
    return None


_UPTIME = re.compile(r"\A(?:(\d+) days?, )?(\d+):(\d{2}):(\d{2})(?:\.\d+)?\Z", re.ASCII)


def _uptime(value):
    """Seconds from an integer, "H:MM:SS" or "N day(s), H:MM:SS", else None."""
    text = _text(value)
    if re.fullmatch(r"\d+(\.\d+)?", text, re.ASCII):
        return int(float(text))
    match = _UPTIME.fullmatch(text)
    if not match:
        return None
    days, hours, minutes, seconds = match.groups()
    return (int(days or 0) * 86400 + int(hours) * 3600 + int(minutes) * 60
            + int(seconds))


def _flag(value):
    return _text(value).lower() in ("true", "1")


def _node_status(value):
    # The GUI decorates the status with a tick or cross symbol; the word
    # underneath is what the panel needs.
    text = _text(value)
    lowered = text.lower()
    if "offline" in lowered:
        return "offline"
    if "online" in lowered:
        return "online"
    return text or "unknown"


def _plural(n, word):
    return f"{n} {word}" if n == 1 else f"{n} {word}s"


def _names(items):
    return ", ".join(items)


class _Users:
    """uid to account name, looked up once per uid."""

    def __init__(self):
        self.cache = {}

    def name(self, uid):
        if uid is None:
            return None
        if uid not in self.cache:
            try:
                self.cache[uid] = pwd.getpwuid(uid).pw_name
            except (KeyError, OverflowError):
                self.cache[uid] = None
        return self.cache[uid]


# ------------------------------------------------------------ the database

class Reading:
    """What one window of the database yielded."""

    def __init__(self, status, events=(), daemon=None, notes=(), skipped=0):
        self.status = status
        self.events = list(events)
        self.daemon = daemon
        self.notes = list(notes)
        self.skipped = skipped

    @classmethod
    def no_data(cls, reason):
        return cls(schema.STATUS_NO_DATA, notes=[NO_DATA_PREFIX + reason])

    @property
    def note(self):
        return " ".join(self.notes)


def _columns(conn, table):
    # table is always one of this module's constants, never outside input.
    return {row[1].lower() for row in conn.execute(f"PRAGMA table_info({table})")}


def _select_list(wanted, present):
    return ", ".join(f'"{c}"' if c in present else f'NULL AS "{c}"' for c in wanted)


def _is_busy(exc):
    text = str(exc).lower()
    return "locked" in text or "busy" in text


def _error_reason(exc):
    text = str(exc).lower()
    if "not a database" in text:
        return "the statistics database file is not an SQLite database."
    if "unable to open" in text:
        return "the statistics database could not be opened."
    return "the statistics database could not be read."


def _check_db_file(path):
    try:
        info = os.stat(path)
    except FileNotFoundError:
        return "the statistics database was not found."
    except OSError:
        return "the statistics database could not be opened."
    if not stat.S_ISREG(info.st_mode):
        return "the statistics database path is not a regular file."
    return None


def read_window(db_path, start, end, cfg, sleep):
    """Read one window from the database, retrying while it is busy."""
    path = os.path.abspath(db_path)
    reason = _check_db_file(path)
    if reason:
        return Reading.no_data(reason)
    for attempt in range(BUSY_ATTEMPTS):
        try:
            return _read(path, start, end, cfg)
        except sqlite3.Error as exc:
            if not _is_busy(exc):
                return Reading.no_data(_error_reason(exc))
            if attempt + 1 < BUSY_ATTEMPTS:
                sleep(BUSY_BACKOFF_S * (2 ** attempt))
    return Reading.no_data("the statistics database was busy, so this window "
                           "could not be read.")


def _read(path, start, end, cfg):
    # mode=ro and query_only together mean nothing in this process can write,
    # migrate or vacuum the firewall's database. immutable=1 is not used: it
    # would let SQLite ignore the GUI's locks and read a torn page.
    uri = "file:" + urllib.parse.quote(path) + "?mode=ro"
    conn = sqlite3.connect(uri, uri=True, timeout=CONNECT_TIMEOUT_S,
                           isolation_level=None)
    try:
        conn.execute("PRAGMA query_only = ON")
        # Each statement below runs in its own short read transaction and its
        # rows are fetched at once, so the GUI's writer is never held up for
        # longer than one query.
        return _read_tables(conn, start, end, cfg)
    finally:
        conn.close()


def _read_tables(conn, start, end, cfg):
    present = _columns(conn, "connections")
    if not present:
        return Reading.no_data("the statistics database has no connections table.")
    missing = [c for c in CONNECTION_REQUIRED if c not in present]
    if missing:
        return Reading.no_data(f"the connections table lacks the column(s) "
                               f"{_names(missing)}, so this window cannot be read.")
    notes = []
    absent = [c for c in CONNECTION_OPTIONAL_READ if c not in present]
    if absent:
        notes.append(f"The connections table lacks the column(s) {_names(absent)}, "
                     "so those fields are empty in this run.")
    unread = [c for c in CONNECTION_OPTIONAL_UNREAD if c not in present]
    if unread:
        notes.append(f"The connections table lacks the column(s) {_names(unread)}, "
                     "which the collector does not read; nothing in this run "
                     "depends on them.")

    sample = _newest_value(conn, "connections", "time")
    if sample is None:
        return Reading.no_data("no connections were recorded in this window.")
    fmt = classify_time(sample)
    if fmt is None:
        return Reading.no_data("the connections time format was not recognised.")

    where, params = _window_filter("time", fmt, start, end)
    rows = conn.execute(
        f"SELECT {_select_list(CONNECTION_SELECTED, present)} FROM connections "
        f"WHERE {where}", params).fetchall()

    events, nodes, skipped = [], Counter(), Counter()
    users = _Users()
    parse = TIME_FORMATS[fmt]
    for row in rows:
        fields = dict(zip(CONNECTION_SELECTED, row))
        when = parse(_text(fields["time"]))
        if when is None:
            skipped["an unreadable time"] += 1
            continue
        if not start <= when < end:
            continue
        event, problem = _event(fields, when, users)
        if problem:
            skipped[problem] += 1
            continue
        events.append(event)
        node = _text(fields["node"])
        if node:
            nodes[node] += 1

    status = schema.STATUS_PARTIAL if (absent or skipped) else schema.STATUS_OK
    if skipped:
        total = sum(skipped.values())
        detail = ", ".join(f"{n} with {why}" for why, n in sorted(skipped.items()))
        verb = "was" if total == 1 else "were"
        notes.append(f"{_plural(total, 'connection row')} in this window {verb} "
                     f"skipped: {detail}.")
    if not events and not skipped:
        return Reading.no_data("no connections were recorded in this window.")
    if len(nodes) > 1:
        notes.append(f"Connections in this window came from {len(nodes)} firewall "
                     "nodes; the daemon state shown is for the busiest one.")

    chosen = nodes.most_common(1)[0][0] if nodes else None
    daemon, degraded = _daemon_state(conn, chosen, start, end, cfg, fmt, notes)
    if degraded:
        status = schema.STATUS_PARTIAL
    return Reading(status, events, daemon, notes, sum(skipped.values()))


def _newest_value(conn, table, column):
    query = (f'SELECT "{column}" FROM {table} WHERE "{column}" IS NOT NULL '
             f"AND \"{column}\" != '' ORDER BY rowid DESC LIMIT 1")
    try:
        row = conn.execute(query).fetchone()
    except sqlite3.OperationalError as exc:
        # A table declared WITHOUT ROWID has no rowid; any row will do.
        if _is_busy(exc):
            raise
        row = conn.execute(query.replace(" ORDER BY rowid DESC", "")).fetchone()
    return None if row is None else row[0]


def _event(fields, when, users):
    """Map one connections row to an engine event, or name why it cannot be."""
    action = _text(fields["action"]).lower()
    if action == "allow":
        pass
    elif action in ("deny", "reject"):
        action = "deny"
    else:
        return None, "an unrecognised action"
    proto = _text(fields["protocol"]).lower()
    if not proto:
        return None, "no protocol"
    dst_ip = _text(fields["dst_ip"])
    if not dst_ip:
        return None, "no destination address"
    dport = _count(fields["dst_port"])
    if dport is None:
        return None, "an unreadable port"
    uid = _count(fields["uid"])
    return {
        "ts": when.isoformat(timespec="seconds"),
        "action": action,
        "src": _text(fields["src_ip"]),
        "dst_ip": dst_ip,
        "dst_host": _text(fields["dst_host"]) or None,
        "dport": dport,
        "proto": proto,
        "uid": uid,
        "user": users.name(uid),
        "pid": _count(fields["pid"]),
        "process": _text(fields["process"]) or None,
    }, None


# ------------------------------------------------------------ daemon state

def _daemon_state(conn, chosen, start, end, cfg, fmt, notes):
    """The daemon= argument for analysis.build_record, and whether it is partial.

    total_connections and dropped are left out on purpose: the engine then
    counts this window, while node{} carries the daemon's lifetime counters.
    """
    degraded = False
    daemon = {}
    node, node_degraded = _node(conn, chosen, fmt, notes)
    degraded |= node_degraded
    if node is not None:
        daemon["node"] = node
        daemon["daemon_uptime"] = node["daemon_uptime"]
    rules, total, rules_degraded = _rules(conn, chosen, cfg, notes)
    degraded |= rules_degraded
    daemon["rules_detail"] = rules
    daemon["rules"] = total
    sockets, sockets_degraded = _sockets(conn, start, end, notes)
    degraded |= sockets_degraded
    daemon["sockets"] = sockets
    return daemon, degraded


def _node(conn, chosen, fmt, notes):
    present = _columns(conn, "nodes")
    if not present:
        notes.append("The nodes table is absent, so the daemon state is not shown.")
        return None, True
    degraded = False
    missing = [c for c in NODE_COLUMNS if c not in present]
    if missing:
        notes.append(f"The nodes table lacks the column(s) {_names(missing)}, so "
                     "those daemon fields are empty.")
        degraded = True
    select = f"SELECT {_select_list(NODE_COLUMNS, present)} FROM nodes"
    rows = []
    if chosen is not None and "addr" in present:
        rows = conn.execute(select + ' WHERE "addr" = ? LIMIT 2', (chosen,)).fetchall()
    if len(rows) != 1:
        rows = conn.execute(select + " LIMIT 2").fetchall()
    if len(rows) != 1:
        notes.append("No daemon state could be matched to this window's "
                     "connections, so it is not shown.")
        return None, True
    fields = dict(zip(NODE_COLUMNS, rows[0]))

    unreadable = []
    counters = {}
    for name in NODE_COUNTERS:
        value = _count(fields[name])
        if value is None and name in present:
            unreadable.append(name)
        counters[name] = value or 0
    if unreadable:
        notes.append(f"The daemon field(s) {_names(unreadable)} could not be read "
                     "and are shown as zero.")
        degraded = True
    # The GUI can write a date into daemon_uptime when a node subscribes, so
    # an unreadable uptime is routine and is shown as zero without comment.
    uptime = _uptime(fields["daemon_uptime"]) or 0
    last = parse_any_time(fields["last_connection"], fmt)
    return {
        "addr": _text(fields["addr"]),
        "hostname": _text(fields["hostname"]),
        "daemon_version": _text(fields["daemon_version"]),
        "daemon_uptime": uptime,
        "daemon_rules": counters["daemon_rules"],
        "cons": counters["cons"],
        "cons_dropped": counters["cons_dropped"],
        "version": _text(fields["version"]),
        "status": _node_status(fields["status"]),
        "last_connection": last.isoformat(timespec="seconds") if last else "",
    }, degraded


def _rules(conn, chosen, cfg, notes):
    present = _columns(conn, "rules")
    if not present:
        notes.append("The rules table is absent, so the rules panel is empty.")
        return [], 0, True
    degraded = False
    missing = [c for c in RULE_COLUMNS if c not in present]
    if missing:
        notes.append(f"The rules table lacks the column(s) {_names(missing)}, so "
                     "those rule fields are empty.")
        degraded = True
    where, params = "", ()
    if chosen is not None and "node" in present:
        where, params = ' WHERE "node" = ?', (chosen,)
    total = conn.execute(f"SELECT COUNT(*) FROM rules{where}", params).fetchone()[0]
    order = ' ORDER BY "name"' if "name" in present else " ORDER BY rowid"
    rows = conn.execute(
        f"SELECT {_select_list(RULE_COLUMNS, present)} FROM rules{where}{order} "
        "LIMIT ?", params + (cfg["aggregate_cap"],)).fetchall()
    detail = []
    cut = 0
    for row in rows:
        fields = dict(zip(RULE_COLUMNS, row))
        rule = {name: _text(fields[name]) for name in RULE_COLUMNS}
        rule["enabled"] = _flag(fields["enabled"])
        rule["precedence"] = _flag(fields["precedence"])
        rule["operator_data"], was_cut = _cap_operator_data(rule["operator_data"])
        cut += was_cut
        detail.append(rule)
    if cut:
        # Shortening is marked in the field itself and stated here. The run
        # stays ok: the rule is present, only its operand text is shortened.
        notes.append(f"{_plural(cut, 'rule')} had operator data longer than "
                     f"{OPERATOR_DATA_MAX_CHARS} characters, shortened and marked "
                     "as truncated.")
    return detail, int(total), degraded


def _cap_operator_data(text):
    """Cut operator_data to the cap, marking the cut. Returns (text, was_cut)."""
    if len(text) <= OPERATOR_DATA_MAX_CHARS:
        return text, False
    marker = f" [truncated from {len(text)} characters]"
    return text[: OPERATOR_DATA_MAX_CHARS] + marker, True


def _sockets(conn, start, end, notes):
    present = _columns(conn, "sockets")
    missing = [c for c in SOCKET_COLUMNS if c not in present]
    if missing:
        what = "is absent" if not present else f"lacks the column(s) {_names(missing)}"
        notes.append(f"The sockets table {what}, so the sockets panel is empty.")
        return [], True
    # An empty sockets table is normal: the GUI fills it only while its
    # socket view is in use. That is not a gap in this run.
    sample = _newest_value(conn, "sockets", "last_seen")
    fmt = classify_time(sample) if sample is not None else None
    if fmt is None:
        return [], False
    where, params = _window_filter("last_seen", fmt, start, end)
    rows = conn.execute(
        f"SELECT {_select_list(SOCKET_COLUMNS, present)} FROM sockets WHERE {where}",
        params).fetchall()
    hits = Counter()
    for row in rows:
        fields = {name: _text(value) for name, value in zip(SOCKET_COLUMNS, row)}
        seen = TIME_FORMATS[fmt](fields["last_seen"])
        if seen is None or not start <= seen < end:
            continue
        hits[(f"{fields['proto']} {fields['src_ip']}:{fields['src_port']} -> "
              f"{fields['dst_ip']}:{fields['dst_port']}")] += 1
    ranked = sorted(hits.items(), key=lambda kv: (-kv[1], kv[0]))
    return [{"what": what, "hits": n} for what, n in ranked], False


# ----------------------------------------------------------- the run files

def _read_record(path, run_id, cfg):
    """A parsed, schema-valid record, or None for anything else."""
    try:
        info = os.lstat(path)
        if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_RECORD_FILE_BYTES:
            return None
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
        fd = os.open(path, flags)
    except OSError:
        return None
    try:
        with os.fdopen(fd, "rb") as fh:
            if not stat.S_ISREG(os.fstat(fh.fileno()).st_mode):
                return None
            data = fh.read(MAX_RECORD_FILE_BYTES + 1)
    except OSError:
        return None
    if len(data) > MAX_RECORD_FILE_BYTES:
        return None
    try:
        record = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return None
    if not isinstance(record, dict) or record.get("run_id") != run_id:
        return None
    if schema.validate(record, aggregate_cap=cfg["aggregate_cap"],
                       trimmed_cap=cfg["trimmed_max_bytes"]):
        return None
    return record


def load_runs(runs_dir, cfg):
    """Every run file as (run_id, record or None), oldest first."""
    try:
        names = os.listdir(runs_dir)
    except FileNotFoundError:
        return []
    except OSError as exc:
        raise Failed(f"the runs directory could not be listed ({_errno_name(exc)})")
    found = []
    for name in names:
        match = RECORD_FILE.fullmatch(name)
        if not match:
            continue
        run_id = match.group(1)
        if not schema.RUN_ID_PATTERN.fullmatch(run_id):
            continue
        found.append((run_id, _read_record(os.path.join(runs_dir, name), run_id, cfg)))
    found.sort(key=lambda item: item[0])
    return found


def chain_head(runs):
    """The newest record, checked hard enough to seal onto; None when empty.

    An older malformed record only drops out of the baseline, but a bad head
    would make every later link wrong, so it stops the run.
    """
    if not runs:
        return None
    head = runs[-1][1]
    if head is None:
        raise Refused("chain head unreadable")
    if chain.content_digest(head) != head["integrity"]["content_sha256"]:
        raise Refused("chain head does not match its digest")
    index = head["integrity"]["run_index"]
    for run_id, record in runs[:-1]:
        if record is not None and record["integrity"]["run_index"] >= index:
            raise Refused("chain head does not carry the highest run index")
    return head


def check_window(records, start, end):
    for record in records:
        their_start = schema.parse_timestamp(record["window_start"])
        their_end = schema.parse_timestamp(record["window_end"])
        if their_start == start and their_end == end:
            raise Refused("window already collected")
        if start < their_end and their_start < end:
            raise Refused("window overlaps an earlier run")


def _errno_name(exc):
    return errno.errorcode.get(getattr(exc, "errno", None) or -1, type(exc).__name__)


def _fsync_dir(path):
    try:
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    except OSError:
        return
    try:
        os.fsync(fd)
    except OSError:
        # Some filesystems refuse fsync on a directory. The rename has
        # already happened; this only narrows the window for a power cut.
        pass
    finally:
        os.close(fd)


def write_atomic(runs_dir, run_id, record):
    """Write a record so that readers see the old file or the new, never half."""
    data = (json.dumps(record, indent=1, sort_keys=True, ensure_ascii=False)
            + "\n").encode("utf-8")
    fd, tmp = tempfile.mkstemp(dir=runs_dir, prefix=".snitchboard-", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as fh:
            os.fchmod(fh.fileno(), 0o640)
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, os.path.join(runs_dir, run_id + ".json"))
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    _fsync_dir(runs_dir)


def ensure_runs_dir(path):
    """Create the runs directory if needed; never touch one that exists.

    os.mkdir rather than makedirs: a missing parent usually means a mistyped
    path, and creating a tree of directories there would hide the mistake.
    """
    try:
        os.mkdir(path, 0o750)
    except FileExistsError:
        if not os.path.isdir(path):
            raise Refused("the runs directory path is not a directory")
        return
    except OSError as exc:
        raise Refused(f"the runs directory could not be created ({_errno_name(exc)})")
    # mkdir's mode is narrowed by the umask; the group needs read access so
    # that Hermes, running under another account, can read the records.
    os.chmod(path, 0o750)


def acquire_lock(path):
    try:
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o640)
    except FileExistsError:
        raise Refused("lock held")
    except OSError as exc:
        raise Refused(f"the lock could not be taken ({_errno_name(exc)})")
    try:
        os.write(fd, f"{os.getpid()}\n".encode("ascii"))
    finally:
        os.close(fd)


def release_lock(path):
    try:
        os.unlink(path)
    except OSError:
        pass


# ---------------------------------------------------------------- settings

def load_settings(path):
    """Plugin settings from a JSON file, validated by snitchboard.config.

    Only the plugin settings are accepted. Engine thresholds are not settings
    in this release, and the viewer validates every record with the defaults,
    so a record built with other thresholds would show as malformed.
    """
    if path is None:
        return config.load()
    try:
        with open(path, "rb") as fh:
            data = fh.read(MAX_SETTINGS_BYTES + 1)
    except OSError as exc:
        raise UsageError(f"the settings file could not be read ({_errno_name(exc)})")
    if len(data) > MAX_SETTINGS_BYTES:
        raise UsageError("the settings file is too large")
    try:
        settings = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        raise UsageError("the settings file is not valid JSON")
    if not isinstance(settings, dict):
        raise UsageError("the settings file must hold a JSON object")
    unknown = sorted(set(settings) - set(config.PLUGIN_DEFAULTS))
    if unknown:
        raise UsageError(f"unknown setting(s): {', '.join(unknown)}")
    # runs_dir and mode belong to the viewer; the collector takes its
    # directory from --runs-dir and always reads live data.
    picked = {k: v for k, v in settings.items() if k not in ("runs_dir", "mode")}
    try:
        return config.load(picked)
    except ValueError as exc:
        # config's messages name settings and bounds, never values.
        raise UsageError(f"invalid settings: {exc}")


# --------------------------------------------------------------- the run

class _Parser(argparse.ArgumentParser):
    def error(self, message):
        # argparse echoes stray arguments back, and a stray argument is often
        # a path, so that one message is shortened.
        if message.startswith("unrecognized arguments"):
            message = "unrecognised arguments"
        self.print_usage(sys.stderr)
        self.exit(2, f"{self.prog}: error: {message}\n")


def _window_end_arg(text):
    try:
        value = schema.parse_timestamp(text)
    except ValueError:
        raise argparse.ArgumentTypeError("must be an ISO 8601 timestamp with an offset")
    return value


def build_parser():
    parser = _Parser(prog="snitchboard_collect.py",
                     description=__doc__.splitlines()[0])
    parser.add_argument("--db", required=True,
                        help="the OpenSnitch statistics database (no default)")
    parser.add_argument("--runs-dir", required=True,
                        help="directory the run records are written to")
    parser.add_argument("--window-end", type=_window_end_arg,
                        help="end of the one-hour window, ISO 8601 with an offset "
                             "(default: the top of the current hour)")
    parser.add_argument("--settings",
                        help="JSON file of plugin settings (retention_days and so on)")
    parser.add_argument("--dry-run", action="store_true",
                        help="analyse and report, but write nothing")
    parser.add_argument("--quiet", action="store_true",
                        help="print nothing unless something goes wrong")
    return parser


def _fixed_offset(moment):
    """Pin an aware datetime to its current offset.

    Arithmetic on a datetime with a zone-rule tzinfo is wall-clock arithmetic,
    so an hour subtracted across a DST change would not be an hour.
    """
    if moment.tzinfo is None:
        moment = moment.astimezone()
    return moment.astimezone(timezone(moment.utcoffset()))


def run(args, now, sleep, say):
    cfg = load_settings(args.settings)
    if args.window_end is not None:
        window_end = _fixed_offset(args.window_end).replace(microsecond=0)
    else:
        window_end = now.replace(minute=0, second=0, microsecond=0)
    if window_end > now:
        raise Refused("window end is in the future")
    window_start = window_end - WINDOW
    runs_dir = os.path.abspath(args.runs_dir)

    if args.dry_run:
        return collect(args, cfg, runs_dir, window_start, window_end, now, sleep, say)
    ensure_runs_dir(runs_dir)
    lock = os.path.join(runs_dir, LOCK_NAME)
    acquire_lock(lock)
    try:
        return collect(args, cfg, runs_dir, window_start, window_end, now, sleep, say)
    finally:
        release_lock(lock)


def collect(args, cfg, runs_dir, window_start, window_end, now, sleep, say):
    runs = load_runs(runs_dir, cfg)
    head = chain_head(runs)
    prior = [record for _, record in runs if record is not None]
    check_window(prior, window_start, window_end)

    started_at = now.isoformat(timespec="seconds")
    run_id = schema.run_id_for(started_at)
    if head is not None and run_id <= head["run_id"]:
        raise Refused("clock is behind the newest record")
    if os.path.lexists(os.path.join(runs_dir, run_id + ".json")):
        raise Refused("a record with this run id already exists")

    reading = read_window(args.db, window_start, window_end, cfg, sleep)
    record = analysis.build_record(
        reading.events,
        started_at=started_at,
        window_start=window_start.isoformat(timespec="seconds"),
        window_end=window_end.isoformat(timespec="seconds"),
        status=reading.status,
        prior_records=prior,
        cfg=cfg,
        daemon=reading.daemon if reading.status != schema.STATUS_NO_DATA else None,
        note=reading.note,
    )
    sealed = chain.seal(record, head)
    problems = schema.validate(sealed, aggregate_cap=cfg["aggregate_cap"],
                               trimmed_cap=cfg["trimmed_max_bytes"])
    if problems:
        raise Failed(f"the new record failed validation "
                     f"({_plural(len(problems), 'problem')})")

    cutoff = now - timedelta(days=cfg["retention_days"])
    due = [r for r in prior if not r["trimmed"]
           and schema.parse_timestamp(r["window_end"]) < cutoff]

    summary = (f"{run_id} status={sealed['status']} "
               f"connections={sealed['totals']['connections']} "
               f"destinations={sealed['totals']['unique_destinations']} "
               f"detections={len(sealed['detections'])}")
    if reading.skipped:
        summary += f" skipped={reading.skipped}"

    if args.dry_run:
        say("dry run: nothing written")
        say(summary)
        _say_note(say, sealed)
        say(f"would_trim={len(due)}")
        return 0

    try:
        write_atomic(runs_dir, run_id, sealed)
    except OSError as exc:
        raise Failed(f"the record could not be written ({_errno_name(exc)})")
    say(summary)
    _say_note(say, sealed)

    trimmed, failures = 0, 0
    for record in due:
        if trim_one(runs_dir, record, cfg):
            trimmed += 1
        else:
            failures += 1
            print(f"trim failed: {record['run_id']}", file=sys.stderr)
    if trimmed:
        say(f"trimmed={trimmed}")
    return 1 if failures else 0


def _say_note(say, record):
    # Notes are composed in this module from fixed text, counts and column
    # names, so they are safe to print; they explain a partial or empty run.
    if record["status"] != schema.STATUS_OK and record["note"]:
        say(f"note: {record['note']}")


def trim_one(runs_dir, record, cfg):
    """Trim one aged full record in place. False means it was left untouched.

    A record whose destinations do not fit the cap is left full (D9): the
    failure is loud rather than a quietly shortened destination list, which
    would corrupt novelty scoring with no sign that it had happened.
    """
    try:
        trimmed = chain.trim(record, max_bytes=cfg["trimmed_max_bytes"])
    except ValueError:
        return False
    if schema.validate(trimmed, aggregate_cap=cfg["aggregate_cap"],
                       trimmed_cap=cfg["trimmed_max_bytes"]):
        return False
    try:
        write_atomic(runs_dir, record["run_id"], trimmed)
    except OSError:
        return False
    return True


def _on_sigterm(signum, frame):
    # SystemExit unwinds through every finally block, so the lock file and
    # any half-written temporary file are removed when systemd stops us.
    raise SystemExit(128 + signum)


def main(argv=None, *, now=None, sleep=time.sleep):
    try:
        args = build_parser().parse_args(argv)
    except SystemExit as exc:
        return exc.code if isinstance(exc.code, int) else 2

    now = _fixed_offset(now if now is not None else datetime.now().astimezone())
    out = None if args.quiet else sys.stdout

    def say(line):
        if out is not None:
            print(line, file=out)

    installed, previous = False, None
    try:
        previous = signal.signal(signal.SIGTERM, _on_sigterm)
        installed = True
    except ValueError:
        # Only the main thread may set handlers; a caller in another thread
        # keeps its own SIGTERM behaviour.
        pass
    try:
        return run(args, now, sleep, say)
    except UsageError as exc:
        print(f"usage error: {exc}", file=sys.stderr)
        return 2
    except Refused as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 1
    except Failed as exc:
        print(f"failed: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:
        # The text of an unexpected exception can carry a path or an address
        # from the data, so only its class is reported.
        print(f"failed: unexpected {type(exc).__name__}", file=sys.stderr)
        return 1
    finally:
        if installed:
            signal.signal(signal.SIGTERM, previous if previous is not None
                          else signal.SIG_DFL)


if __name__ == "__main__":
    sys.exit(main())
