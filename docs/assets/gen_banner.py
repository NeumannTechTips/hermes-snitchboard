#!/usr/bin/env python3
"""Generate docs/assets/banner.svg for hermes-snitchboard.

The banner follows the house style of the NeumannTechTips repositories: a dark
GitHub-style canvas, monospace type and a phosphor green to amber gradient.

Every address and name shown is synthetic and lies inside a documentation range:
IPv4 192.0.2.0/24, 198.51.100.0/24 and 203.0.113.0/24 (RFC 5737), and domains
under example.com and example.net (RFC 2606). Nothing here comes from a real host.

Usage:  python3 gen_banner.py            writes banner.svg beside this script
"""
from pathlib import Path
from xml.sax.saxutils import escape

W, H = 860, 330
BG, BORDER = "#0d1117", "#30363d"
GREEN, AMBER, RED, GREY, TEXT = "#4af626", "#ffb000", "#ff5f56", "#8b949e", "#c9d1d9"
MONO = "ui-monospace, SFMono-Regular, Menlo, Consolas, 'DejaVu Sans Mono', 'Liberation Mono', monospace"

# (time, verdict, process, destination, note) - all synthetic
LOG = [
    ("09:14:02", "ALLOW", "agent-core", "198.51.100.24:443", "llm-provider.example.com", GREEN),
    ("09:14:07", "ALLOW", "pkg-mgr", "203.0.113.9:443", "mirror.example.net", GREEN),
    ("09:15:00", "BEACON", "sync-daemon", "192.0.2.77:443", "jitter 4.1%  every 60s", AMBER),
    ("09:15:31", "NOVEL", "agent-core", "203.0.113.150:8443", "rarity 100  new destination", AMBER),
    ("09:16:12", "DENY", "unknown", "198.51.100.200:4444", "T1571  non-standard port", RED),
]


def build() -> str:
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}" '
        f'role="img" aria-label="Snitchboard: tamper-evident outbound connection audit for Hermes Agent">',
        "<defs>",
        '<linearGradient id="ga" x1="0" y1="0" x2="1" y2="0">'
        f'<stop offset="0" stop-color="{GREEN}"/><stop offset="1" stop-color="{AMBER}"/></linearGradient>',
        "</defs>",
        f'<rect x="0.5" y="0.5" width="{W-1}" height="{H-1}" rx="10" fill="{BG}" stroke="{BORDER}"/>',
    ]
    # title
    parts.append(
        f'<text x="40" y="82" font-family="{MONO}" font-size="54" font-weight="700" '
        f'letter-spacing="3" fill="url(#ga)">SNITCHBOARD</text>'
    )
    parts.append(
        f'<text x="42" y="112" font-family="{MONO}" font-size="15" fill="{TEXT}">'
        "tamper-evident outbound connection audit for Hermes Agent</text>"
    )
    parts.append(f'<rect x="40" y="128" width="{W-80}" height="2" fill="url(#ga)" opacity="0.85"/>')
    # synthetic log pane
    y = 160
    for ts, verdict, proc, dest, note, colour in LOG:
        parts.append(
            f'<text x="40" y="{y}" font-family="{MONO}" font-size="13.5" fill="{GREY}">{escape(ts)}</text>'
            f'<text x="116" y="{y}" font-family="{MONO}" font-size="13.5" font-weight="700" fill="{colour}">{escape(verdict)}</text>'
            f'<text x="196" y="{y}" font-family="{MONO}" font-size="13.5" fill="{TEXT}">{escape(proc)}</text>'
            f'<text x="316" y="{y}" font-family="{MONO}" font-size="13.5" fill="{TEXT}">{escape(dest)}</text>'
            f'<text x="512" y="{y}" font-family="{MONO}" font-size="13.5" fill="{GREY}">{escape(note)}</text>'
        )
        y += 24
    # integrity footer
    parts.append(f'<rect x="40" y="{H-52}" width="{W-80}" height="1" fill="{BORDER}"/>')
    parts.append(
        f'<text x="40" y="{H-26}" font-family="{MONO}" font-size="13.5" fill="{GREEN}">'
        "chain intact</text>"
        f'<text x="162" y="{H-26}" font-family="{MONO}" font-size="13.5" fill="{GREY}">'
        "sha256:3f9a41c7...e08b  run 24 of 24  |  mapped to MITRE ATT&amp;CK  |  demo data</text>"
    )
    parts.append("</svg>")
    return "\n".join(parts) + "\n"


if __name__ == "__main__":
    out = Path(__file__).with_name("banner.svg")
    out.write_text(build(), encoding="utf-8")
    print(f"wrote {out}")
