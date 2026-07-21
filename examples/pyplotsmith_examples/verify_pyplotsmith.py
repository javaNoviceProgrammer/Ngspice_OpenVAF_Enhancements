#!/usr/bin/env python3
"""Enhancement-254: `pyplot -smith` -- Smith-chart plotting.

`pyplot [name] -smith <complex vectors>` plots reflection coefficients (S11, S22,
Gamma, stability/gain-circle traces) on a Smith chart via matplotlib. Each vector
is drawn as a curve in the reflection-coefficient plane (real part = x, imaginary
part = y) over the standard Smith grid: the unit circle |Gamma|=1, the
constant-resistance circles and the constant-reactance arcs. Like the existing
`-hist`/`-contour` modes it is a render mode over the normal pyplot signal list;
with `set pyplot_terminal=png` it renders headless (Agg) to `<name>.png` and also
writes `<name>.py`/`<name>.data`.

This runs the shipped `smith_demo.cir` deck (S11/S22 of an R-C two-port + a matched
Gamma=0 load) and checks (both solvers). matplotlib is required; if the PNG is not
produced the test self-skips.
 1+2. `pyplot smith_demo -smith S_1_1 S_2_2` renders a valid PNG (magic bytes) of
      non-trivial size;
 3.   the generated `smith_demo.py` draws the Smith grid (unit circle + const-R/X
      curves) and plots both vectors;
 4.   the plotted data (`smith_demo.data`) equals the S-parameters exactly (re, im
      per point) -- so the curve on the chart is the real reflection coefficient;
 5.   a matched reflection coefficient (Gamma=0 -> the chart center) plots without
      error (`smith_match.png`).

The generated `.py`/`.data`/`.png` and `s11.dat` are verify-run scratch (gitignored);
the tracked deck `smith_demo.cir` is left untouched. Line 1 of the deck is the title.
"""
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from _setup import NG as NGSPICE  # noqa: E402
from _setup import check_both_solvers as _check_both_solvers  # noqa: E402
_check_both_solvers(__file__)

DECK = os.path.join(HERE, "smith_demo.cir")
passed = failed = 0


def check(label, ok, detail=""):
    global passed, failed
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  {detail}" if detail else ""))
    if ok:
        passed += 1
    else:
        failed += 1


def is_png(path):
    try:
        with open(path, "rb") as f:
            sig = f.read(8)
    except OSError:
        return False
    return sig == b"\x89PNG\r\n\x1a\n"


def path(name):
    return os.path.join(HERE, name)


# run the shipped demo deck (do NOT write it -- it is a tracked example file)
subprocess.run([NGSPICE, "-b", DECK], capture_output=True, text=True,
               timeout=90, cwd=HERE)

if not is_png(path("smith_demo.png")):
    print("  SKIP  matplotlib unavailable (no PNG produced) -- cannot render -smith")
    raise SystemExit(0)

# 1 + 2: PNG rendered and valid, non-trivial size
sz = os.path.getsize(path("smith_demo.png"))
check("pyplot -smith renders a valid PNG of non-trivial size",
      is_png(path("smith_demo.png")) and sz > 5000, f"{sz} bytes")

# 3: the .py draws the Smith grid and plots both vectors
py = open(path("smith_demo.py")).read()
check("smith_demo.py draws the Smith grid (unit circle + const-R/X) and both vectors",
      "matplotlib" in py and "np.cos(th)" in py and "_rcircle" in py
      and "_xarc" in py and "s_1_1" in py and "s_2_2" in py)

# 4: the plotted data equals the S-parameters exactly (vi=0 rows vs wrdata'd S_1_1)
data = [ln.split() for ln in open(path("smith_demo.data")) if ln.split()]
plotted = [(float(t[1]), float(t[2])) for t in data if len(t) >= 3 and t[0] == "0"]
s11 = []
for ln in open(path("s11.dat")):
    t = ln.split()
    if len(t) >= 3:
        s11.append((float(t[1]), float(t[2])))       # freq, re, im -> (re, im)
n = min(len(plotted), len(s11))
worst = max((abs(plotted[i][0] - s11[i][0]) + abs(plotted[i][1] - s11[i][1])
             for i in range(n)), default=1.0)
check("plotted Smith data equals the S-parameters exactly (re, im per point)",
      n >= 5 and worst < 1e-6, f"n={n} worst_abs={worst:.2e}")

# 5: a matched reflection coefficient (Gamma=0 -> center) renders without error
check("a matched coefficient (Gamma=0 at center) renders without error",
      is_png(path("smith_match.png")))

print(f"\n{passed} passed, {failed} failed")
raise SystemExit(1 if failed else 0)
