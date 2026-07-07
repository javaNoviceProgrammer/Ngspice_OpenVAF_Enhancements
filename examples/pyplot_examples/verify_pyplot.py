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
"""
import os
import re
import struct
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from _setup import VAF as OPENVAF, NG as NGSPICE

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

for f in ("tran.sp", "ac.sp", "nofn.sp", "rc.py", "rc.data", "rc.png",
          "acmag.py", "acmag.data", "acmag.png",
          "pyplot.py", "pyplot.data", "pyplot.png", "rcload.osdi"):
    p = os.path.join(HERE, f)
    if os.path.exists(p):
        os.remove(p)

print(f"\n{passed}/{checks} checks passed")
raise SystemExit(0 if passed == checks else 1)
