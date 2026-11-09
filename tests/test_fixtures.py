"""Safety net for everything under fixtures/ (PRD SP6, SC4, SC7).

The build fails if any address, hardware address or name in fixtures/ falls
outside the ranges reserved for documentation, or if a process, account or
home directory appears that is not on the invented list below. The scanner
is tested against known-bad values too, so a weakened pattern is caught.
"""

import importlib.util
import ipaddress
import json
import re
import tempfile
import unittest
from pathlib import Path

from snitchboard import chain, schema

REPO = Path(__file__).resolve().parent.parent
FIXTURES = REPO / "fixtures"

IPV4_NETS = [ipaddress.ip_network(n) for n in
             ("192.0.2.0/24", "198.51.100.0/24", "203.0.113.0/24")]
IPV6_NET = ipaddress.ip_network("2001:db8::/32")
DOMAINS = ("example.com", "example.net")
MAC_PREFIX = "00-00-5E-00-53-"

# Invented names. Adding one is a deliberate edit, reviewed like any other.
PROCESSES = {
    "/usr/bin/web-browser", "/usr/libexec/name-resolver", "/usr/bin/note-sync",
    "/usr/libexec/update-checker", "/usr/sbin/clock-sync",
    "/home/demo-user/.local/bin/agent-runner", "/usr/local/bin/model-gateway",
    "/opt/widget/bin/widget-helper", "unattributed process",
}
ACCOUNTS = {"demo-user", "resolver-svc", "root", "clock-svc", "agent-svc"}
# Labels the engine itself writes when the firewall supplies no identity.
ENGINE_LABELS = {"unknown account"}
# Firewall rule operand names, which are dotted but are not host names.
OPERANDS = {"process.path", "dest.host", "dest.port"}

_DOTTED = re.compile(r"(?<![\w.])\d+(?:\.\d+){3}(?![\w.])")
_HEXCOLON = re.compile(r"(?<![\w:.])[0-9A-Fa-f]*(?::[0-9A-Fa-f]*){2,}(?![\w:])")
_MAC = re.compile(r"(?<![\w:.-])[0-9A-Fa-f]{2}([:-])[0-9A-Fa-f]{2}(?:\1[0-9A-Fa-f]{2}){4}(?![\w:-])")
_MAC_DOTTED = re.compile(r"(?<![\w.])[0-9A-Fa-f]{4}\.[0-9A-Fa-f]{4}\.[0-9A-Fa-f]{4}(?![\w.])")
_NAME = re.compile(r"(?<![\w.@-])((?:[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?\.)+[A-Za-z]{2,63})(?![\w-])")
_TIME = re.compile(r"^\d{2}:\d{2}(?::\d{2})?$")
_HOME = re.compile(r"/home/([^/\s\"]+)")


def scan_text(text):
    """Return every value in `text` that falls outside the permitted ranges."""
    bad = []
    for m in _DOTTED.finditer(text):
        try:
            addr = ipaddress.ip_address(m.group(0))
        except ValueError:
            bad.append(f"malformed dotted address {m.group(0)}")
            continue
        if not any(addr in net for net in IPV4_NETS):
            bad.append(f"IPv4 outside documentation ranges: {addr}")
    for m in _HEXCOLON.finditer(text):
        token = m.group(0)
        if _TIME.match(token) or _MAC.fullmatch(token):
            continue
        try:
            addr = ipaddress.IPv6Address(token)
        except ValueError:
            bad.append(f"unparseable colon-separated value {token}")
            continue
        if addr not in IPV6_NET:
            bad.append(f"IPv6 outside 2001:db8::/32: {addr}")
    for m in _MAC.finditer(text):
        normal = m.group(0).upper().replace(":", "-")
        if not normal.startswith(MAC_PREFIX):
            bad.append(f"hardware address outside RFC 7042 range: {m.group(0)}")
    for m in _MAC_DOTTED.finditer(text):
        normal = m.group(0).replace(".", "").upper()
        if not normal.startswith("00005E0053"):
            bad.append(f"hardware address outside RFC 7042 range: {m.group(0)}")
    for m in _NAME.finditer(text):
        name = m.group(1).lower()
        if name in OPERANDS:
            continue
        if not any(name == d or name.endswith("." + d) for d in DOMAINS):
            bad.append(f"name outside example.com and example.net: {name}")
    if "@" in text:
        bad.append("an @ sign, which suggests an e-mail address or handle")
    for m in _HOME.finditer(text):
        if m.group(1) not in ACCOUNTS:
            bad.append(f"home directory of an account not on the invented list: {m.group(1)}")
    return bad


def fixture_files():
    return sorted(p for p in FIXTURES.rglob("*") if p.is_file())


def run_records():
    records = [json.loads(p.read_text(encoding="utf-8"))
               for p in sorted((FIXTURES / "runs").glob("*.json"))]
    return sorted(records, key=lambda r: r["integrity"]["run_index"])


class ScannerSelfTest(unittest.TestCase):
    def test_flags_values_outside_the_ranges(self):
        # Out of range on purpose, yet still reserved or unroutable, so the
        # samples themselves name nothing real.
        for sample in ("100.64.0.1", "10.0.0.1", "192.0.3.1", "999.1.1.1",
                       "2001:db9::1", "fe80::1", "2001:db8:::1",
                       "aa:bb:cc:dd:ee:ff", "00-00-5E-00-54-01", "0000.5e00.5401",
                       "mail.example.org", "host.lan.example", "host.invalid",
                       "example.com.test", "someone@example.com",
                       "/home/alice/.bashrc", "process.paths", "dest.hostname"):
            self.assertTrue(scan_text(f'"{sample}"'), f"not flagged: {sample}")

    def test_accepts_documentation_values(self):
        for sample in ("192.0.2.1", "198.51.100.255", "203.0.113.0", "2001:db8::1",
                       "2001:db8:20::14", "00-00-5E-00-53-FF", "00:00:5e:00:53:01",
                       "0000.5e00.53ab", "api.example.com", "example.net",
                       "2026-11-02T03:00:02+01:00", "239.6 s", "demo-1.0",
                       "/home/demo-user/.local/bin/agent-runner"):
            self.assertEqual(scan_text(f'"{sample}"'), [], sample)


class FixtureRanges(unittest.TestCase):
    def test_only_json_files(self):
        others = [p.name for p in fixture_files() if p.suffix != ".json"]
        self.assertEqual(others, [])

    def test_every_value_is_in_a_documentation_range(self):
        problems = []
        for path in fixture_files():
            for issue in scan_text(path.read_text(encoding="utf-8")):
                problems.append(f"{path.relative_to(REPO)}: {issue}")
        self.assertEqual(problems, [])

    def test_processes_and_accounts_are_invented(self):
        problems = set()
        for record in run_records():
            if record["trimmed"]:
                continue
            for row in record["rows"]:
                if row["process"] is not None and row["process"] not in PROCESSES:
                    problems.add(f"process {row['process']}")
            agg = record["aggregates"]
            problems |= {f"process {p['what']}" for p in agg["procs"]
                         if p["what"] not in PROCESSES}
            problems |= {f"account {u['what']}" for u in agg["users"]
                         if u["what"] not in ACCOUNTS | ENGINE_LABELS}
            problems |= {f"account {a['user']}" for a in record["agents"]
                         if a["user"] and a["user"] not in ACCOUNTS}
            host = agg["node"]["hostname"]
            if not any(host.endswith("." + d) for d in DOMAINS):
                problems.add(f"node host name {host}")
        self.assertEqual(sorted(problems), [])


class FixtureContent(unittest.TestCase):
    def test_every_fixture_validates(self):
        for record in run_records():
            self.assertEqual(schema.validate(record), [], record["run_id"])

    def test_composition(self):
        records = run_records()
        self.assertGreaterEqual(len(records), 24)
        self.assertEqual(sum(1 for r in records if not r["trimmed"]), 2)
        self.assertEqual(sum(1 for r in records if r["status"] == "no_data"), 1)
        self.assertFalse(records[-1]["trimmed"])
        self.assertFalse(records[-2]["trimmed"])

    def test_chain_is_intact_across_the_set(self):
        result = chain.verify(run_records())
        self.assertTrue(result["intact"], result["summary"])
        self.assertEqual(result["sealed_links"], len(run_records()) - 2)

    def test_file_names_match_run_ids(self):
        for path in (FIXTURES / "runs").glob("*.json"):
            self.assertEqual(path.stem, json.loads(path.read_text())["run_id"])

    def test_generator_reproduces_the_committed_fixtures(self):
        spec = importlib.util.spec_from_file_location("gen_demo", REPO / "tools" / "gen_demo.py")
        gen = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(gen)
        with tempfile.TemporaryDirectory() as tmp:
            gen.write(tmp)
            fresh = sorted(p.relative_to(tmp) for p in Path(tmp).rglob("*") if p.is_file())
            committed = sorted(p.relative_to(FIXTURES) for p in fixture_files())
            self.assertEqual(fresh, committed)
            for rel in committed:
                self.assertEqual((Path(tmp) / rel).read_bytes(),
                                 (FIXTURES / rel).read_bytes(), str(rel))


if __name__ == "__main__":
    unittest.main()
