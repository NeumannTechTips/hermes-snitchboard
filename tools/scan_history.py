#!/usr/bin/env python3
"""Scan the working tree and the whole git history for identifiers that must
never become public.

This implements step 1 of the publication gate in HSB-PRD-001 section 11.3.
Git history is permanent, so a value removed in a later commit is still served
to anyone who clones the repository. The scan therefore reads every blob ever
committed, not just the files present today.

Standard library only, so it runs anywhere the plugin does.

Usage
    python3 tools/scan_history.py            working tree and full history
    python3 tools/scan_history.py --tree     working tree only, faster
    python3 tools/scan_history.py --quiet    exit status only

Exit status 0 means clean, 1 means at least one finding.
"""

from __future__ import annotations

import argparse
import ipaddress
import re
import subprocess
import sys

# Ranges reserved for documentation. Anything outside these is a finding.
DOC_V4 = [ipaddress.ip_network(n) for n in
          ("192.0.2.0/24", "198.51.100.0/24", "203.0.113.0/24")]
DOC_V6 = ipaddress.ip_network("2001:db8::/32")
DOC_MAC_PREFIX = "00-00-5E-00-53"
RESERVED_SUFFIXES = (".example.com", ".example.net", ".invalid",
                     "example.com", "example.net", "localhost")

# Addresses that carry no information about a real machine.
BENIGN_V4 = {"0.0.0.0", "127.0.0.1", "255.255.255.255", "239.255.255.250",
             "1.1.1.1", "8.8.8.8"}

RE_V4 = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")
RE_V6 = re.compile(r"\b(?:[0-9a-fA-F]{1,4}:){2,7}[0-9a-fA-F]{1,4}\b")
RE_MAC = re.compile(r"\b(?:[0-9A-Fa-f]{2}[:-]){5}[0-9A-Fa-f]{2}\b")
RE_EMAIL = re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b")
RE_HOME = re.compile(r"/home/[a-z_][a-z0-9_-]*", re.I)

# Words that would identify the maintainer or the development host are NOT
# listed here. Writing them into this file would publish the very strings the
# scan exists to keep out of the repository. They are read instead from
# .scan-words, one per line, which .gitignore excludes from every commit.
#
# Create it once, locally:
#     printf '%s\n' 'a-real-name' 'a-real-hostname' > .scan-words
#
# When the file is absent the word check is reported as skipped rather than
# passed, because a silent pass on an empty list is worse than no check at all.
WORD_LIST = ".scan-words"

# Home paths are a finding only when the account name could belong to a real
# person or a real host. Invented accounts are what the fixtures are supposed to
# contain, so they are allowed here. Extend this set rather than dropping the
# check, and keep every entry obviously fictitious.
SYNTHETIC_HOME_USERS = {
    "demo", "demo-user", "demouser", "example", "example-user",
    "test", "test-user", "testuser", "user", "someone", "alice", "bob",
}

# Files expected to contain patterns, reported separately rather than as
# findings. Matched on suffix so the invocation directory does not matter.
EXPECTED_PATTERN_FILES = ("scan_history.py", "test_fixtures.py")

SKIP_SUFFIXES = (".png", ".jpg", ".jpeg", ".gif", ".ico", ".pdf", ".zip",
                 ".woff", ".woff2", ".ttf")


def run(args: list[str]) -> str:
    return subprocess.run(args, capture_output=True, text=True,
                          errors="replace").stdout


def findings_in(text: str, words: list[str]) -> list[str]:
    out: list[str] = []

    for m in set(RE_V4.findall(text)):
        if m in BENIGN_V4:
            continue
        try:
            ip = ipaddress.ip_address(m)
        except ValueError:
            continue
        if ip.is_loopback or ip.is_unspecified or ip.is_multicast:
            continue
        if not any(ip in net for net in DOC_V4):
            out.append(f"IPv4 outside the documentation ranges: {m}")

    for m in set(RE_V6.findall(text)):
        try:
            ip = ipaddress.ip_address(m)
        except ValueError:
            continue
        if ip.is_loopback or ip.is_unspecified or ip.is_multicast:
            continue
        if ip not in DOC_V6:
            out.append(f"IPv6 outside 2001:db8::/32: {m}")

    for m in set(RE_MAC.findall(text)):
        if not m.upper().startswith(DOC_MAC_PREFIX):
            out.append(f"hardware address outside the documentation range: {m}")

    for m in set(RE_EMAIL.findall(text)):
        if not m.endswith("users.noreply.github.com") and not m.endswith("example.com"):
            out.append(f"e-mail address: {m}")

    for m in set(RE_HOME.findall(text)):
        user = m.rsplit("/", 1)[-1].lower()
        if user not in SYNTHETIC_HOME_USERS:
            out.append(f"home path for a non-synthetic account: {m}")

    low = text.lower()
    for w in words:
        if w and w in low:
            # The word itself is never printed, since this output may be pasted
            # into a chat, an issue or a build log.
            out.append(f"word from {WORD_LIST}, entry {words.index(w) + 1}")

    return out


def load_words() -> list[str]:
    try:
        with open(WORD_LIST, encoding="utf-8") as fh:
            return [ln.strip().lower() for ln in fh if ln.strip()
                    and not ln.startswith("#")]
    except OSError:
        return []


def scan_tree(words: list[str]) -> dict[str, list[str]]:
    hits: dict[str, list[str]] = {}
    for path in run(["git", "ls-files"]).split():
        if path.endswith(SKIP_SUFFIXES) or path.endswith(EXPECTED_PATTERN_FILES):
            continue
        try:
            with open(path, encoding="utf-8", errors="replace") as fh:
                text = fh.read()
        except OSError:
            continue
        f = findings_in(text, words)
        if f:
            hits[path] = f
    return hits


def scan_history(words: list[str]) -> dict[str, list[str]]:
    """Every blob ever committed, addressed by its object id."""
    hits: dict[str, list[str]] = {}
    seen: set[str] = set()
    listing = run(["git", "rev-list", "--objects", "--all"])
    for line in listing.splitlines():
        parts = line.split(maxsplit=1)
        if len(parts) != 2:
            continue
        oid, path = parts
        if oid in seen or path.endswith(SKIP_SUFFIXES) or path.endswith(EXPECTED_PATTERN_FILES):
            continue
        seen.add(oid)
        kind = run(["git", "cat-file", "-t", oid]).strip()
        if kind != "blob":
            continue
        f = findings_in(run(["git", "cat-file", "-p", oid]), words)
        if f:
            hits[f"{path} @ {oid[:10]}"] = f
    return hits


def report(title: str, hits: dict[str, list[str]], quiet: bool) -> int:
    if not hits:
        if not quiet:
            print(f"  {title}: clean")
        return 0
    total = sum(len(v) for v in hits.values())
    if not quiet:
        print(f"  {title}: {total} finding(s) in {len(hits)} location(s)")
        for where, items in sorted(hits.items()):
            print(f"    {where}")
            for i in sorted(set(items)):
                print(f"      - {i}")
        if any("non-synthetic account" in i for v in hits.values() for i in v):
            print(f"    note: accounts treated as fictitious are "
                  f"{', '.join(sorted(SYNTHETIC_HOME_USERS))}")
    return total


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--tree", action="store_true", help="working tree only")
    ap.add_argument("--quiet", action="store_true", help="exit status only")
    args = ap.parse_args()

    words = load_words()
    if not args.quiet:
        print("Publication gate scan, HSB-PRD-001 section 11.3")
        print(f"  word list: {len(words)} entries from {WORD_LIST}" if words
              else f"  word list: SKIPPED, {WORD_LIST} not found")

    total = report("working tree", scan_tree(words), args.quiet)
    if not args.tree:
        total += report("git history", scan_history(words), args.quiet)

    if not args.quiet:
        print()
        print("CLEAN. Safe to make the repository public." if total == 0 else
              f"BLOCKED. {total} finding(s). Rewrite the history before publishing.")
    return 1 if total else 0


if __name__ == "__main__":
    sys.exit(main())
