#!/usr/bin/env python3
"""Generate docs/assets/banner.svg for hermes-snitchboard.

The banner follows the house style used across the NeumannTechTips repositories:
a dark GitHub-toned canvas, monospace type, block-square lettering and a phosphor
green to amber gradient, with the project avatar set in a gradient ring.

Every address, host name and process name shown in the sample log is synthetic and
sits inside a range reserved for documentation: IPv4 192.0.2.0/24, 198.51.100.0/24
and 203.0.113.0/24 (RFC 5737), and names under example.com and example.net
(RFC 2606). Nothing in this image comes from a real machine.

The avatar is embedded as a base64 data URI because GitHub blocks external
references from inside an SVG, so a linked image would not render.

Usage:  python3 gen_banner.py        reads logo.png, writes banner.svg
"""

import base64
from pathlib import Path
from xml.sax.saxutils import escape

HERE = Path(__file__).parent
W, H = 860, 478

BG = "#0d1117"
BORDER = "#30363d"
GREEN = "#4af626"
AMBER = "#ffb000"
RED = "#ff5f56"
GREY = "#8b949e"
TEXT = "#c9d1d9"
MONO = (
    "ui-monospace, SFMono-Regular, Menlo, Consolas, "
    "'DejaVu Sans Mono', 'Liberation Mono', monospace"
)

# Five by five block font, limited to the glyphs this banner needs.
GLYPHS = {
    "S": ("01111", "10000", "01110", "00001", "11110"),
    "N": ("10001", "11001", "10101", "10011", "10001"),
    "I": ("11111", "00100", "00100", "00100", "11111"),
    "T": ("11111", "00100", "00100", "00100", "00100"),
    "C": ("01110", "10001", "10000", "10001", "01110"),
    "H": ("10001", "10001", "11111", "10001", "10001"),
    "B": ("11110", "10001", "11110", "10001", "11110"),
    "O": ("01110", "10001", "10001", "10001", "01110"),
    "A": ("01110", "10001", "11111", "10001", "10001"),
    "R": ("11110", "10001", "11110", "10100", "10011"),
    "D": ("11110", "10001", "10001", "10001", "11110"),
}

WORD = "SNITCHBOARD"
CELL = 10          # square size
PITCH = 11         # square size plus gap
WORD_TOP = 150

# (time, verdict, process, destination, note, colour) - synthetic throughout
LOG = [
    ("09:14:02", "ALLOW", "agent-core", "198.51.100.24:443", "llm-provider.example.com", GREEN),
    ("09:15:00", "BEACON", "sync-daemon", "192.0.2.77:443", "jitter 4.1%  every 60s", AMBER),
    ("09:15:31", "NOVEL", "agent-core", "203.0.113.150:8443", "rarity 100  first sighting", AMBER),
    ("09:16:12", "DENY", "unknown", "198.51.100.200:4444", "T1571  non-standard port", RED),
]


def lerp(a: str, b: str, t: float) -> str:
    """Blend two hex colours."""
    ca = [int(a[i:i + 2], 16) for i in (1, 3, 5)]
    cb = [int(b[i:i + 2], 16) for i in (1, 3, 5)]
    return "#%02x%02x%02x" % tuple(round(x + (y - x) * t) for x, y in zip(ca, cb))


def avatar_data_uri() -> str:
    raw = (HERE / "logo.png").read_bytes()
    return "data:image/png;base64," + base64.b64encode(raw).decode("ascii")


def wordmark(x0: int, y0: int) -> list[str]:
    """Block lettering, coloured left to right across the whole word."""
    out = []
    total = len(WORD) * 6 * PITCH - PITCH
    for i, ch in enumerate(WORD):
        rows = GLYPHS[ch]
        for r, row in enumerate(rows):
            for c, bit in enumerate(row):
                if bit != "1":
                    continue
                x = x0 + (i * 6 + c) * PITCH
                y = y0 + r * PITCH
                colour = lerp(GREEN, AMBER, (x - x0) / total)
                out.append(
                    f'<rect x="{x}" y="{y}" width="{CELL}" height="{CELL}" rx="1.5" fill="{colour}"/>'
                )
    return out


def shield(x: float, y: float, colour: str, scale: float = 1.0) -> str:
    """A small shield mark, used as a row of accents beside the avatar."""
    w, h = 13 * scale, 16 * scale
    d = (
        f"M {x} {y + h * 0.18} L {x + w / 2} {y} L {x + w} {y + h * 0.18} "
        f"L {x + w} {y + h * 0.55} Q {x + w} {y + h} {x + w / 2} {y + h} "
        f"Q {x} {y + h} {x} {y + h * 0.55} Z"
    )
    tick = (
        f'<path d="M {x + w * 0.28} {y + h * 0.5} L {x + w * 0.45} {y + h * 0.66} '
        f'L {x + w * 0.74} {y + h * 0.33}" fill="none" stroke="{BG}" '
        f'stroke-width="{2.1 * scale}" stroke-linecap="round" stroke-linejoin="round"/>'
    )
    return f'<path d="{d}" fill="{colour}"/>' + tick


def build() -> str:
    cx, cy, r = 84, 70, 44
    p = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" '
        f'viewBox="0 0 {W} {H}" role="img" '
        f'aria-label="Snitchboard: tamper-evident outbound connection audit for Hermes Agent, '
        f'shown with a sample connection log of allow, beacon, novel and deny entries">',
        "<defs>",
        f'<linearGradient id="ga" x1="0" y1="0" x2="1" y2="0">'
        f'<stop offset="0" stop-color="{GREEN}"/><stop offset="1" stop-color="{AMBER}"/></linearGradient>',
        f'<clipPath id="avatar"><circle cx="{cx}" cy="{cy}" r="{r - 3}"/></clipPath>',
        "</defs>",
        f'<rect x="0.5" y="0.5" width="{W - 1}" height="{H - 1}" rx="12" fill="{BG}" stroke="{BORDER}"/>',
    ]

    # avatar in a gradient ring
    d = r - 3
    p.append(
        f'<image href="{avatar_data_uri()}" x="{cx - d}" y="{cy - d}" '
        f'width="{d * 2}" height="{d * 2}" clip-path="url(#avatar)" '
        f'preserveAspectRatio="xMidYMid slice"/>'
    )
    p.append(f'<circle cx="{cx}" cy="{cy}" r="{d}" fill="none" stroke="url(#ga)" stroke-width="3"/>')

    # shield accents, echoing the three marks on the sibling repository banner
    for i, colour in enumerate((GREEN, lerp(GREEN, AMBER, 0.55), AMBER)):
        p.append(shield(164 + i * 30, 58, colour, 1.15))

    # strapline beside the avatar
    p.append(
        f'<text x="164" y="100" font-family="{MONO}" font-size="12.5" letter-spacing="1.6" '
        f'fill="{GREY}">read-only  ·  local  ·  no telemetry</text>'
    )

    # wordmark
    word_width = len(WORD) * 6 * PITCH - PITCH
    p += wordmark(round((W - word_width) / 2), WORD_TOP)

    # spaced subtitle
    p.append(
        f'<text x="{W / 2}" y="{WORD_TOP + 5 * PITCH + 34}" text-anchor="middle" '
        f'font-family="{MONO}" font-size="15" letter-spacing="7" font-weight="700" '
        f'fill="{GREEN}">e g r e s s · a u d i t</text>'
    )

    rule_y = WORD_TOP + 5 * PITCH + 54
    p.append(f'<rect x="150" y="{rule_y}" width="{W - 300}" height="2" fill="url(#ga)" opacity="0.8"/>')

    # description
    p.append(
        f'<text x="{W / 2}" y="{rule_y + 30}" text-anchor="middle" font-family="{MONO}" '
        f'font-size="14" fill="{TEXT}">tamper-evident outbound connection audit for '
        f'<tspan fill="{AMBER}">Hermes Agent</tspan></text>'
    )
    p.append(
        f'<text x="{W / 2}" y="{rule_y + 54}" text-anchor="middle" font-family="{MONO}" '
        f'font-size="13" letter-spacing="1.4" fill="{GREY}">'
        f'<tspan fill="{GREEN}">OpenSnitch</tspan> evidence  ·  mapped to MITRE ATT&amp;CK  ·  '
        f'hash-chained runs</text>'
    )

    # sample log
    y = rule_y + 82
    for ts, verdict, proc, dest, note, colour in LOG:
        p.append(
            f'<text x="40" y="{y}" font-family="{MONO}" font-size="13" fill="{GREY}">{escape(ts)}</text>'
            f'<text x="116" y="{y}" font-family="{MONO}" font-size="13" font-weight="700" '
            f'fill="{colour}">{escape(verdict)}</text>'
            f'<text x="196" y="{y}" font-family="{MONO}" font-size="13" fill="{TEXT}">{escape(proc)}</text>'
            f'<text x="316" y="{y}" font-family="{MONO}" font-size="13" fill="{TEXT}">{escape(dest)}</text>'
            f'<text x="512" y="{y}" font-family="{MONO}" font-size="13" fill="{GREY}">{escape(note)}</text>'
        )
        y += 23

    # integrity footer
    p.append(f'<rect x="40" y="{H - 46}" width="{W - 80}" height="1" fill="{BORDER}"/>')
    p.append(
        f'<text x="40" y="{H - 20}" font-family="{MONO}" font-size="13" font-weight="700" '
        f'fill="{GREEN}">chain intact</text>'
        f'<text x="162" y="{H - 20}" font-family="{MONO}" font-size="13" fill="{GREY}">'
        f'sha256:3f9a41c7...e08b   run 24 of 24   ·   sample data</text>'
    )

    p.append("</svg>")
    return "\n".join(p) + "\n"


if __name__ == "__main__":
    out = HERE / "banner.svg"
    out.write_text(build(), encoding="utf-8")
    print(f"wrote {out} ({out.stat().st_size} bytes)")
