"""Analysis engine (HSB-PRD-001 section 7.4).

The engine works on connection events, not on run records: a record's rows
are capped at 120, which is too few for beaconing or novelty. build_record()
turns one window of events into an unsealed full record.

An event is a dict with: ts, action, src, dst_ip, dst_host (or None), dport,
proto, uid, user, pid, process (None when unattributed) and, where measured,
sent_bytes, recv_bytes and paired (False for a flow that opened before the
window and could not be matched to its start).
"""

import statistics
from collections import Counter, defaultdict
from datetime import timedelta

from . import detect, severity
from .schema import (
    CAPS, HIGH, LOW, MEDIUM, SCHEMA_VERSION, SEVERITY_RANK, STATUS_NO_DATA,
    STATUS_OK, STATUSES, parse_timestamp, run_id_for,
)

_EVENT_REQUIRED = ("ts", "action", "dst_ip", "dport", "proto")


def normalise_event(raw):
    """Fill optional event fields and derive the destination key."""
    for name in _EVENT_REQUIRED:
        if name not in raw:
            raise ValueError(f"event is missing '{name}': {raw!r}")
    parse_timestamp(raw["ts"])
    if raw["action"] not in ("allow", "deny"):
        raise ValueError(f"event action must be allow or deny: {raw['action']!r}")
    event = {
        "ts": raw["ts"],
        "action": raw["action"],
        "src": raw.get("src", ""),
        "dst_ip": raw["dst_ip"],
        "dst_host": raw.get("dst_host") or None,
        "dport": int(raw["dport"]),
        "proto": raw["proto"],
        "uid": raw.get("uid"),
        "user": raw.get("user"),
        "pid": raw.get("pid"),
        "process": raw.get("process") or None,
        "sent_bytes": raw.get("sent_bytes"),
        "recv_bytes": raw.get("recv_bytes"),
        "paired": raw.get("paired", True),
    }
    event["destination"] = event["dst_host"] or event["dst_ip"]
    return event


def process_label(event):
    return event["process"] or detect.UNATTRIBUTED_LABEL


def user_label(event):
    if event.get("user"):
        return event["user"]
    return f"uid {event['uid']}" if event.get("uid") is not None else "unknown account"


# ---------------------------------------------------------------- coverage

def coverage(runs, end, cfg):
    """Hourly coverage for the `coverage_hours` ending at `end`.

    A slot is covered only when runs with status ok cover the whole hour,
    allowing `coverage_tolerance_s` for timer drift. Runs of any other status
    contribute nothing: absence of collection is not an all-clear.
    """
    end_dt = parse_timestamp(end)
    hours = cfg["coverage_hours"]
    tolerance = cfg["coverage_tolerance_s"]
    windows = []
    for run in runs:
        if run.get("status") != STATUS_OK:
            continue
        windows.append((parse_timestamp(run["window_start"]),
                        parse_timestamp(run["window_end"])))
    slots = []
    for k in range(hours):
        start = end_dt - timedelta(hours=hours - k)
        stop = start + timedelta(hours=1)
        clipped = sorted((max(a, start), min(b, stop)) for a, b in windows
                         if a < stop and b > start)
        covered_s = 0.0
        cursor = start
        for a, b in clipped:
            a = max(a, cursor)
            if b > a:
                covered_s += (b - a).total_seconds()
                cursor = b
        slots.append({
            "label": start.strftime("%H:%M"),
            "covered": covered_s >= 3600 - tolerance,
        })
    return {
        "title": f"Collection coverage, last {hours} hours",
        "from": (end_dt - timedelta(hours=hours)).isoformat(),
        "to": end_dt.isoformat(),
        "slots": slots,
    }


# ----------------------------------------------------------------- novelty

def baseline_from(prior_records, cfg):
    """The prior runs, up to `novelty_max_prior`, that carry collected data.

    Runs with status no_data are excluded from the denominator: a run that
    collected nothing is not evidence that a destination was absent.
    """
    ordered = sorted(prior_records, key=lambda r: parse_timestamp(r["started_at"]))
    recent = ordered[-cfg["novelty_max_prior"]:] if cfg["novelty_max_prior"] else []
    return [set(r["destinations"]) for r in recent if r["status"] != STATUS_NO_DATA]


def rarity(seen, baseline_runs):
    """100 when never seen, 0 when seen in every prior run, rounded half up."""
    if baseline_runs == 0:
        return 100
    return (200 * (baseline_runs - seen) + baseline_runs) // (2 * baseline_runs)


def novelty(events, baseline, cfg):
    contacts = Counter(e["destination"] for e in events)
    processes = defaultdict(set)
    for e in events:
        processes[e["destination"]].add(process_label(e))
    n = len(baseline)
    entries = []
    for dest, count in contacts.items():
        seen = sum(1 for run in baseline if dest in run)
        entries.append({
            "destination": dest,
            "rarity": rarity(seen, n),
            "contacts": count,
            "processes": sorted(processes[dest]),
            "prior_runs_seen": seen,
            "baseline_note": detect.baseline_note(dest, seen, n),
        })
    entries.sort(key=lambda x: (-x["rarity"], -x["contacts"], x["destination"]))
    return entries[: cfg["novelty_top"]]


# --------------------------------------------------------------- beaconing

def jitter_confidence(jitter_pct, cfg):
    if jitter_pct < cfg["beacon_high_below_pct"]:
        return HIGH
    if jitter_pct < cfg["beacon_medium_below_pct"]:
        return MEDIUM
    return LOW


def interval_stats(timestamps):
    """Mean interval in seconds and jitter as a coefficient of variation in %.

    Population standard deviation is used: the intervals are the whole of
    what was observed, not a sample drawn from a larger set.
    """
    ordered = sorted(parse_timestamp(t) for t in timestamps)
    gaps = [(b - a).total_seconds() for a, b in zip(ordered, ordered[1:])]
    mean = statistics.fmean(gaps)
    if mean == 0:
        return 0.0, 0.0
    return mean, statistics.pstdev(gaps) / mean * 100


def beaconing(events, cfg):
    """Regular-interval process and destination pairs, ordered by jitter.

    Mean and jitter are rounded to one decimal place before the thresholds
    are applied, so the stored figures and the stored confidence always agree.
    """
    pairs = defaultdict(list)
    for e in events:
        if e["dport"] in cfg["beacon_excluded_ports"]:
            continue
        pairs[(process_label(e), e["destination"])].append(e)
    found = []
    for (proc, dest), group in pairs.items():
        if len(group) < cfg["beacon_min_contacts"]:
            continue
        mean, jitter = interval_stats([e["ts"] for e in group])
        mean, jitter = round(mean, 1), round(jitter, 1)
        if not cfg["beacon_min_mean_s"] <= mean <= cfg["beacon_max_mean_s"]:
            continue
        if jitter >= cfg["beacon_max_jitter_pct"]:
            continue
        expected = (severity.matches(severity.process_name(proc), cfg["expected_services"])
                    or severity.matches(proc, cfg["expected_services"])
                    or severity.matches(dest, cfg["expected_services"]))
        confidence = jitter_confidence(jitter, cfg)
        found.append({
            "process": proc,
            "destination": dest,
            "count": len(group),
            "mean_interval": mean,
            "jitter_pct": jitter,
            "confidence": confidence,
            "assessment": detect.beacon_assessment(proc, dest, len(group), mean,
                                                   jitter, expected),
            "expected": expected,
            "events": sorted(group, key=lambda e: parse_timestamp(e["ts"])),
            "dport": group[0]["dport"],
        })
    found.sort(key=lambda b: (b["jitter_pct"], b["process"], b["destination"]))
    return found[: CAPS["beacons"]]


# ------------------------------------------------------------------ volume

def volume(events, cfg):
    """Measured byte counts only. Nothing is ever estimated."""
    measured = [e for e in events
                if isinstance(e["sent_bytes"], int) and isinstance(e["recv_bytes"], int)]
    if not measured:
        return {
            "available": False,
            "note": ("Volume unavailable: this window carries no measured byte "
                     "counts, and no figure is estimated in their place."),
            "rows": [],
        }, []
    groups = {}
    for e in measured:
        key = (process_label(e), e["destination"])
        g = groups.setdefault(key, {
            "process": key[0], "destination": key[1], "sent_bytes": 0,
            "recv_bytes": 0, "flows": 0, "unpaired": 0, "dport": e["dport"],
        })
        g["sent_bytes"] += e["sent_bytes"]
        g["recv_bytes"] += e["recv_bytes"]
        g["flows"] += 1
        if not e["paired"]:
            g["unpaired"] += 1
    ranked = sorted(groups.values(),
                    key=lambda g: (-(g["sent_bytes"] + g["recv_bytes"]),
                                   g["process"], g["destination"]))
    rows = [{
        "process": g["process"],
        "destination": g["destination"],
        "sent_bytes": g["sent_bytes"],
        "recv_bytes": g["recv_bytes"],
        "flows": g["flows"],
        "assessment": detect.volume_assessment(g, cfg),
    } for g in ranked[: CAPS["volume_rows"]]]
    note = (f"Measured byte counts cover {len(measured)} of {len(events)} "
            "connection(s); unmeasured connections are left out rather than "
            "estimated.")
    return {"available": True, "note": note, "rows": rows}, ranked


# ------------------------------------------------------------------ agents

def _most_common(values):
    counts = Counter(v for v in values if v is not None)
    if not counts:
        return None
    best = max(counts.values())
    return sorted((v for v, c in counts.items() if c == best), key=str)[0]


def agents(events, detections_by_process, off_allowlist, cfg):
    """One row per configured AI process name and per configured account."""
    rows = []
    for name in cfg["ai_process_names"]:
        mine = [e for e in events if e["process"] and (
            severity.process_name(e["process"]) == name or e["process"] == name)]
        process = _most_common(e["process"] for e in mine) or name
        rows.append(_agent_row(name, process, mine, cfg,
                               detect.process_verdict(name, mine,
                                                      detections_by_process.get(process, {}))))
    for account in cfg["agent_accounts"]:
        mine = [e for e in events if severity.account_of(e, cfg) == account]
        process = _most_common(process_label(e) for e in mine) or ""
        rows.append(_agent_row(account, process, mine, cfg,
                               detect.account_verdict(account, mine,
                                                      off_allowlist.get(account, set()),
                                                      cfg)))
    return rows


def _agent_row(name, process, mine, cfg, verdict):
    uid = _most_common(e["uid"] for e in mine)
    return {
        "process": process,
        "pid": _most_common(e["pid"] for e in mine),
        "user": _most_common(user_label(e) for e in mine) or "",
        "connections": len(mine),
        "ports": sorted({e["dport"] for e in mine}),
        "destinations": sorted({e["destination"] for e in mine})[: cfg["aggregate_cap"]],
        "privilege_note": detect.privilege_note(name, uid, bool(mine)),
        "verdict": verdict,
    }


# -------------------------------------------------------------- aggregates

def _tally(values, cap):
    counts = Counter(v for v in values if v)
    ranked = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    return [{"what": what, "hits": hits} for what, hits in ranked[:cap]]


def aggregates(events, daemon, cfg):
    daemon = daemon or {}
    cap = cfg["aggregate_cap"]
    denied = sum(1 for e in events if e["action"] == "deny")
    last = max((e["ts"] for e in events), key=parse_timestamp, default="")
    node = {
        "addr": "", "hostname": "", "daemon_version": "", "daemon_uptime": 0,
        "daemon_rules": 0, "cons": len(events), "cons_dropped": denied,
        "version": "", "status": "unknown", "last_connection": last,
    }
    node.update(daemon.get("node", {}))
    rules_detail = list(daemon.get("rules_detail", []))
    return {
        "daemon_uptime": daemon.get("daemon_uptime", node["daemon_uptime"]),
        "total_connections": daemon.get("total_connections", len(events)),
        "dropped": daemon.get("dropped", denied),
        "rules": daemon.get("rules", len(rules_detail)),
        "procs": _tally((process_label(e) for e in events), cap),
        "hosts": _tally((e["dst_host"] for e in events), CAPS["hosts"]),
        "users": _tally((user_label(e) for e in events), cap),
        "ports": _tally((f"{e['proto']}/{e['dport']}" for e in events), cap),
        "addrs": _tally((e["dst_ip"] for e in events), CAPS["addrs"]),
        "node": node,
        "rules_detail": rules_detail,
        "sockets": list(daemon.get("sockets", []))[:cap],
    }


# ----------------------------------------------------------- record build

def build_record(events, *, started_at, window_start, window_end, status,
                 prior_records, cfg, daemon=None, note=""):
    """Analyse one window of events and return an unsealed full record.

    prior_records are earlier records of either form; they supply coverage
    and the novelty baseline.
    """
    if status not in STATUSES:
        raise ValueError(f"unknown status {status!r}")
    events = [normalise_event(e) for e in events]
    if status == STATUS_NO_DATA and events:
        raise ValueError("a no_data run cannot carry events")
    events.sort(key=lambda e: parse_timestamp(e["ts"]))

    baseline_sets = baseline_from(prior_records, cfg)
    ctx = {
        "cfg": cfg,
        "baseline": set().union(*baseline_sets) if baseline_sets else set(),
        "baseline_runs": len(baseline_sets),
    }

    beacons = beaconing(events, cfg)
    vol, volume_groups = volume(events, cfg)
    outbound_pairs = {(g["process"], g["destination"]) for g in volume_groups
                      if severity.is_outbound_dominant(g["sent_bytes"], g["recv_bytes"], cfg)}

    # Each event collects the rules it triggers, from its own fields and from
    # the pair- or flow-level analyses it belongs to.
    fired = [severity.event_rules(e, ctx) for e in events]
    index_of = {id(e): i for i, e in enumerate(events)}
    for b in beacons:
        rule = severity.beacon_rule(b)
        if rule:
            for e in b["events"]:
                fired[index_of[id(e)]].append(rule)
    transfer_keys = {}
    for g in volume_groups:
        rule = severity.transfer_rule(g, cfg)
        if rule:
            transfer_keys[(g["process"], g["destination"])] = g
    for i, e in enumerate(events):
        if (process_label(e), e["destination"]) in transfer_keys and e["sent_bytes"] is not None:
            fired[i].append("outbound_transfer_unidentified")
        for strong, weak in severity.SUPPRESSES.items():
            if strong in fired[i] and weak in fired[i]:
                fired[i].remove(weak)

    per_process_dests = defaultdict(set)
    dns_counts = Counter()
    for e in events:
        if e["process"]:
            per_process_dests[e["process"]].add(e["destination"])
            if e["dport"] in cfg["dns_ports"]:
                dns_counts[e["process"]] += 1

    detections, overflow = detect.build_detections(
        events, fired, beacons, transfer_keys, outbound_pairs, per_process_dests,
        dns_counts, ctx)

    detections_by_process = defaultdict(Counter)
    for d in detections:
        detections_by_process[d["_process"]][d["severity"]] += 1
    off_allowlist = defaultdict(set)
    for e, rules in zip(events, fired):
        if "agent_off_allowlist" in rules:
            off_allowlist[severity.account_of(e, cfg)].add(e["destination"])
    agent_rows = agents(events, detections_by_process, off_allowlist, cfg)

    rows = []
    for e, rules in zip(events, fired):
        sev = min((severity.severity_of(r) for r in rules),
                  key=SEVERITY_RANK.__getitem__, default=LOW)
        rows.append({
            "ts": e["ts"], "action": e["action"], "src": e["src"],
            "dst": e["destination"], "dport": e["dport"], "proto": e["proto"],
            "uid": e["uid"], "pid": e["pid"], "process": e["process"],
            "activity": detect.activity_label(rules, severity.is_ai(e, cfg)),
            "is_ai": severity.is_ai(e, cfg), "severity": sev,
        })
    # Rank by severity, newest first within a level. Sorting twice keeps
    # Python's stable sort doing the tie-breaking.
    rows.sort(key=lambda r: parse_timestamp(r["ts"]), reverse=True)
    rows.sort(key=lambda r: SEVERITY_RANK[r["severity"]])

    novel = novelty(events, baseline_sets, cfg)
    novel_count = (sum(1 for d in {e["destination"] for e in events}
                       if d not in ctx["baseline"]) if ctx["baseline_runs"] else 0)
    reported = [b for b in beacons if not b["expected"]]

    this_run = {"window_start": window_start, "window_end": window_end, "status": status}
    record = {
        "schema_version": SCHEMA_VERSION,
        "run_id": run_id_for(started_at),
        "started_at": started_at,
        "window_start": window_start,
        "window_end": window_end,
        "status": status,
        "trimmed": False,
        "note": detect.run_note(note, overflow),
        "coverage": coverage(list(prior_records) + [this_run], window_end, cfg),
        "totals": {
            "connections": len(events),
            "allowed": sum(1 for e in events if e["action"] == "allow"),
            "denied": sum(1 for e in events if e["action"] == "deny"),
            "unique_processes": len({e["process"] for e in events if e["process"]}),
            "unique_destinations": len({e["destination"] for e in events}),
            "ai_connections": sum(1 for e in events if severity.is_ai(e, cfg)),
            "unattributed": sum(1 for e in events if not e["process"]),
            "novel_destinations": novel_count,
            "beacon_candidates": len(reported),
            "agents_active": sum(1 for a in agent_rows if a["connections"]),
        },
        "detections": [{k: v for k, v in d.items() if not k.startswith("_")}
                       for d in detections],
        "beacons": [{k: b[k] for k in ("process", "destination", "count",
                                       "mean_interval", "jitter_pct", "confidence",
                                       "assessment")} for b in beacons],
        "novel": novel,
        "agents": agent_rows,
        "volume": vol,
        "rows": rows[: CAPS["rows"]],
        "aggregates": aggregates(events, daemon, cfg),
        "destinations": sorted({e["destination"] for e in events}),
    }
    return record

