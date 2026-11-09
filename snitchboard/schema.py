"""Run record schema, version 1 (HSB-PRD-001 section 7.3).

validate() is deliberately strict: it rejects unknown fields as well as
missing ones, because section 5.1 records what happens when record shape is
allowed to drift.
"""

import re
from datetime import datetime, timezone

from . import attack
from .canonical import canonical_bytes

SCHEMA_VERSION = 1

STATUS_OK = "ok"
STATUS_PARTIAL = "partial"
STATUS_NO_DATA = "no_data"
STATUSES = (STATUS_OK, STATUS_PARTIAL, STATUS_NO_DATA)

# The reference implementation wrote this value; it is accepted on input only.
LEGACY_STATUS = {"collection_unavailable": STATUS_NO_DATA}

HIGH = "high"
MEDIUM = "medium"
LOW = "low"
SEVERITIES = (HIGH, MEDIUM, LOW)
CONFIDENCES = (HIGH, MEDIUM, LOW)
SEVERITY_RANK = {HIGH: 0, MEDIUM: 1, LOW: 2}

ACTIONS = ("allow", "deny")

CAPS = {
    "rows": 120,
    "volume_rows": 45,
    "hosts": 20,
    "addrs": 15,
    "novel": 15,
    "beacons": 16,
    "coverage_slots": 24,
    "full_bytes": 200 * 1024,
    "trimmed_bytes": 8 * 1024,
}

GENESIS_SHA256 = "0" * 64

# A run identifier is derived from the UTC instant of started_at. The suffix
# Z is truthful because the instant is converted, not relabelled.
RUN_ID_PATTERN = re.compile(r"^run-\d{8}T\d{6}Z$")

_TIMESTAMP = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d{1,6})?(Z|[+-]\d{2}:\d{2})$"
)
_SHA256 = re.compile(r"^[0-9a-f]{64}$")

COMMON_FIELDS = (
    "schema_version", "run_id", "started_at", "window_start", "window_end",
    "status", "trimmed", "note", "coverage", "totals", "integrity",
)
# `destinations` appears in both forms. Section 7.3 lists it for the trimmed
# form only, but a full record's rows and host list are capped, so without it
# novelty cannot be computed against a full prior record either.
FULL_FIELDS = COMMON_FIELDS + (
    "detections", "beacons", "novel", "agents", "volume", "rows",
    "aggregates", "destinations",
)
TRIMMED_FIELDS = COMMON_FIELDS + ("detections", "destinations")

TOTALS_FIELDS = (
    "connections", "allowed", "denied", "unique_processes",
    "unique_destinations", "ai_connections", "unattributed",
    "novel_destinations", "beacon_candidates", "agents_active",
)
DETECTION_FIELDS = (
    "title", "severity", "confidence", "attack", "detail", "evidence",
    "recommendation",
)
ATTACK_FIELDS = ("technique", "technique_id", "tactic", "tactic_id")
BEACON_FIELDS = (
    "process", "destination", "count", "mean_interval", "jitter_pct",
    "confidence", "assessment",
)
NOVEL_FIELDS = (
    "destination", "rarity", "contacts", "processes", "prior_runs_seen",
    "baseline_note",
)
AGENT_FIELDS = (
    "process", "pid", "user", "connections", "ports", "destinations",
    "privilege_note", "verdict",
)
VOLUME_FIELDS = ("available", "note", "rows")
VOLUME_ROW_FIELDS = (
    "process", "destination", "sent_bytes", "recv_bytes", "flows",
    "assessment",
)
ROW_FIELDS = (
    "ts", "action", "src", "dst", "dport", "proto", "uid", "pid", "process",
    "activity", "is_ai", "severity",
)
AGGREGATE_FIELDS = (
    "daemon_uptime", "total_connections", "dropped", "rules", "procs",
    "hosts", "users", "ports", "addrs", "node", "rules_detail", "sockets",
)
AGGREGATE_LISTS = ("procs", "hosts", "users", "ports", "addrs", "sockets")
NODE_FIELDS = (
    "addr", "hostname", "daemon_version", "daemon_uptime", "daemon_rules",
    "cons", "cons_dropped", "version", "status", "last_connection",
)
RULE_FIELDS = (
    "name", "enabled", "precedence", "action", "duration", "operator_type",
    "operator_operand", "operator_data", "created",
)
COVERAGE_FIELDS = ("title", "from", "to", "slots")
SLOT_FIELDS = ("label", "covered")
INTEGRITY_FULL_FIELDS = ("content_sha256", "prev_sha256", "run_index")
INTEGRITY_TRIMMED_FIELDS = INTEGRITY_FULL_FIELDS + ("sealed_sha256",)


def normalise_status(value):
    """Map a legacy status onto the version 1 set; leave others untouched."""
    return LEGACY_STATUS.get(value, value)


def parse_timestamp(value):
    """Parse an ISO 8601 timestamp that must carry an explicit offset.

    A naive timestamp is rejected rather than assumed to be UTC, because
    assuming would relabel a local time.
    """
    if not isinstance(value, str) or not _TIMESTAMP.match(value):
        raise ValueError(f"not an ISO 8601 timestamp with an offset: {value!r}")
    text = value[:-1] + "+00:00" if value.endswith("Z") else value
    parsed = datetime.fromisoformat(text)
    if parsed.utcoffset() is None:
        raise ValueError(f"timestamp has no offset: {value!r}")
    return parsed


def run_id_for(started_at):
    """Derive the run identifier from a started_at timestamp."""
    instant = parse_timestamp(started_at).astimezone(timezone.utc)
    return "run-" + instant.strftime("%Y%m%dT%H%M%SZ")


def is_int(value):
    return isinstance(value, int) and not isinstance(value, bool)


def is_number(value):
    return (isinstance(value, (int, float)) and not isinstance(value, bool))


class _Checker:
    def __init__(self):
        self.problems = []

    def fail(self, path, message):
        self.problems.append(f"{path}: {message}")

    def obj(self, value, path, fields):
        """Check an object has exactly `fields`. Returns False if unusable."""
        if not isinstance(value, dict):
            self.fail(path, f"expected an object, found {type(value).__name__}")
            return False
        for name in fields:
            if name not in value:
                self.fail(path, f"missing mandatory field '{name}'")
        for name in sorted(set(value) - set(fields)):
            self.fail(path, f"unexpected field '{name}'")
        return True

    def string(self, value, path, allow_empty=True, allow_none=False):
        if value is None and allow_none:
            return
        if not isinstance(value, str):
            self.fail(path, f"expected a string, found {type(value).__name__}")
        elif not allow_empty and not value.strip():
            self.fail(path, "must not be empty")

    def integer(self, value, path, minimum=None, allow_none=False):
        if value is None and allow_none:
            return
        if not is_int(value):
            self.fail(path, f"expected an integer, found {type(value).__name__}")
        elif minimum is not None and value < minimum:
            self.fail(path, f"must be at least {minimum}, found {value}")

    def number(self, value, path, minimum=None):
        if not is_number(value):
            self.fail(path, f"expected a number, found {type(value).__name__}")
        elif minimum is not None and value < minimum:
            self.fail(path, f"must be at least {minimum}, found {value}")

    def boolean(self, value, path):
        if not isinstance(value, bool):
            self.fail(path, f"expected true or false, found {type(value).__name__}")

    def choice(self, value, path, options):
        if value not in options:
            self.fail(path, f"must be one of {', '.join(options)}, found {value!r}")

    def timestamp(self, value, path):
        try:
            parse_timestamp(value)
        except ValueError as exc:
            self.fail(path, str(exc))

    def sha(self, value, path):
        if not isinstance(value, str) or not _SHA256.match(value):
            self.fail(path, "expected 64 lowercase hexadecimal characters")

    def str_list(self, value, path, cap=None, sorted_unique=False):
        if not isinstance(value, list):
            self.fail(path, f"expected a list, found {type(value).__name__}")
            return
        for i, item in enumerate(value):
            self.string(item, f"{path}[{i}]")
        if cap is not None and len(value) > cap:
            self.fail(path, f"holds {len(value)} entries, above the cap of {cap}")
        if sorted_unique and all(isinstance(v, str) for v in value):
            if value != sorted(set(value)):
                self.fail(path, "must be sorted and free of duplicates")

    def int_list(self, value, path):
        if not isinstance(value, list):
            self.fail(path, f"expected a list, found {type(value).__name__}")
            return
        for i, item in enumerate(value):
            self.integer(item, f"{path}[{i}]", minimum=0)

    def items(self, value, path, cap=None):
        """Yield (index, item, item_path) for a list, reporting shape faults."""
        if not isinstance(value, list):
            self.fail(path, f"expected a list, found {type(value).__name__}")
            return
        if cap is not None and len(value) > cap:
            self.fail(path, f"holds {len(value)} entries, above the cap of {cap}")
        for i, item in enumerate(value):
            yield i, item, f"{path}[{i}]"


def _check_detection(c, det, path):
    if not c.obj(det, path, DETECTION_FIELDS):
        return
    c.string(det.get("title"), f"{path}.title", allow_empty=False)
    c.choice(det.get("severity"), f"{path}.severity", SEVERITIES)
    c.choice(det.get("confidence"), f"{path}.confidence", CONFIDENCES)
    c.string(det.get("detail"), f"{path}.detail", allow_empty=False)
    c.string(det.get("recommendation"), f"{path}.recommendation", allow_empty=False)
    evidence = det.get("evidence")
    c.str_list(evidence, f"{path}.evidence")
    if isinstance(evidence, list) and not evidence:
        c.fail(f"{path}.evidence", "must hold at least one observed record")
    block = det.get("attack")
    if c.obj(block, f"{path}.attack", ATTACK_FIELDS):
        for name in ATTACK_FIELDS:
            c.string(block.get(name), f"{path}.attack.{name}")
        if not attack.is_permitted(block):
            c.fail(f"{path}.attack",
                   f"technique {block.get('technique_id')!r} with tactic "
                   f"{block.get('tactic_id')!r} is not in the permitted table")


def _check_coverage(c, cov, path):
    if not c.obj(cov, path, COVERAGE_FIELDS):
        return
    c.string(cov.get("title"), f"{path}.title")
    c.timestamp(cov.get("from"), f"{path}.from")
    c.timestamp(cov.get("to"), f"{path}.to")
    slots = list(c.items(cov.get("slots"), f"{path}.slots"))
    if isinstance(cov.get("slots"), list) and len(slots) != CAPS["coverage_slots"]:
        c.fail(f"{path}.slots",
               f"must hold exactly {CAPS['coverage_slots']} slots, found {len(slots)}")
    for _, slot, spath in slots:
        if c.obj(slot, spath, SLOT_FIELDS):
            c.string(slot.get("label"), f"{spath}.label", allow_empty=False)
            c.boolean(slot.get("covered"), f"{spath}.covered")


def _check_totals(c, totals, path):
    if c.obj(totals, path, TOTALS_FIELDS):
        for name in TOTALS_FIELDS:
            c.integer(totals.get(name), f"{path}.{name}", minimum=0)


def _check_integrity(c, block, path, trimmed):
    fields = INTEGRITY_TRIMMED_FIELDS if trimmed else INTEGRITY_FULL_FIELDS
    if not c.obj(block, path, fields):
        return
    c.sha(block.get("content_sha256"), f"{path}.content_sha256")
    c.sha(block.get("prev_sha256"), f"{path}.prev_sha256")
    c.integer(block.get("run_index"), f"{path}.run_index", minimum=0)
    if trimmed:
        c.sha(block.get("sealed_sha256"), f"{path}.sealed_sha256")


def _check_beacon(c, b, path):
    if not c.obj(b, path, BEACON_FIELDS):
        return
    c.string(b.get("process"), f"{path}.process", allow_empty=False)
    c.string(b.get("destination"), f"{path}.destination", allow_empty=False)
    c.integer(b.get("count"), f"{path}.count", minimum=0)
    c.number(b.get("mean_interval"), f"{path}.mean_interval", minimum=0)
    c.number(b.get("jitter_pct"), f"{path}.jitter_pct", minimum=0)
    c.choice(b.get("confidence"), f"{path}.confidence", CONFIDENCES)
    c.string(b.get("assessment"), f"{path}.assessment", allow_empty=False)


def _check_novel(c, n, path):
    if not c.obj(n, path, NOVEL_FIELDS):
        return
    c.string(n.get("destination"), f"{path}.destination", allow_empty=False)
    c.integer(n.get("rarity"), f"{path}.rarity", minimum=0)
    if is_int(n.get("rarity")) and n["rarity"] > 100:
        c.fail(f"{path}.rarity", f"must be at most 100, found {n['rarity']}")
    c.integer(n.get("contacts"), f"{path}.contacts", minimum=0)
    c.str_list(n.get("processes"), f"{path}.processes")
    c.integer(n.get("prior_runs_seen"), f"{path}.prior_runs_seen", minimum=0)
    c.string(n.get("baseline_note"), f"{path}.baseline_note", allow_empty=False)


def _check_agent(c, a, path):
    if not c.obj(a, path, AGENT_FIELDS):
        return
    c.string(a.get("process"), f"{path}.process")
    c.integer(a.get("pid"), f"{path}.pid", minimum=0, allow_none=True)
    c.string(a.get("user"), f"{path}.user")
    c.integer(a.get("connections"), f"{path}.connections", minimum=0)
    c.int_list(a.get("ports"), f"{path}.ports")
    c.str_list(a.get("destinations"), f"{path}.destinations")
    c.string(a.get("privilege_note"), f"{path}.privilege_note", allow_empty=False)
    c.string(a.get("verdict"), f"{path}.verdict", allow_empty=False)


def _check_volume(c, vol, path):
    if not c.obj(vol, path, VOLUME_FIELDS):
        return
    c.boolean(vol.get("available"), f"{path}.available")
    c.string(vol.get("note"), f"{path}.note")
    rows = list(c.items(vol.get("rows"), f"{path}.rows", CAPS["volume_rows"]))
    if vol.get("available") is False and rows:
        c.fail(f"{path}.rows", "must be empty when volume is unavailable")
    for _, row, rpath in rows:
        if c.obj(row, rpath, VOLUME_ROW_FIELDS):
            c.string(row.get("process"), f"{rpath}.process")
            c.string(row.get("destination"), f"{rpath}.destination", allow_empty=False)
            c.integer(row.get("sent_bytes"), f"{rpath}.sent_bytes", minimum=0)
            c.integer(row.get("recv_bytes"), f"{rpath}.recv_bytes", minimum=0)
            c.integer(row.get("flows"), f"{rpath}.flows", minimum=0)
            c.string(row.get("assessment"), f"{rpath}.assessment", allow_empty=False)


def _check_row(c, row, path):
    if not c.obj(row, path, ROW_FIELDS):
        return
    c.timestamp(row.get("ts"), f"{path}.ts")
    c.choice(row.get("action"), f"{path}.action", ACTIONS)
    c.string(row.get("src"), f"{path}.src")
    c.string(row.get("dst"), f"{path}.dst", allow_empty=False)
    c.integer(row.get("dport"), f"{path}.dport", minimum=0)
    c.string(row.get("proto"), f"{path}.proto", allow_empty=False)
    c.integer(row.get("uid"), f"{path}.uid", minimum=0, allow_none=True)
    c.integer(row.get("pid"), f"{path}.pid", minimum=0, allow_none=True)
    c.string(row.get("process"), f"{path}.process", allow_none=True)
    c.string(row.get("activity"), f"{path}.activity", allow_empty=False)
    c.boolean(row.get("is_ai"), f"{path}.is_ai")
    c.choice(row.get("severity"), f"{path}.severity", SEVERITIES)


def _check_aggregates(c, agg, path, aggregate_cap):
    if not c.obj(agg, path, AGGREGATE_FIELDS):
        return
    for name in ("daemon_uptime", "total_connections", "dropped", "rules"):
        c.integer(agg.get(name), f"{path}.{name}", minimum=0)
    caps = {"hosts": CAPS["hosts"], "addrs": CAPS["addrs"]}
    for name in AGGREGATE_LISTS:
        cap = caps.get(name, aggregate_cap)
        for _, item, ipath in c.items(agg.get(name), f"{path}.{name}", cap):
            if c.obj(item, ipath, ("what", "hits")):
                c.string(item.get("what"), f"{ipath}.what", allow_empty=False)
                c.integer(item.get("hits"), f"{ipath}.hits", minimum=0)
    node = agg.get("node")
    if c.obj(node, f"{path}.node", NODE_FIELDS):
        for name in ("addr", "hostname", "daemon_version", "version", "status"):
            c.string(node.get(name), f"{path}.node.{name}")
        for name in ("daemon_uptime", "daemon_rules", "cons", "cons_dropped"):
            c.integer(node.get(name), f"{path}.node.{name}", minimum=0)
        if node.get("last_connection"):
            c.timestamp(node.get("last_connection"), f"{path}.node.last_connection")
        else:
            c.string(node.get("last_connection"), f"{path}.node.last_connection")
    for _, rule, rpath in c.items(agg.get("rules_detail"), f"{path}.rules_detail"):
        if c.obj(rule, rpath, RULE_FIELDS):
            for name in RULE_FIELDS:
                if name in ("enabled", "precedence"):
                    c.boolean(rule.get(name), f"{rpath}.{name}")
                else:
                    c.string(rule.get(name), f"{rpath}.{name}")


def validate(record, aggregate_cap=20):
    """Return a list of human-readable problems; an empty list means valid."""
    c = _Checker()
    if not isinstance(record, dict):
        c.fail("record", f"expected an object, found {type(record).__name__}")
        return c.problems
    trimmed = record.get("trimmed")
    if not isinstance(trimmed, bool):
        c.fail("record.trimmed", "missing or not true/false, so the form is unknown")
        return c.problems
    form = "trimmed" if trimmed else "full"
    c.obj(record, f"record ({form} form)", TRIMMED_FIELDS if trimmed else FULL_FIELDS)

    if record.get("schema_version") != SCHEMA_VERSION:
        c.fail("record.schema_version",
               f"expected {SCHEMA_VERSION}, found {record.get('schema_version')!r}")
    run_id = record.get("run_id")
    if not isinstance(run_id, str) or not RUN_ID_PATTERN.match(run_id):
        c.fail("record.run_id", f"does not match the run identifier pattern: {run_id!r}")
    for name in ("started_at", "window_start", "window_end"):
        c.timestamp(record.get(name), f"record.{name}")
    if isinstance(run_id, str) and "started_at" in record:
        try:
            if run_id_for(record["started_at"]) != run_id:
                c.fail("record.run_id", "does not correspond to started_at")
        except ValueError:
            pass
    c.choice(record.get("status"), "record.status", STATUSES)
    c.string(record.get("note"), "record.note")
    if "coverage" in record:
        _check_coverage(c, record["coverage"], "record.coverage")
    if "totals" in record:
        _check_totals(c, record["totals"], "record.totals")
    if "integrity" in record:
        _check_integrity(c, record["integrity"], "record.integrity", trimmed)
    for _, det, path in c.items(record.get("detections", []), "record.detections"):
        _check_detection(c, det, path)
    c.str_list(record.get("destinations", []), "record.destinations",
               sorted_unique=True)

    if not trimmed:
        for _, b, path in c.items(record.get("beacons", []), "record.beacons",
                                  CAPS["beacons"]):
            _check_beacon(c, b, path)
        for _, n, path in c.items(record.get("novel", []), "record.novel",
                                  CAPS["novel"]):
            _check_novel(c, n, path)
        for _, a, path in c.items(record.get("agents", []), "record.agents"):
            _check_agent(c, a, path)
        if "volume" in record:
            _check_volume(c, record["volume"], "record.volume")
        for _, row, path in c.items(record.get("rows", []), "record.rows",
                                    CAPS["rows"]):
            _check_row(c, row, path)
        if "aggregates" in record:
            _check_aggregates(c, record["aggregates"], "record.aggregates",
                              aggregate_cap)

    try:
        size = len(canonical_bytes(record))
    except (TypeError, ValueError) as exc:
        c.fail("record", f"cannot be serialised canonically: {exc}")
    else:
        cap = CAPS["trimmed_bytes"] if trimmed else CAPS["full_bytes"]
        if size > cap:
            c.fail("record", f"{form} record is {size} bytes, above the cap of {cap}")
    return c.problems
