#!/usr/bin/env python3
"""Enhancement-170 figure: semantic syntax highlighting.

Renders, as a terminal window, the ACTUAL ANSI-colored output of ngspice's
`synhl' command -- the same engine that colors the live prompt -- run AFTER a
circuit has been simulated, so its node signals really exist and can be checked.
It shows: a valid signal stays the default color while an unknown one turns red;
an invalid signal inside an otherwise-valid expression reddens only that signal;
a genuinely malformed expression reddens as a whole; and (bottom) error output
is drawn in red.

Run:  python3 make_semantic_fig.py   ->  syntaxhl_semantic.png
"""
import os
import re
import subprocess
import sys
import tempfile

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.font_manager import FontProperties

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from _setup import NG as NGSPICE

ANSI = {"0": "#d6d6d6", "31": "#ff5f56", "32": "#4ad83a", "33": "#e8c33a",
        "35": "#d06fce", "36": "#3fc4cf"}
DEFAULT = "#d6d6d6"
PROMPT = "#6f9bff"
_sgr = re.compile(r"\033\[([0-9]*)m")


def spans_of(raw):
    """Parse an ANSI-colored line into a list of (text, color) spans."""
    spans, color, i = [], DEFAULT, 0
    for m in _sgr.finditer(raw):
        if m.start() > i:
            spans.append((raw[i:m.start()], color))
        color = ANSI.get(m.group(1) or "0", DEFAULT)
        i = m.end()
    if i < len(raw):
        spans.append((raw[i:], color))
    return spans


def synhl_after_run(lines):
    """Run `synhl <line>' for each line, in a deck that first simulates a small
    circuit (so its node signals a, b exist), and return the colored spans."""
    body = "".join("synhl " + l + "\n" for l in lines)
    deck = ("* semantic\nv1 a 0 dc 1\nr1 a b 1k\nr2 b 0 1k\n.op\n"
            ".control\nrun\n" + body + ".endc\n.end\n")
    with tempfile.NamedTemporaryFile("w", suffix=".cir", delete=False) as f:
        f.write(deck)
        path = f.name
    try:
        out = subprocess.run([NGSPICE, "-b", path], capture_output=True, text=True).stdout
    finally:
        os.unlink(path)
    colored = [l for l in out.splitlines() if "\033[" in l]
    return [spans_of(l) for l in colored]


LINES = [
    ("print v(a) v(b)",          "valid signals -> default color"),
    ("print v(a) + v(zzz)",      "unknown signal -> only v(zzz) red"),
    ("print sqrt(v(a)) - v(bad)", "unknown signal inside a function -> red"),
    ("plot v(a)*/v(b)",          "malformed expression -> whole red"),
    ("plot v(a) vs time",        "keywords (vs) are not flagged"),
]
rows = synhl_after_run([l for l, _ in LINES])
# the error line (bottom) -- rendered red, as it appears at an interactive tty
ERR = [("Warning: v(zzz) is not available or has zero length.", ANSI["31"])]

FP = FontProperties(family="monospace", size=13)
NOTE = FontProperties(family="monospace", size=10)
CW = 0.0092


def draw(ax, y, prompt, spans, note=None):
    x = 0.03
    if prompt:
        ax.text(x, y, prompt, color=PROMPT, fontproperties=FP,
                transform=ax.transAxes, va="center")
        x += len(prompt) * CW
    for text, color in spans:
        ax.text(x, y, text, color=color, fontproperties=FP,
                transform=ax.transAxes, va="center")
        x += len(text) * CW
    if note:
        ax.text(0.60, y, "# " + note, color="#777c86", fontproperties=NOTE,
                transform=ax.transAxes, va="center")


fig = plt.figure(figsize=(12.5, 5.6))
fig.patch.set_facecolor("#1b1b20")
ax = fig.add_axes([0.0, 0.0, 1.0, 1.0])
ax.set_facecolor("#141418")
ax.set_xticks([]); ax.set_yticks([])
for s in ax.spines.values():
    s.set_color("#33333b")

ax.text(0.03, 0.94, "ngspice  —  interactive prompt   (semantic highlighting)",
        color="#9aa0aa", fontproperties=FontProperties(family="monospace", size=11),
        transform=ax.transAxes, va="center")

y = 0.82
for i, (spans, (_, note)) in enumerate(zip(rows, LINES)):
    draw(ax, y, f"ngspice {i+1} -> ", spans, note)
    y -= 0.108

# the command that errors, then its red error output
draw(ax, y - 0.02, "ngspice 6 -> ", spans_of("\033[32mprint\033[0m \033[31mv(zzz)\033[0m"))
y -= 0.13
draw(ax, y, "", ERR)

# legend
leg = [("valid signal", DEFAULT), ("invalid signal / expr", ANSI["31"]),
       ("number", ANSI["33"]), ("error output", ANSI["31"])]
lx = 0.03
for label, color in leg:
    ax.text(lx, 0.05, "■", color=color, fontproperties=FP, transform=ax.transAxes)
    ax.text(lx + 0.02, 0.05, label, color="#9aa0aa", fontproperties=NOTE,
            transform=ax.transAxes)
    lx += 0.02 + len(label) * CW + 0.04

out = os.path.join(HERE, "syntaxhl_semantic.png")
fig.savefig(out, dpi=110, facecolor=fig.get_facecolor())
print("wrote", out)
