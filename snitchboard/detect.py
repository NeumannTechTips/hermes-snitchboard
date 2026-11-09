"""Detections and the plain-language text attached to findings.

Kept apart from severity.py so the rule table stays short enough to check
against the PRD at a glance. Every sentence produced here names the process,
account or destination it concerns, so two findings in one record never
share a sentence.
"""

from collections import defaultdict

from . import attack, severity
from .schema import SEVERITY_RANK, parse_timestamp

UNATTRIBUTED_LABEL = "unattributed process"

_EVENT_RULES = (
    "unattributed", "ai_nonstandard_port", "denied", "ai_novel_unattended",
    "new_destination_known_process", "agent_off_allowlist", "ai_telemetry",
)

_ACTIVITY = {
    "unattributed": "no attributable process",
    "ai_nonstandard_port": "AI tooling on a non-standard port",
    "denied": "denied by the firewall",
    "ai_novel_unattended": "AI tooling, new destination, unattended hours",
    "agent_off_allowlist": "agent account outside its allowlist",
    "outbound_transfer_unidentified": "large outbound transfer",
    "new_destination_known_process": "new destination",
    "ai_telemetry": "AI tooling reaching telemetry",
    "beacon_high_confidence": "regular-interval contact, high confidence",
    "beacon_candidate": "regular-interval contact",
}


def _label(process):
    return process or UNATTRIBUTED_LABEL


def evidence_line(e):
    dest = e["destination"]
    where = dest if dest == e["dst_ip"] else f"{dest} ({e['dst_ip']})"
    pid = e["pid"] if e["pid"] is not None else "unknown"
    uid = e["uid"] if e["uid"] is not None else "unknown"
    return (f"{e['ts']} {e['action']} {_label(e['process'])} pid {pid} uid {uid} "
            f"-> {where} {e['proto']}/{e['dport']}")


def baseline_note(dest, seen, baseline_runs):
    if baseline_runs == 0:
        return (f"No prior run with collected data exists, so {dest} scores 100 "
                "by definition rather than on evidence.")
    return f"{dest} appeared in {seen} of {baseline_runs} prior run(s) with collected data."


def beacon_assessment(proc, dest, count, mean, jitter, expected):
    if expected:
        return (f"Expected service: contact between {proc} and {dest} matches the "
                f"configured expected list, so it is labelled rather than flagged. "
                f"Benign reading: routine polling of {dest} by {proc}, as the list "
                f"anticipates. Malicious reading: a heartbeat to {dest} hidden inside "
                f"traffic already trusted as {proc}.")
    return (f"{proc} contacted {dest} {count} times, every {mean:g} s on average "
            f"with {jitter:g}% jitter. Benign reading: {proc} polling {dest} for "
            f"updates, synchronisation or a keep-alive. Malicious reading: a "
            f"command-and-control heartbeat from {proc} to {dest}.")


def volume_assessment(group, cfg):
    proc, dest = group["process"], group["destination"]
    sent, recv = group["sent_bytes"], group["recv_bytes"]
    ratio = cfg["outbound_ratio"]
    if sent > 0 and recv == 0:
        text = f"Outbound only: {proc} sent {sent} bytes to {dest} and received none."
    elif sent >= ratio * recv and sent > 0:
        text = (f"Outbound-dominant: {proc} sent {sent / recv:.1f} times what it "
                f"received from {dest}.")
    elif recv >= ratio * sent:
        text = (f"Inbound-dominant: {proc} mostly downloaded from {dest}, which "
                "fits fetching content.")
    else:
        text = (f"Balanced exchange between {proc} and {dest}, typical of an "
                "interactive session.")
    if group["unpaired"]:
        text += (f" {group['unpaired']} flow(s) to {dest} opened before the window "
                 "and could not be paired, so their counts cover only the part "
                 "observed.")
    return text


def privilege_note(name, uid, active):
    if not active:
        return f"{name} was not observed in this window, so its privileges cannot be assessed."
    if uid is None:
        return f"{name} ran under an account the firewall could not identify."
    if uid == 0:
        return f"{name} ran as root (uid 0), far more privilege than network access requires."
    if uid < 1000:
        return f"{name} ran under system account uid {uid}."
    return f"{name} ran under an unprivileged account (uid {uid})."


def process_verdict(name, mine, severities):
    if not mine:
        return (f"No connections from {name} in this window; that says nothing "
                "about its activity outside the window.")
    if not severities:
        return f"{name} made {len(mine)} connection(s) and raised no findings."
    parts = [f"{severities[s]} {s}" for s in ("high", "medium", "low") if severities.get(s)]
    return f"{name} raised {', '.join(parts)} finding(s); see Findings for each one."


def account_verdict(account, mine, off_allowlist, cfg):
    if not mine:
        return (f"No connections from account {account} in this window; that "
                "says nothing about its activity outside the window.")
    if not cfg["provider_allowlist"]:
        return (f"Account {account} has no provider allowlist configured, so all "
                f"{len({e['destination'] for e in mine})} destination(s) it reached are flagged.")
    if off_allowlist:
        return (f"Account {account} reached {len(off_allowlist)} destination(s) "
                "outside the provider allowlist.")
    return f"Account {account} kept to the provider allowlist."


def activity_label(rules, is_ai):
    for rule in sorted(rules, key=lambda r: SEVERITY_RANK[severity.severity_of(r)]):
        if rule in _ACTIVITY:
            return _ACTIVITY[rule]
    return "AI tooling, routine" if is_ai else "routine"


def run_note(note, overflow):
    if not overflow:
        return note
    extra = (f"{overflow} lower-severity detection(s) beyond the cap were not "
             "recorded; the totals still count every connection.")
    return f"{note} {extra}".strip()


def _local_time(ts):
    return parse_timestamp(ts).strftime("%H:%M %z")


def _event_detection(rule, proc, dest, port, group, ctx, outbound_pairs):
    cfg = ctx["cfg"]
    first = group[0]
    n = len(group)
    proto = first["proto"]
    label = _label(proc)
    if rule == "unattributed":
        tech = attack.channel_technique(port, cfg)
        title = f"Connection with no attributable process to {dest}:{port}"
        detail = (f"{n} connection(s) to {dest} on {proto}/{port} could not be tied "
                  "to any process, so nothing on the host accounts for them.")
        rec = (f"Check whether a short-lived or containerised process reached {dest}, "
               "and restore process attribution for that path if it is missing.")
    elif rule == "ai_nonstandard_port":
        outbound = (label, dest) in outbound_pairs
        tech = attack.nonstandard_port_technique(outbound)
        title = f"AI process {label} used non-standard port {port} to reach {dest}"
        reading = ("Measured bytes show the exchange with {d} was outbound-dominant, "
                   "which supports the exfiltration reading." if outbound else
                   "Without measured bytes showing an outbound-dominant exchange with "
                   "{d}, the control-channel reading stands.").format(d=dest)
        detail = (f"{label} made {n} connection(s) to {dest} on {proto}/{port}, outside "
                  f"the configured standard ports. {reading}")
        rec = (f"Confirm that {label} is meant to use port {port}; if not, block {dest} "
               "on that port and review the tool calls made in this window.")
    elif rule == "denied":
        tech = attack.channel_technique(port, cfg)
        title = f"Denied connection from {label} to {dest}:{port}"
        detail = f"The firewall denied {n} attempt(s) by {label} to reach {dest} on {proto}/{port}."
        rec = (f"Find out why {label} tried to reach {dest}: the denial stopped the "
               "attempt but not whatever caused it.")
    elif rule == "ai_novel_unattended":
        tech = "T1568"
        title = f"AI tooling reached new destination {dest} during unattended hours"
        detail = (f"{label} contacted {dest} at {_local_time(first['ts'])}, inside the "
                  f"configured unattended hours, and {dest} appears in none of the "
                  f"{ctx['baseline_runs']} prior run(s) with collected data.")
        rec = (f"Review what {label} was doing at that time and whether anyone "
               f"instructed it to contact {dest}.")
    elif rule == "new_destination_known_process":
        tech = "T1568"
        title = f"New destination {dest} for {label}"
        detail = (f"{label} reached {dest} {n} time(s), and {dest} appears in none of "
                  f"the {ctx['baseline_runs']} prior run(s) with collected data.")
        rec = (f"Confirm that {dest} is a legitimate service for {label}; if it is "
               "routine it stops reading as new once it recurs.")
    elif rule == "agent_off_allowlist":
        account = severity.account_of(first, cfg)
        tech = "T1078"
        title = f"Agent account {account} reached {dest}, outside the provider allowlist"
        detail = (f"Account {account} made {n} connection(s) through {label} to {dest} "
                  f"on {proto}/{port}, and {dest} is not on the provider allowlist.")
        rec = (f"Add {dest} to the allowlist only if account {account} genuinely needs "
               "it; otherwise restrict the account's outbound access.")
    elif rule == "ai_telemetry":
        tech = "T1567"
        title = f"AI tooling {label} reached third-party telemetry at {dest}"
        detail = (f"{label} made {n} connection(s) to {dest}, which matches the "
                  "configured telemetry list.")
        rec = f"Decide whether {label} should report to {dest}, and disable that telemetry if not."
    else:
        raise KeyError(rule)
    return tech, title, detail, rec


def build_detections(events, fired, beacons, transfer_keys, outbound_pairs,
                     per_process_dests, dns_counts, ctx):
    cfg = ctx["cfg"]
    per = cfg["evidence_per_detection"]
    out = []

    def add(rule, tech, title, detail, evidence, rec, process, confidence=None):
        sev, default_conf = severity.RULES[rule]
        out.append({
            "title": title,
            "severity": sev,
            "confidence": confidence or default_conf,
            "attack": attack.block(tech),
            "detail": detail,
            "evidence": evidence[:per],
            "recommendation": rec,
            "_process": process,
        })

    groups = defaultdict(list)
    for e, rules in zip(events, fired):
        for rule in rules:
            if rule in _EVENT_RULES:
                groups[(rule, e["process"], e["destination"], e["dport"])].append(e)
    for (rule, proc, dest, port), group in groups.items():
        tech, title, detail, rec = _event_detection(rule, proc, dest, port, group,
                                                    ctx, outbound_pairs)
        add(rule, tech, title, detail, [evidence_line(e) for e in group], rec, proc)

    for b in beacons:
        rule = severity.beacon_rule(b)
        if not rule:
            continue
        add(rule, "T1071",
            f"Regular-interval contact from {b['process']} to {b['destination']}",
            (f"{b['process']} reached {b['destination']} on port {b['dport']} "
             f"{b['count']} times, a mean of {b['mean_interval']:g} s apart. The "
             f"rhythm fits either routine polling by {b['process']} or a "
             f"control-server heartbeat to {b['destination']}."),
            [evidence_line(e) for e in b["events"]],
            (f"Compare the {b['mean_interval']:g}-second rhythm from {b['process']} "
             f"with its documented polling; if nothing explains it, isolate the "
             f"process and investigate {b['destination']}."),
            b["events"][0]["process"], confidence=b["confidence"])

    for (proc, dest), g in transfer_keys.items():
        mine = [e for e in events if (e["process"] or UNATTRIBUTED_LABEL) == proc
                and e["destination"] == dest and e["sent_bytes"] is not None]
        unpaired = (f" {g['unpaired']} flow(s) opened before the window, so the "
                    "figure for those covers only the part observed.") if g["unpaired"] else ""
        add("outbound_transfer_unidentified", attack.transfer_technique(g["dport"], cfg),
            f"Outbound-dominant transfer of {g['sent_bytes'] / 1e6:.1f} MB from {proc} "
            f"to unidentified {dest}",
            (f"{proc} sent {g['sent_bytes']} bytes and received {g['recv_bytes']} across "
             f"{g['flows']} flow(s) to {dest}, an address with no resolved name.{unpaired}"),
            [evidence_line(e) for e in mine],
            (f"Identify who operates {dest} and establish what {proc} uploaded; treat "
             "it as possible exfiltration until explained."),
            mine[0]["process"] if mine else None)

    for proc, dests in sorted(per_process_dests.items()):
        if len(dests) > cfg["many_destinations_threshold"]:
            sample = [evidence_line(e) for e in events if e["process"] == proc]
            add("many_destinations", "T1568",
                f"{proc} reached {len(dests)} distinct destinations",
                (f"{proc} contacted {len(dests)} distinct destinations in this window, "
                 f"above the threshold of {cfg['many_destinations_threshold']}."),
                sample,
                (f"Review the destinations reached by {proc} for names that look "
                 "generated or unrelated to its purpose."),
                proc)
    for proc, count in sorted(dns_counts.items()):
        if count > cfg["dns_volume_threshold"]:
            sample = [evidence_line(e) for e in events
                      if e["process"] == proc and e["dport"] in cfg["dns_ports"]]
            add("dns_volume", "T1071.004", f"Unusual DNS volume from {proc}",
                (f"{proc} made {count} DNS lookups in this window, above the threshold "
                 f"of {cfg['dns_volume_threshold']}."),
                sample,
                (f"Check whether {proc} is resolving many generated names, which can "
                 "indicate tunnelling or dynamic resolution."),
                proc)

    out.sort(key=lambda d: (SEVERITY_RANK[d["severity"]], d["title"]))
    cap = cfg["max_detections"]
    return out[:cap], max(0, len(out) - cap)
