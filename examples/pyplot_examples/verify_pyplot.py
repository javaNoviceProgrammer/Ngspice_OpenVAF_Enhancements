#!/usr/bin/env python3
"""
verify_pyplot.py -- verifies Enhancement-94 (the ngspice `pyplot` command,
matplotlib backend), end-to-end through the committed openvaf-r + ngspice.

`pyplot` mirrors ngspice's `gnuplot` command but renders with matplotlib: it
writes a `<file>.data` table and a `<file>.py` script and runs Python. With
`set pyplot_terminal=png` it renders headless (Agg) to `<file>.png`.

  [1] the OSDI model compiles and the transient runs
  [2] `pyplot rc v(out) v(in)` writes rc.py, rc.data and rc.png
  [3] rc.png is a valid PNG (magic bytes) of non-trivial size
  [4] the generated rc.py references both plotted vectors and uses matplotlib
  [5] an AC log-scale plot (`set type=...`/loglog) also renders a PNG

Enhancement-183 (this session's options):
  [E-183a] two omitted-file-name plots get DISTINCT names (pyplot, pyplot-2)
           with their own titles -- no interactive-window collision
  [E-183b] the .py/.data/.png are written next to the CIRCUIT FILE, not the cwd
  [E-183c] `set pyplot_linewidth=<w>` -> linewidth in the plot() calls
  [E-183d] `set pyplot_backend=<name>` -> matplotlib.use(<name>)

Enhancement-208:
  [E-208] `pyplot [name] -eye <expr> -ui <T>` runs the `eye` analysis and renders
          the folded eye as a persistence 2-D-histogram eye diagram (hist2d),
          honouring the same pyplot_* settings; the base name defaults to "eye".
"""
import os
import random
import re
import struct
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from _setup import VAF as OPENVAF, NG as NGSPICE
from _setup import check_both_solvers as _check_both_solvers; _check_both_solvers(__file__)  # verify under BOTH KLU and Sparse solvers

checks = passed = 0
def check(label, ok, detail=""):
    global checks, passed
    checks += 1; passed += bool(ok)
    print(f"[{'PASS' if ok else 'FAIL'}] {label}" + (f"  ({detail})" if detail and not ok else ""))

def is_png(path):
    if not os.path.isfile(path) or os.path.getsize(path) < 1000:
        return False
    with open(path, "rb") as f:
        sig = f.read(8)
    return sig == b"\x89PNG\r\n\x1a\n"

for stale in ("rc.png", "rc.py", "rc.data", "acmag.png", "acmag.py", "acmag.data"):
    p = os.path.join(HERE, stale)
    if os.path.exists(p):
        os.remove(p)

# compile the OSDI model
r = subprocess.run([OPENVAF, "rcload.va"], capture_output=True, text=True, cwd=HERE)
check("rcload.va compiles", r.returncode == 0, (r.stderr or r.stdout).strip()[:120])

# transient + pyplot to PNG
deck = """* pyplot transient demo (Enhancement-94)
.model rl rcload
V1 in 0 PULSE(0 1 0 1n 1n 1m 2m)
N1 in out rl
C1 out 0 1u
.tran 10u 3m
.control
pre_osdi rcload.osdi
run
set pyplot_terminal=png
pyplot rc v(out) v(in)
.endc
.end
"""
with open(os.path.join(HERE, "tran.sp"), "w") as f:
    f.write(deck)
r = subprocess.run([NGSPICE, "-b", "tran.sp"], capture_output=True, text=True, cwd=HERE)
log = r.stdout + r.stderr
check("transient runs and pyplot reports writing the PNG", "wrote rc.png" in log,
      log.strip()[-160:])
check("pyplot wrote rc.py, rc.data and rc.png",
      all(os.path.isfile(os.path.join(HERE, f)) for f in ("rc.py", "rc.data", "rc.png")))
check("rc.png is a valid PNG image", is_png(os.path.join(HERE, "rc.png")))
py = open(os.path.join(HERE, "rc.py")).read() if os.path.isfile(os.path.join(HERE, "rc.py")) else ""
check("rc.py uses matplotlib and plots both vectors",
      "matplotlib" in py and "v(out)" in py and "v(in)" in py)

# Enhancement-182: without explicit user limits the script must NOT pin the
# axes -- matplotlib's autoscaling + fig.tight_layout() frame the data (the
# old behavior forwarded ngspice's grid-rounded internal ranges).
check("E-182: auto plot has no set_xlim/set_ylim, relies on tight_layout",
      "set_xlim" not in py and "set_ylim" not in py and "tight_layout" in py)

# ... while explicit `xlimit`/`ylimit` on the command are still honored.
limdeck = deck.replace("pyplot rc v(out) v(in)",
                       "pyplot rclim v(out) v(in) xlimit 0 1m ylimit -1 1")
with open(os.path.join(HERE, "tranlim.sp"), "w") as f:
    f.write(limdeck)
r = subprocess.run([NGSPICE, "-b", "tranlim.sp"], capture_output=True, text=True, cwd=HERE)
pylim = (open(os.path.join(HERE, "rclim.py")).read()
         if os.path.isfile(os.path.join(HERE, "rclim.py")) else "")
check("E-182: explicit xlimit/ylimit still emit set_xlim and set_ylim",
      "set_xlim(0.000000e+00, 1.000000e-03)" in pylim and
      "set_ylim(-1.000000e+00, 1.000000e+00)" in pylim and
      is_png(os.path.join(HERE, "rclim.png")))
for f_ in ("tranlim.sp", "rclim.py", "rclim.data", "rclim.png"):
    try:
        os.remove(os.path.join(HERE, f_))
    except OSError:
        pass

# AC magnitude on a log x-axis
acdeck = """* pyplot AC demo
.model rl rcload
V1 in 0 DC 0 AC 1
N1 in out rl
C1 out 0 1u
.ac dec 20 1 1meg
.control
pre_osdi rcload.osdi
run
set pyplot_terminal=png
pyplot acmag db(v(out))
.endc
.end
"""
with open(os.path.join(HERE, "ac.sp"), "w") as f:
    f.write(acdeck)
subprocess.run([NGSPICE, "-b", "ac.sp"], capture_output=True, text=True, cwd=HERE)
check("AC log-scale plot renders a PNG", is_png(os.path.join(HERE, "acmag.png")))

# Enhancement-95: the file name is optional -- `pyplot v(out)` (no file name)
# defaults the base name to "pyplot".
nofndeck = """* pyplot without a file name
.model rl rcload
V1 in 0 PULSE(0 1 0 1n 1n 1m 2m)
N1 in out rl
C1 out 0 1u
.tran 10u 3m
.control
pre_osdi rcload.osdi
run
set pyplot_terminal=png
pyplot v(out)
.endc
.end
"""
with open(os.path.join(HERE, "nofn.sp"), "w") as f:
    f.write(nofndeck)
subprocess.run([NGSPICE, "-b", "nofn.sp"], capture_output=True, text=True, cwd=HERE)
check("pyplot with no file name defaults to 'pyplot.png'",
      is_png(os.path.join(HERE, "pyplot.png")))

# ---- Enhancement-183a: distinct default names for successive no-name plots ----
for f_ in ("pyplot.py", "pyplot.data", "pyplot.png",
           "pyplot-2.py", "pyplot-2.data", "pyplot-2.png"):
    try:
        os.remove(os.path.join(HERE, f_))
    except OSError:
        pass
twodeck = """* two no-name plots
.model rl rcload
V1 in 0 PULSE(0 1 0 1n 1n 1m 2m)
N1 in out rl
C1 out 0 1u
.tran 10u 3m
.control
pre_osdi rcload.osdi
run
set pyplot_terminal=png
pyplot v(out) title first
pyplot v(in) title second
.endc
.end
"""
with open(os.path.join(HERE, "two.sp"), "w") as f:
    f.write(twodeck)
subprocess.run([NGSPICE, "-b", "two.sp"], capture_output=True, text=True, cwd=HERE)
p1 = open(os.path.join(HERE, "pyplot.py")).read() if os.path.isfile(os.path.join(HERE, "pyplot.py")) else ""
p2 = open(os.path.join(HERE, "pyplot-2.py")).read() if os.path.isfile(os.path.join(HERE, "pyplot-2.py")) else ""
check("E-183a: two no-name plots -> distinct pyplot / pyplot-2 with own titles",
      is_png(os.path.join(HERE, "pyplot.png")) and is_png(os.path.join(HERE, "pyplot-2.png"))
      and "suptitle('first')" in p1 and "suptitle('second')" in p2)

# ---- Enhancement-183b: artifacts written next to the CIRCUIT FILE ----
for f_ in ("dir.py", "dir.data", "dir.png"):
    try:
        os.remove(os.path.join(HERE, f_))
    except OSError:
        pass
dirdeck = twodeck.replace("pyplot v(out) title first\npyplot v(in) title second",
                          "pyplot dir v(out)")
deckpath = os.path.join(HERE, "dir.sp")
with open(deckpath, "w") as f:
    f.write(dirdeck)
# run from the PARENT dir but give the deck by ABSOLUTE path -> outputs must
# land next to the deck (HERE), not in the cwd (the parent)
parent = os.path.dirname(HERE)
subprocess.run([NGSPICE, "-b", deckpath], capture_output=True, text=True, cwd=parent)
pydir = open(os.path.join(HERE, "dir.py")).read() if os.path.isfile(os.path.join(HERE, "dir.py")) else ""
check("E-183b: artifacts land next to the .cir (abs deck path, run from parent)",
      is_png(os.path.join(HERE, "dir.png"))
      and not os.path.exists(os.path.join(parent, "dir.png"))
      and os.path.join(HERE, "dir.data") in pydir)

# ---- Enhancement-183c: pyplot_linewidth ----
lwdeck = twodeck.replace(
    "set pyplot_terminal=png\npyplot v(out) title first\npyplot v(in) title second",
    "set pyplot_terminal=png\nset pyplot_linewidth=3.5\npyplot lw v(out)")
with open(os.path.join(HERE, "lw.sp"), "w") as f:
    f.write(lwdeck)
subprocess.run([NGSPICE, "-b", "lw.sp"], capture_output=True, text=True, cwd=HERE)
pylw = open(os.path.join(HERE, "lw.py")).read() if os.path.isfile(os.path.join(HERE, "lw.py")) else ""
check("E-183c: set pyplot_linewidth=3.5 -> linewidth=3.5 in the plot() call",
      "linewidth=3.5" in pylw and is_png(os.path.join(HERE, "lw.png")))

# ---- Enhancement-183d: pyplot_backend ----
bedeck = twodeck.replace(
    "set pyplot_terminal=png\npyplot v(out) title first\npyplot v(in) title second",
    "set pyplot_terminal=png\nset pyplot_backend=Agg\npyplot be v(out)")
with open(os.path.join(HERE, "be.sp"), "w") as f:
    f.write(bedeck)
subprocess.run([NGSPICE, "-b", "be.sp"], capture_output=True, text=True, cwd=HERE)
pybe = open(os.path.join(HERE, "be.py")).read() if os.path.isfile(os.path.join(HERE, "be.py")) else ""
check("E-183d: set pyplot_backend=Agg -> matplotlib.use('agg') in the script",
      "matplotlib.use('agg')" in pybe and is_png(os.path.join(HERE, "be.png")))

# ---- Enhancement-208: `pyplot -eye` renders an eye diagram via matplotlib ----
# A self-contained data eye: a short pseudo-random NRZ bit stream (PWL) through a
# bandwidth-limiting RC channel (tau ~ 0.5 UI) so the eye is clearly open but
# ISI-shaped -- no OSDI model needed for the rendering path.
for f_ in ("eyefig.py", "eyefig.data", "eyefig.png",
           "eye.py", "eye.data", "eye.png", "eye.sp"):
    try:
        os.remove(os.path.join(HERE, f_))
    except OSError:
        pass
random.seed(7)
_UI, _N, _TR = 0.5e-9, 300, 12e-12
_bits = [random.randint(0, 1) for _ in range(_N)]
_pts = ["0 %d" % _bits[0]]
for _k in range(1, _N):
    if _bits[_k] != _bits[_k - 1]:
        _te = _k * _UI
        _pts.append("%.6e %d" % (_te - _TR / 2, _bits[_k - 1]))
        _pts.append("%.6e %d" % (_te + _TR / 2, _bits[_k]))
eyedeck = """* pyplot -eye: eye diagram straight from a transient (Enhancement-208)
Vtx tx 0 PWL(%s)
Rc tx rx 250
Cc rx 0 1p
.tran 1p %gn
.control
run
set pyplot_terminal=png
pyplot eyefig -eye v(rx) -ui 0.5n -tstart 3n
pyplot -eye v(rx) -ui 0.5n -tstart 3n
.endc
.end
""" % (" ".join(_pts), _N * 0.5)
with open(os.path.join(HERE, "eye.sp"), "w") as f:
    f.write(eyedeck)
r = subprocess.run([NGSPICE, "-b", "eye.sp"], capture_output=True, text=True, cwd=HERE)
elog = r.stdout + r.stderr
pyeye = (open(os.path.join(HERE, "eyefig.py")).read()
         if os.path.isfile(os.path.join(HERE, "eyefig.py")) else "")
check("E-208: `pyplot -eye` runs the eye analysis and reports its metrics",
      "eye height" in elog and "eye width" in elog, elog.strip()[-160:])
check("E-208: `pyplot eyefig -eye v(rx) -ui ...` renders a valid eye PNG",
      is_png(os.path.join(HERE, "eyefig.png")))
check("E-208: the generated eye script is a persistence 2-D-histogram (hist2d)",
      "hist2d" in pyeye and "eye height" in pyeye and "matplotlib" in pyeye)
check("E-208: the no-name form defaults the eye base to 'eye.png'",
      is_png(os.path.join(HERE, "eye.png")))

for f in ("two.sp", "dir.sp", "lw.sp", "be.sp",
          "pyplot-2.py", "pyplot-2.data", "pyplot-2.png",
          "dir.py", "dir.data", "dir.png", "lw.py", "lw.data", "lw.png",
          "be.py", "be.data", "be.png",
          "tran.sp", "ac.sp", "nofn.sp", "rc.py", "rc.data", "rc.png",
          "acmag.py", "acmag.data", "acmag.png",
          "eye.sp", "eyefig.py", "eyefig.data", "eyefig.png",
          "eye.py", "eye.data", "eye.png",
          "pyplot.py", "pyplot.data", "pyplot.png", "rcload.osdi"):
    p = os.path.join(HERE, f)
    if os.path.exists(p):
        os.remove(p)

print(f"\n{passed}/{checks} checks passed")
raise SystemExit(0 if passed == checks else 1)
