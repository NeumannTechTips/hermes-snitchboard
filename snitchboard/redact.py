"""Masking of addresses, host names, hardware addresses and process arguments.

Masks are pseudonyms numbered within one record (host-1, ip-1, mac-1), so a
masked view still shows that two rows share a destination without saying
which one. Numbering follows a canonical walk of the record, so the same
record always masks the same way. Home directory names are masked too,
because a path under /home names an account.
"""

import copy
import ipaddress
import re

_IPV4 = re.compile(r"(?<![\w.])(?:\d{1,3}\.){3}\d{1,3}(?![\w.])")
_IPV6 = re.compile(r"(?<![\w:.])[0-9A-Fa-f]{0,4}(?::[0-9A-Fa-f]{0,4}){2,7}(?![\w:])")
_MAC = re.compile(r"(?<![\w:-])[0-9A-Fa-f]{2}(?:([:-])[0-9A-Fa-f]{2})(?:\1[0-9A-Fa-f]{2}){4}(?![\w:-])")
_HOME = re.compile(r"/home/[^/\s]+")

# Fields whose string values are destination host names or addresses.
_HOST_KEYS = {"dst", "destination", "hostname"}
_HOST_LIST_KEYS = {"destinations"}
_HOST_TALLIES = {"hosts", "addrs"}
_PROCESS_KEYS = {"process", "processes"}


def mask_home(text):
    """Mask the account name in every /home/<name> segment of a string."""
    return _HOME.sub("/home/[user]", text)


class _Masker:
    def __init__(self):
        self.maps = {"host": {}, "ip": {}, "mac": {}}

    def token(self, kind, value):
        table = self.maps[kind]
        key = value.lower()
        if key not in table:
            table[key] = f"{kind}-{len(table) + 1}"
        return table[key]

    def host(self, value):
        try:
            ipaddress.ip_address(value)
        except ValueError:
            return self.token("host", value) if value else value
        return self.token("ip", value)

    def text(self, value, known_hosts, known_processes=()):
        # Whole process strings go first, so arguments quoted inside a title
        # or evidence line are masked along with the process field itself.
        for process in known_processes:
            if process in value:
                value = value.replace(process, self.process(process))
        value = _MAC.sub(lambda m: self.token("mac", m.group(0).replace(":", "-")), value)
        value = _IPV4.sub(lambda m: self._ip_or_keep(m.group(0)), value)
        value = _IPV6.sub(lambda m: self._ip_or_keep(m.group(0)), value)
        for host in known_hosts:
            if host in value:
                value = re.sub(rf"(?<![\w.-]){re.escape(host)}(?![\w-])",
                               self.token("host", host), value)
        return mask_home(value)

    def _ip_or_keep(self, candidate):
        try:
            ipaddress.ip_address(candidate)
        except ValueError:
            return candidate
        return self.token("ip", candidate)

    def process(self, value):
        if not value:
            return value
        path, _, args = value.partition(" ")
        path = mask_home(path)
        return f"{path} [arguments masked]" if args.strip() else path


def _known_processes(record):
    found = set()

    def visit(node, key=None):
        if isinstance(node, dict):
            if key == "procs" and isinstance(node.get("what"), str):
                found.add(node["what"])
            for k, v in node.items():
                visit(v, k)
        elif isinstance(node, list):
            for item in node:
                visit(item, key)
        elif isinstance(node, str) and key in _PROCESS_KEYS and " " in node:
            found.add(node)

    visit(record)
    # Longest first, so a string that contains another is replaced whole.
    return sorted((p for p in found if " " in p), key=lambda p: (-len(p), p))


def _known_hosts(record):
    hosts = set()

    def visit(node, key=None):
        if isinstance(node, dict):
            for k, v in node.items():
                if k in _HOST_TALLIES and isinstance(v, list):
                    hosts.update(i.get("what", "") for i in v if isinstance(i, dict))
                visit(v, k)
        elif isinstance(node, list):
            for item in node:
                visit(item, key)
        elif isinstance(node, str) and key in (_HOST_KEYS | _HOST_LIST_KEYS):
            hosts.add(node)

    visit(record)
    named = set()
    for h in hosts:
        try:
            ipaddress.ip_address(h)
        except ValueError:
            if h:
                named.add(h)
    # Longest first, so a name is never partly replaced by a shorter suffix.
    return sorted(named, key=lambda h: (-len(h), h))


def redact(record):
    """Return a masked deep copy of a run record. The input is not modified."""
    masker = _Masker()
    known = _known_hosts(record)
    processes = _known_processes(record)
    for host in sorted(known):
        masker.token("host", host)

    def walk(node, key=None, parent_key=None):
        if isinstance(node, dict):
            out = {}
            for k in sorted(node):
                v = node[k]
                if key in _HOST_TALLIES and k == "what" and isinstance(v, str):
                    out[k] = masker.host(v)
                else:
                    out[k] = walk(v, k, key)
            return out
        if isinstance(node, list):
            return [walk(item, key, parent_key) for item in node]
        if isinstance(node, str):
            if key in _HOST_KEYS or key in _HOST_LIST_KEYS:
                return masker.host(node)
            if key in _PROCESS_KEYS or (parent_key == "procs" and key == "what"):
                return masker.text(masker.process(node), known)
            if key in ("content_sha256", "prev_sha256", "sealed_sha256"):
                return node
            return masker.text(node, known, processes)
        return copy.deepcopy(node)

    masked = walk(record)
    # Destinations stay a sorted list so the masked record keeps its shape.
    if isinstance(masked.get("destinations"), list):
        masked["destinations"] = sorted(masked["destinations"])
    return masked
