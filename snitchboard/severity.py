"""Severity rules (HSB-PRD-001 section 7.6) and the matching they depend on.

RULES is the whole of the severity policy. The three low-severity rules at the
end are this implementation's reading of "anything else worth recording".
"""

import ipaddress
import posixpath

from .schema import HIGH, LOW, MEDIUM, parse_timestamp

# rule id -> (severity, confidence)
RULES = {
    # High, in the order section 7.6 lists them.
    "unattributed": (HIGH, HIGH),
    "ai_nonstandard_port": (HIGH, HIGH),
    "denied": (HIGH, HIGH),
    "ai_novel_unattended": (HIGH, MEDIUM),
    "agent_off_allowlist": (HIGH, HIGH),
    "outbound_transfer_unidentified": (HIGH, HIGH),
    # Medium.
    "new_destination_known_process": (MEDIUM, MEDIUM),
    "ai_telemetry": (MEDIUM, HIGH),
    "beacon_high_confidence": (MEDIUM, HIGH),
    # Low.
    "beacon_candidate": (LOW, None),
    "dns_volume": (LOW, MEDIUM),
    "many_destinations": (LOW, LOW),
}

# A rule that subsumes another for the same connection suppresses it, so one
# event is not reported twice for the same reason at two severities.
SUPPRESSES = {
    "ai_novel_unattended": "new_destination_known_process",
    "beacon_high_confidence": "beacon_candidate",
}


def severity_of(rule):
    return RULES[rule][0]


def is_address(value):
    try:
        ipaddress.ip_address(value)
    except ValueError:
        return False
    return True


def matches(value, patterns):
    """Match a destination, process or account against configured patterns.

    A pattern is an exact value (case-insensitive), a `*.domain` suffix that
    also matches the bare domain, or a CIDR block for addresses.
    """
    if not value:
        return False
    text = str(value).lower()
    for pattern in patterns:
        pat = pattern.lower()
        if pat == text:
            return True
        if pat.startswith("*.") and (text.endswith(pat[1:]) or text == pat[2:]):
            return True
        if "/" in pat and is_address(text):
            try:
                if ipaddress.ip_address(text) in ipaddress.ip_network(pat, strict=False):
                    return True
            except ValueError:
                continue
    return False


def process_name(process):
    return posixpath.basename(process) if process else ""


def is_ai(event, cfg):
    return bool(event["process"]) and (
        process_name(event["process"]) in cfg["ai_process_names"]
        or event["process"] in cfg["ai_process_names"])


def account_of(event, cfg):
    """The configured agent account an event belongs to, or None."""
    for account in cfg["agent_accounts"]:
        if account == event.get("user") or (
                event.get("uid") is not None and account == str(event["uid"])):
            return account
    return None


def in_unattended_hours(ts, cfg):
    # The hour is read in the timestamp's own offset, never converted.
    return parse_timestamp(ts).hour in cfg["unattended_hours"]


def event_rules(event, ctx):
    """Rules triggered by a single connection event.

    ctx carries cfg, baseline (set of destinations seen in prior runs) and
    baseline_runs (how many prior runs with data the baseline covers).
    """
    cfg = ctx["cfg"]
    fired = []
    dest = event["destination"]
    ai = is_ai(event, cfg)
    if not event["process"]:
        fired.append("unattributed")
    if ai and event["dport"] not in cfg["standard_ports"]:
        fired.append("ai_nonstandard_port")
    if event["action"] == "deny":
        fired.append("denied")
    is_new = ctx["baseline_runs"] > 0 and dest not in ctx["baseline"]
    if is_new and ai and in_unattended_hours(event["ts"], cfg):
        fired.append("ai_novel_unattended")
    elif is_new and event["process"]:
        fired.append("new_destination_known_process")
    if account_of(event, cfg) and not matches(dest, cfg["provider_allowlist"]):
        fired.append("agent_off_allowlist")
    if ai and matches(dest, cfg["telemetry_destinations"]):
        fired.append("ai_telemetry")
    return fired


def is_outbound_dominant(sent, recv, cfg):
    return sent > 0 and sent >= cfg["outbound_ratio"] * recv


def transfer_rule(volume_group, cfg):
    """The flow-level High rule: a large outbound transfer to a bare address."""
    sent, recv = volume_group["sent_bytes"], volume_group["recv_bytes"]
    if (sent > cfg["transfer_high_bytes"] and is_outbound_dominant(sent, recv, cfg)
            and is_address(volume_group["destination"])):
        return "outbound_transfer_unidentified"
    return None


def beacon_rule(beacon):
    """Expected services are labelled, not flagged, so they yield no rule."""
    if beacon["expected"]:
        return None
    return "beacon_high_confidence" if beacon["confidence"] == HIGH else "beacon_candidate"
