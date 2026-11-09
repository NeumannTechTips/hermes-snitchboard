#!/usr/bin/env python3
"""Generate the synthetic demonstration runs in fixtures/.

Every value comes from ranges reserved for documentation (RFC 5737, RFC 3849,
RFC 2606, RFC 7042), and every process and account name is invented. The
records are produced by the real engine, so the fixtures exercise the same
code path as live data. Output is deterministic: running this twice gives
identical files, which tests/test_fixtures.py checks.

Usage: python3 tools/gen_demo.py [--out DIR]
"""

import argparse
import json
import random
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from snitchboard import analysis, chain, config, schema  # noqa: E402

# A fixed, non-zero offset shows that local time is kept, not relabelled.
OFFSET = timezone(timedelta(hours=1))
FIRST_WINDOW = datetime(2026, 11, 1, 1, 0, 0, tzinfo=OFFSET)
HOURS = 27
SKIPPED_HOUR = 9        # no run at all: a coverage gap
NO_DATA_HOUR = 15       # a run that collected nothing
FULL_RUNS = 2           # the newest runs stay in full form

LOCAL_ADDR = "192.0.2.10"

DEMO_SETTINGS = {
    "mode": "demo",
    "ai_process_names": ["agent-runner", "model-gateway"],
    "agent_accounts": ["agent-svc"],
    "expected_services": ["note-sync"],
    "provider_allowlist": ["api.example.com"],
    "unattended_hours": [0, 1, 2, 3, 4, 5],
    "telemetry_destinations": ["telemetry.example.net"],
}

BROWSER = ("/usr/bin/web-browser", 2101, 1000, "demo-user")
RESOLVER = ("/usr/libexec/name-resolver", 610, 990, "resolver-svc")
NOTE_SYNC = ("/usr/bin/note-sync", 2240, 1000, "demo-user")
UPDATER = ("/usr/libexec/update-checker", 702, 0, "root")
CLOCK = ("/usr/sbin/clock-sync", 655, 995, "clock-svc")
AGENT = ("/home/demo-user/.local/bin/agent-runner", 3300, 1500, "agent-svc")
GATEWAY = ("/usr/local/bin/model-gateway", 3410, 1000, "demo-user")
WIDGET = ("/opt/widget/bin/widget-helper", 4120, 1000, "demo-user")

HOSTS = {
    "cdn.example.net": "203.0.113.20",
    "mirror.example.com": "198.51.100.30",
    "news.example.com": "198.51.100.31",
    "sync.example.com": "203.0.113.40",
    "updates.example.com": "198.51.100.50",
    "time.example.net": "192.0.2.123",
    "api.example.com": "203.0.113.10",
    "telemetry.example.net": "192.0.2.90",
    "relay.example.net": "198.51.100.77",
    "files.example.net": "203.0.113.99",
    "newsfeed.example.com": "203.0.113.61",
}
CDN_V6 = "2001:db8:20::14"
RESOLVER_ADDR = "192.0.2.53"


class Window:
    def __init__(self, hour):
        self.hour = hour
        self.start = FIRST_WINDOW + timedelta(hours=hour)
        self.end = self.start + timedelta(hours=1)
        self.rng = random.Random(7000 + hour)
        self.events = []
        self.measured = True
        self.port_seq = 40000 + hour * 100

    def at(self, seconds):
        return (self.start + timedelta(seconds=seconds)).isoformat(timespec="seconds")

    def add(self, who, seconds, host=None, ip=None, port=443, proto="tcp",
            action="allow", sent=None, recv=None, paired=True):
        process, pid, uid, user = who if who else (None, None, None, None)
        self.port_seq += 1
        event = {
            "ts": self.at(seconds), "action": action, "src": LOCAL_ADDR,
            "dst_ip": ip or HOSTS[host], "dst_host": host, "dport": port,
            "proto": proto, "uid": uid, "user": user, "pid": pid,
            "process": process,
        }
        if self.measured:
            event["sent_bytes"] = sent if sent is not None else self.rng.randint(400, 9000)
            event["recv_bytes"] = recv if recv is not None else self.rng.randint(2000, 400000)
            event["paired"] = paired
        self.events.append(event)

    def periodic(self, who, host, interval, jitter_frac, offset, port=443):
        t = offset
        while t < 3600:
            self.add(who, int(t), host, port=port)
            t += interval * (1 + self.rng.uniform(-jitter_frac, jitter_frac))

    def scattered(self, who, host, count, port=443, proto="tcp", ip=None):
        for _ in range(count):
            self.add(who, self.rng.randint(0, 3599), host, ip=ip, port=port, proto=proto)


def routine(w):
    w.scattered(BROWSER, "cdn.example.net", w.rng.randint(8, 16))
    w.scattered(BROWSER, "cdn.example.net", w.rng.randint(2, 5), ip=CDN_V6)
    w.scattered(BROWSER, "mirror.example.com", w.rng.randint(3, 8))
    w.scattered(BROWSER, "news.example.com", w.rng.randint(2, 6))
    w.scattered(RESOLVER, None, w.rng.randint(25, 45), port=53, proto="udp", ip=RESOLVER_ADDR)
    w.periodic(NOTE_SYNC, "sync.example.com", 180, 0.02, 30)
    w.periodic(UPDATER, "updates.example.com", 360, 0.36, 50)
    w.scattered(CLOCK, "time.example.net", 4, port=123, proto="udp")
    w.scattered(AGENT, "api.example.com", w.rng.randint(10, 25))
    w.scattered(GATEWAY, "api.example.com", w.rng.randint(4, 10))
    if w.hour % 4 == 0:
        w.scattered(AGENT, "telemetry.example.net", 2)


def incidents(w, newest):
    """Findings planted in the two full runs, one for each severity rule."""
    w.periodic(WIDGET, "relay.example.net", 240, 0.01, 90, port=8443)
    w.add(BROWSER, 1210, None, ip="198.51.100.66", port=80, action="deny")
    if not newest:
        return
    for i, (sent, paired) in enumerate([(2_600_000, False), (1_100_000, True),
                                        (650_000, True)]):
        w.add(GATEWAY, 600 + i * 410, None, ip="203.0.113.80", port=7000,
              sent=sent, recv=9000 + i * 1200, paired=paired)
    w.add(AGENT, 1200, "files.example.net", sent=48_000, recv=3_100)
    w.scattered(AGENT, "telemetry.example.net", 3)
    w.add(None, 2405, None, ip="198.51.100.23", port=443)
    w.add(None, 2950, None, ip="198.51.100.23", port=443)
    w.add(BROWSER, 3010, "newsfeed.example.com")


def daemon_state(w, cons_total, dropped_total):
    last = max(e["ts"] for e in w.events) if w.events else ""
    created = FIRST_WINDOW.isoformat(timespec="seconds")
    rules = [
        ("allow-name-resolver", "allow", "process.path", RESOLVER[0]),
        ("allow-web-browser", "allow", "process.path", BROWSER[0]),
        ("allow-agent-provider", "allow", "dest.host", "api.example.com"),
        ("deny-plain-http-browser", "deny", "dest.port", "80"),
    ]
    return {
        "daemon_uptime": 86400 + w.hour * 3600,
        "total_connections": cons_total,
        "dropped": dropped_total,
        "node": {
            "addr": LOCAL_ADDR, "hostname": "demo-host.example.com",
            "daemon_version": "demo-1.0", "daemon_uptime": 86400 + w.hour * 3600,
            "daemon_rules": len(rules), "cons": cons_total,
            "cons_dropped": dropped_total, "version": "demo-1.0",
            "status": "running", "last_connection": last,
        },
        "rules_detail": [{
            "name": name, "enabled": True, "precedence": action == "deny",
            "action": action, "duration": "always", "operator_type": "simple",
            "operator_operand": operand, "operator_data": data, "created": created,
        } for name, action, operand, data in rules],
        "sockets": [
            {"what": f"tcp {LOCAL_ADDR}:52344 -> {HOSTS['api.example.com']}:443 ESTABLISHED",
             "hits": 1},
            {"what": f"udp {LOCAL_ADDR}:41000 -> {RESOLVER_ADDR}:53", "hits": 1},
        ],
    }


def generate():
    cfg = config.load(DEMO_SETTINGS)
    sealed = []
    cons_total = dropped_total = 0
    for hour in range(HOURS):
        if hour == SKIPPED_HOUR:
            continue
        w = Window(hour)
        newest = hour == HOURS - 1
        full = hour >= HOURS - FULL_RUNS
        status, note = schema.STATUS_OK, ""
        if hour == NO_DATA_HOUR:
            status = schema.STATUS_NO_DATA
            note = ("Collection unavailable: the statistics database could not be "
                    "read during this window.")
        else:
            if hour == HOURS - 2:
                w.measured = False
                note = "Byte counting was switched off for this window."
            routine(w)
            if full:
                incidents(w, newest)
        cons_total += len(w.events)
        dropped_total += sum(1 for e in w.events if e["action"] == "deny")
        started = (w.end + timedelta(seconds=2)).isoformat(timespec="seconds")
        record = analysis.build_record(
            w.events,
            started_at=started,
            window_start=w.start.isoformat(timespec="seconds"),
            window_end=w.end.isoformat(timespec="seconds"),
            status=status,
            prior_records=sealed,
            cfg=cfg,
            daemon=daemon_state(w, cons_total, dropped_total) if w.events else None,
            note=note,
        )
        sealed.append(chain.seal(record, sealed[-1] if sealed else None))
    keep_full = len(sealed) - FULL_RUNS
    cap = cfg["trimmed_max_bytes"]
    return [chain.trim(r, max_bytes=cap) if i < keep_full else r
            for i, r in enumerate(sealed)]


def write(out_dir):
    runs_dir = Path(out_dir) / "runs"
    runs_dir.mkdir(parents=True, exist_ok=True)
    for stale in runs_dir.glob("run-*.json"):
        stale.unlink()
    records = generate()
    cap = config.load(DEMO_SETTINGS)["trimmed_max_bytes"]
    for record in records:
        problems = schema.validate(record, trimmed_cap=cap)
        if problems:
            raise SystemExit(f"{record['run_id']} is invalid: {problems}")
        path = runs_dir / f"{record['run_id']}.json"
        path.write_text(json.dumps(record, indent=1, sort_keys=True,
                                   ensure_ascii=False) + "\n", encoding="utf-8")
    settings = Path(out_dir) / "demo_settings.json"
    settings.write_text(json.dumps(DEMO_SETTINGS, indent=1, sort_keys=True) + "\n",
                        encoding="utf-8")
    result = chain.verify(records)
    if not result["intact"]:
        raise SystemExit(result["summary"])
    return records, result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", default=str(REPO / "fixtures"),
                        help="output directory (default: fixtures/)")
    args = parser.parse_args(argv)
    records, result = write(args.out)
    full = sum(1 for r in records if not r["trimmed"])
    print(f"Wrote {len(records)} runs ({full} full, {len(records) - full} trimmed) "
          f"to {args.out}. {result['summary']}")


if __name__ == "__main__":
    main()
