"""Shared builders for the test suite. Every value is a documentation value."""

from datetime import datetime, timedelta, timezone

from snitchboard import analysis, chain, config

TZ = timezone(timedelta(hours=1))
T0 = datetime(2026, 11, 2, 10, 0, 0, tzinfo=TZ)

AI = "/usr/local/bin/test-agent"
APP = "/usr/bin/test-app"


def ts(seconds, base=T0):
    return (base + timedelta(seconds=seconds)).isoformat()


def event(seconds=0, *, process=APP, host="svc.example.com", ip="203.0.113.5",
          port=443, action="allow", uid=1000, user="test-user", pid=100,
          proto="tcp", sent=None, recv=None, paired=True, base=T0):
    e = {
        "ts": ts(seconds, base), "action": action, "src": "192.0.2.1",
        "dst_ip": ip, "dst_host": host, "dport": port, "proto": proto,
        "uid": uid, "user": user, "pid": pid, "process": process,
    }
    if sent is not None:
        e.update(sent_bytes=sent, recv_bytes=recv, paired=paired)
    return e


def at_offsets(offsets, **kw):
    return [event(s, **kw) for s in offsets]


def cumulative(intervals, start=0.0):
    out, t = [start], start
    for gap in intervals:
        t += gap
        out.append(t)
    return out


def cfg(**overrides):
    return config.load(overrides)


def build(events, *, prior=(), hour=0, status="ok", settings=None, daemon=None):
    """Build an unsealed record for the window starting `hour` hours after T0."""
    start = T0 + timedelta(hours=hour)
    end = start + timedelta(hours=1)
    return analysis.build_record(
        events,
        started_at=(end + timedelta(seconds=2)).isoformat(),
        window_start=start.isoformat(),
        window_end=end.isoformat(),
        status=status,
        prior_records=list(prior),
        cfg=settings or cfg(),
        daemon=daemon,
    )


def sealed_chain(n, settings=None):
    """n sealed full records, each holding one connection."""
    records = []
    for h in range(n):
        rec = build([event(60, base=T0 + timedelta(hours=h), host=f"h{h}.example.com")],
                    prior=records, hour=h, settings=settings)
        records.append(chain.seal(rec, records[-1] if records else None))
    return records


def prior_run(destinations, status="ok", hour=-1):
    """A minimal stand-in for an earlier record, as novelty and coverage read it."""
    start = T0 + timedelta(hours=hour)
    return {
        "started_at": (start + timedelta(hours=1, seconds=2)).isoformat(),
        "window_start": start.isoformat(),
        "window_end": (start + timedelta(hours=1)).isoformat(),
        "status": status,
        "destinations": sorted(destinations),
    }
