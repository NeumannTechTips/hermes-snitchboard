"""MITRE ATT&CK mapping (HSB-PRD-001 section 7.5).

PERMITTED is the single source of every identifier the engine may emit. A test
asserts that nothing outside it is produced, so adding a technique is a
deliberate edit here and in the PRD, never a side effect elsewhere.
"""

# technique_id -> (technique name, tactic name, tactic_id)
# T1078 spans several tactics; the PRD records it as not tied to one, so no
# tactic identifier is emitted for it rather than inventing a choice.
PERMITTED = {
    "T1071": ("Application Layer Protocol", "Command and Control", "TA0011"),
    "T1071.001": ("Web Protocols", "Command and Control", "TA0011"),
    "T1071.004": ("DNS", "Command and Control", "TA0011"),
    "T1568": ("Dynamic Resolution", "Command and Control", "TA0011"),
    "T1571": ("Non-Standard Port", "Command and Control", "TA0011"),
    "T1048": ("Exfiltration Over Alternative Protocol", "Exfiltration", "TA0010"),
    "T1567": ("Exfiltration Over Web Service", "Exfiltration", "TA0010"),
    "T1078": ("Valid Accounts", "Not tied to a single tactic", ""),
}

PERMITTED_TECHNIQUE_IDS = frozenset(PERMITTED)
PERMITTED_TACTIC_IDS = frozenset(t[2] for t in PERMITTED.values() if t[2])


def block(technique_id):
    """Return the attack block for a permitted technique, or raise KeyError."""
    name, tactic, tactic_id = PERMITTED[technique_id]
    return {
        "technique": name,
        "technique_id": technique_id,
        "tactic": tactic,
        "tactic_id": tactic_id,
    }


def is_permitted(attack_block):
    """True only when the block matches a permitted entry exactly."""
    if not isinstance(attack_block, dict):
        return False
    technique_id = attack_block.get("technique_id")
    if technique_id not in PERMITTED:
        return False
    return attack_block == block(technique_id)


def channel_technique(port, cfg):
    """Technique describing the channel a connection used, judged by port.

    Used for findings whose PRD pattern names no technique of its own, such as
    a denied or unattributed connection: the channel is what was observed.
    """
    if port in cfg["dns_ports"]:
        return "T1071.004"
    if port in cfg["web_ports"]:
        return "T1071.001"
    if port in cfg["standard_ports"]:
        return "T1071"
    return "T1571"


def nonstandard_port_technique(outbound_dominant):
    """T1048 for the exfiltration reading, T1571 for the control reading.

    The exfiltration reading needs measured bytes showing the flow was
    outbound-dominant; without them the control-channel reading stands.
    """
    return "T1048" if outbound_dominant else "T1571"


def transfer_technique(port, cfg):
    """A sustained outbound transfer: web service if over web ports."""
    return "T1567" if port in cfg["web_ports"] else "T1048"
