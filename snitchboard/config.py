"""Settings defaults and validation.

Every default is neutral: no process, account, host or address is named, so
nothing here describes a particular machine. The first group mirrors the
plugin settings in PRD section 7.8; the second holds the analysis thresholds
that section 7.4 says are configurable.
"""

import copy

PLUGIN_DEFAULTS = {
    "runs_dir": "",
    "mode": "auto",
    "ai_process_names": [],
    "agent_accounts": [],
    "expected_services": [],
    "provider_allowlist": [],
    "unattended_hours": [],
    "redact_by_default": True,
    "allow_reveal": True,
    "retention_days": 14,
    "telemetry_destinations": [],
    "trimmed_max_bytes": 8192,
}

# Bounds for trimmed_max_bytes. The ceiling is the full-record cap in
# schema.CAPS, written as a literal because schema is not imported here; a
# test keeps the two equal.
TRIMMED_MAX_BYTES_FLOOR = 1024
TRIMMED_MAX_BYTES_CEILING = 200 * 1024

ENGINE_DEFAULTS = {
    "standard_ports": [53, 80, 123, 443, 853],
    "web_ports": [80, 443],
    "dns_ports": [53, 853],
    "beacon_min_contacts": 8,
    "beacon_excluded_ports": [53],
    "beacon_min_mean_s": 20,
    "beacon_max_mean_s": 7200,
    "beacon_max_jitter_pct": 60.0,
    "beacon_high_below_pct": 10.0,
    "beacon_medium_below_pct": 25.0,
    "novelty_max_prior": 48,
    "novelty_top": 15,
    "coverage_hours": 24,
    "coverage_tolerance_s": 300,
    "transfer_high_bytes": 1_000_000,
    "outbound_ratio": 2.0,
    "many_destinations_threshold": 50,
    "dns_volume_threshold": 500,
    "max_detections": 50,
    "evidence_per_detection": 5,
    "aggregate_cap": 20,
}

DEFAULTS = {**PLUGIN_DEFAULTS, **ENGINE_DEFAULTS}

MODES = ("auto", "demo", "live")

_LIST_OF_STR = (
    "ai_process_names", "agent_accounts", "expected_services",
    "provider_allowlist", "telemetry_destinations",
)
_LIST_OF_INT = (
    "unattended_hours", "standard_ports", "web_ports", "dns_ports",
    "beacon_excluded_ports",
)
_BOOL = ("redact_by_default", "allow_reveal")
_NUMBER = (
    "beacon_max_jitter_pct", "beacon_high_below_pct",
    "beacon_medium_below_pct", "outbound_ratio",
)


def load(overrides=None):
    """Merge `overrides` onto the defaults and validate the result.

    Unknown keys raise rather than being ignored, so a misspelt threshold is
    reported instead of silently leaving the default in force.
    """
    cfg = copy.deepcopy(DEFAULTS)
    overrides = overrides or {}
    unknown = sorted(set(overrides) - set(DEFAULTS))
    if unknown:
        raise ValueError(f"unknown setting(s): {', '.join(unknown)}")
    cfg.update(copy.deepcopy(overrides))
    problems = check(cfg)
    if problems:
        raise ValueError("; ".join(problems))
    return cfg


def is_integer(value):
    return isinstance(value, int) and not isinstance(value, bool)


def check(cfg):
    problems = []
    for key in _LIST_OF_STR:
        value = cfg[key]
        if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
            problems.append(f"{key} must be a list of strings")
    for key in _LIST_OF_INT:
        value = cfg[key]
        if not isinstance(value, list) or not all(
                isinstance(v, int) and not isinstance(v, bool) for v in value):
            problems.append(f"{key} must be a list of integers")
    if all(isinstance(h, int) for h in cfg["unattended_hours"]):
        if any(h < 0 or h > 23 for h in cfg["unattended_hours"]):
            problems.append("unattended_hours must hold hours from 0 to 23")
    for key in _BOOL:
        if not isinstance(cfg[key], bool):
            problems.append(f"{key} must be true or false")
    for key in _NUMBER:
        if not isinstance(cfg[key], (int, float)) or isinstance(cfg[key], bool):
            problems.append(f"{key} must be a number")
    if cfg["mode"] not in MODES:
        problems.append(f"mode must be one of {', '.join(MODES)}")
    if not isinstance(cfg["runs_dir"], str):
        problems.append("runs_dir must be a string")
    integer_keys = set(DEFAULTS) - set(_LIST_OF_STR) - set(_LIST_OF_INT) \
        - set(_BOOL) - set(_NUMBER) - {"mode", "runs_dir"}
    for key in sorted(integer_keys):
        value = cfg[key]
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            problems.append(f"{key} must be a non-negative integer")
    limit = cfg["trimmed_max_bytes"]
    if is_integer(limit) and not (
            TRIMMED_MAX_BYTES_FLOOR <= limit <= TRIMMED_MAX_BYTES_CEILING):
        problems.append(f"trimmed_max_bytes must lie between {TRIMMED_MAX_BYTES_FLOOR} "
                        f"and {TRIMMED_MAX_BYTES_CEILING}")
    if not problems and cfg["beacon_min_mean_s"] > cfg["beacon_max_mean_s"]:
        problems.append("beacon_min_mean_s must not exceed beacon_max_mean_s")
    return problems
