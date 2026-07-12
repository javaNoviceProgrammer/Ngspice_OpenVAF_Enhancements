#!/usr/bin/env python3
"""Enhancement-169 figure: interactive syntax highlighting.

Renders, as a terminal window, the ACTUAL ANSI-colored output produced by
ngspice's `synhl' command (the same coloring engine that colors the live prompt),
so the figure reflects real output rather than a hand-drawn mock. The lower strip
shows the as-you-type behavior: a word stays neutral while it is a valid command
prefix, turns green the moment it is a complete command, and a typo that cannot
become a command shows red.

Run:  python3 make_syntaxhl_fig.py   ->  syntaxhl.png
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

# ANSI SGR code -> display color on a dark terminal
ANSI = {"0": "#d6d6d6", "31": "#ff5f56", "32": "#4ad83a", "33": "#e8c33a",
        "35": "#d06fce", "36": "#3fc4cf"}
DEFAULT = "#d6d6d6"
PROMPT = "#6f9bff"
_sgr = re.compile(r"\033\[([0-9]*)m")


def synhl(line):
    """Return ngspice's colorized rendering of `line` as a list of (text,color)."""
    deck = f"* f\n.control\nsynhl {line}\n.endc\n.end\n"
    with tempfile.NamedTemporaryFile("w", suffix=".cir", delete=False) as f:
        f.write(deck)
        path = f.name
    try:
        out = subprocess.run([NGSPICE, "-b", path], capture_output=True, text=True).stdout
    finally:
        os.unlink(path)
    raw = next((l for l in out.splitlines() if "\033[" in l), line)
    spans, color, i = [], DEFAULT, 0
    for m in _sgr.finditer(raw):
        if m.start() > i:
            spans.append((raw[i:m.start()], color))
        code = m.group(1) or "0"
        color = ANSI.get(code, DEFAULT)
        i = m.end()
    if i < len(raw):
        spans.append((raw[i:], color))
    return spans


GALLERY = [
    "tran 1n 100n uic",
    "ac dec 10 1 1meg",
    "plot v(out) v(in)",
    "let rout = v(out)/i(vin)",
    "write results.raw all",
    'echo "hello world" -foo 3.14',
    "boguscommand 1 2 3",
]
# as-you-type: each successive keystroke of a word, plus a typo
TYPING = [("plo", "(still typing... valid prefix)"),
          ("plot", "(complete command -> green)"),
          ("plt", "(cannot become a command -> red)")]

FP = FontProperties(family="monospace", size=13)
CW = 0.0104   # monospace character width in axes fraction (tuned for the layout)


def draw_line(ax, y, prompt, spans, dim=False):
    x = 0.03
    if prompt:
        ax.text(x, y, prompt, color=PROMPT, fontproperties=FP,
                transform=ax.transAxes, va="center")
        x += len(prompt) * CW
    for text, color in spans:
        ax.text(x, y, text, color=("#666" if dim else color), fontproperties=FP,
                transform=ax.transAxes, va="center")
        x += len(text) * CW


fig = plt.figure(figsize=(11, 6.4))
fig.patch.set_facecolor("#1b1b20")

# main terminal panel
axT = fig.add_axes([0.0, 0.34, 1.0, 0.62])
axT.set_facecolor("#141418")
axT.set_xticks([]); axT.set_yticks([])
for s in axT.spines.values():
    s.set_color("#33333b")
axT.text(0.03, 0.93, "ngspice  —  interactive prompt", color="#9aa0aa",
         fontproperties=FontProperties(family="monospace", size=11),
         transform=axT.transAxes, va="center")

y = 0.80
prompt = "ngspice 1 -> "
for i, cmd in enumerate(GALLERY):
    draw_line(axT, y, prompt.replace("1", str(i + 1)), synhl(cmd))
    y -= 0.115

# legend of token colors
leg = [("command", "#4ad83a"), ("unknown", "#ff5f56"), ("number", "#e8c33a"),
       ('"string"', "#d06fce"), ("-option", "#3fc4cf")]
lx = 0.03
for label, color in leg:
    axT.text(lx, 0.03, "■", color=color, fontproperties=FP, transform=axT.transAxes)
    axT.text(lx + 0.022, 0.03, label, color="#9aa0aa",
             fontproperties=FontProperties(family="monospace", size=10),
             transform=axT.transAxes)
    lx += 0.022 + len(label) * CW + 0.03

# as-you-type strip
axB = fig.add_axes([0.0, 0.03, 1.0, 0.24])
axB.set_facecolor("#141418")
axB.set_xticks([]); axB.set_yticks([])
for s in axB.spines.values():
    s.set_color("#33333b")
axB.text(0.03, 0.88, "as you type  (the word is re-colored on every keystroke)",
         color="#9aa0aa", fontproperties=FontProperties(family="monospace", size=11),
         transform=axB.transAxes, va="center")
yy = 0.62
for word, note in TYPING:
    spans = synhl(word)
    draw_line(axB, yy, "ngspice -> ", spans)
    axB.text(0.34, yy, note, color="#777c86",
             fontproperties=FontProperties(family="monospace", size=11),
             transform=axB.transAxes, va="center")
    yy -= 0.235

out = os.path.join(HERE, "syntaxhl.png")
fig.savefig(out, dpi=110, facecolor=fig.get_facecolor())
print("wrote", out)
