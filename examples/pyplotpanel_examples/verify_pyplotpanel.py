#!/usr/bin/env python3
"""
verify_pyplotpanel.py -- verifies Enhancement-98 (pyplot multi-panel subplots +
matplotlib style sheets), through the committed ngspice.

`set pyplot_subplots=N` renders the traces as stacked subplots sharing the
x-axis, N traces per panel (0/unset = a single axis). `set pyplot_style=<name>`
applies a matplotlib style sheet ("dark" aliases dark_background). `vs` still
means the x-axis vector (ngspice semantics), so it is not a panel separator.

  [1] baseline: a single axis -> plt.subplots(1, 1, ...)
  [2] pyplot_subplots=1: one trace per panel -> plt.subplots(3, 1, ...) for 3
  [3] pyplot_subplots=2: two traces per panel -> plt.subplots(2, 1, ...) for 4
  [4] pyplot_style=dark applies the dark_background style sheet
  [5] every case renders a valid PNG
"""
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from _setup import NG as NGSPICE
from _setup import check_both_solvers as _check_both_solvers; _check_both_solvers(__file__)  # verify under BOTH KLU and Sparse solvers

checks = passed = 0
def check(label, ok, detail=""):
    global checks, passed
    checks += 1; passed += bool(ok)
    print(f"[{'PASS' if ok else 'FAIL'}] {label}" + (f"  ({detail})" if detail and not ok else ""))

def is_png(name):
    p = os.path.join(HERE, name)
    if not os.path.isfile(p) or os.path.getsize(p) < 1000:
        return False
    with open(p, "rb") as f:
        return f.read(8) == b"\x89PNG\r\n\x1a\n"

def pyfile(name):
    p = os.path.join(HERE, name)
    return open(p).read() if os.path.isfile(p) else ""

ARTIFACTS = []
for base in ("base", "p1", "p2", "sty"):
    for ext in (".py", ".data", ".npy", ".png"):
        ARTIFACTS.append(base + ext)
for a in ARTIFACTS + ["deck.sp"]:
    p = os.path.join(HERE, a)
    if os.path.exists(p):
        os.remove(p)

deck = """* pyplot multi-panel demo (Enhancement-98)
V1 in 0 SIN(0 1 1k)
R1 in a 1k
C1 a 0 100n
R2 a b 1k
C2 b 0 100n
R3 b c 1k
C3 c 0 100n
.tran 5u 2m
.control
run
set pyplot_terminal=png
pyplot base v(a) v(b) v(c)
set pyplot_subplots=1
pyplot p1 v(a) v(b) v(c)
set pyplot_subplots=2
pyplot p2 v(in) v(a) v(b) v(c)
unset pyplot_subplots
set pyplot_style=dark
pyplot sty v(a)
.endc
.end
"""
with open(os.path.join(HERE, "deck.sp"), "w") as f:
    f.write(deck)
subprocess.run([NGSPICE, "-b", "deck.sp"], capture_output=True, text=True, cwd=HERE)

check("baseline uses a single axis (subplots(1, 1))",
      "plt.subplots(1, 1, sharex=True" in pyfile("base.py"))
check("pyplot_subplots=1 -> 3 stacked panels (subplots(3, 1))",
      "plt.subplots(3, 1, sharex=True" in pyfile("p1.py"))
check("pyplot_subplots=2 -> 2 panels for 4 traces (subplots(2, 1))",
      "plt.subplots(2, 1, sharex=True" in pyfile("p2.py"))
check("pyplot_style=dark applies dark_background",
      "plt.style.use('dark_background')" in pyfile("sty.py"))
check("all four render valid PNGs",
      all(is_png(n) for n in ("base.png", "p1.png", "p2.png", "sty.png")))

for a in ARTIFACTS + ["deck.sp"]:
    p = os.path.join(HERE, a)
    if os.path.exists(p):
        os.remove(p)

print(f"\n{passed}/{checks} checks passed")
raise SystemExit(0 if passed == checks else 1)
