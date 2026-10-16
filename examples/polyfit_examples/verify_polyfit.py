#!/usr/bin/env python3
"""verify_polyfit.py -- Enhancement-890: the local polynomial fits are made in
a local coordinate.

F2 of the nonlinear correctness campaign of 2026-10-15. ft_polyfit fitted each
local polynomial in the monomials of the abscissa itself -- 1, t, t^2, t^3 with
t near 0.5 s and the points 1 us apart -- so the fit's condition grew as
(t/h)^degree, and the coefficients, evaluated at t again, cancelled by as
much. `fourier` (polydegree), `deriv` (dpolydegree), `interpolate`,
`linearize` and plot interpolation all fit this way.

  [1] deriv of a 1 kHz sine at dpolydegree=3 over 500 ms is within 1e-7 of
      2 pi f cos (E-889: 3.2e20)
  [2] at dpolydegree=4 over 50 ms, within 1e-9 (E-889: 3.4e33)
  [3] (control) at the default dpolydegree=2 the error is the method's own,
      6.58e-6, as before
  [4] fourier at polydegree=3 of four stacked harmonics at 5.07 MHz: the 4th
      harmonic's phase within 0.001 degree, the 5th and 6th, which are zero,
      below 1e-9 (E-889: 1.07 degrees off, 1.2e-4 and 2.3e-5)
  [5] the same at polydegree=4: the fundamental within 1e-5 of 0.975116
      (E-889: 3831)
  [6] a pure sine over 2000 ms reads a THD below 1e-9 % at polydegree 1 to 4
      (E-889: 1.8e-9 %, 4.2e-7 %, 3.8e-7 % and nan)

Exit code 0 = pass.
"""
import math
import os
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from _setup import NG as NGSPICE  # noqa: E402
from _setup import check_both_solvers as _check_both_solvers; _check_both_solvers(__file__)  # noqa: E402

WORK = tempfile.mkdtemp(prefix="polyfit_")
checks = passed = 0


def check(label, ok, detail=""):
    global checks, passed
    checks += 1
    passed += bool(ok)
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  [{detail}]" if detail else ""))


def run(tag, text):
    path = os.path.join(WORK, tag + ".cir")
    with open(path, "w") as f:
        f.write(text)
    r = subprocess.run([NGSPICE, "-b", path], cwd=WORK, capture_output=True, text=True, timeout=300)
    return r.stdout + r.stderr


def num(out, name):
    m = re.search(r"^%s\s*=\s*(\S+)" % re.escape(name), out, re.M)
    try:
        return float(m.group(1)) if m else None
    except ValueError:
        return None


DERIV = """* deriv of a 1 kHz sine against the exact cosine
v1 a 0 sin(0 1 1k)
r1 a 0 1k
.control
set dpolydegree=%d
tran 1u %s 0 1u
let d = deriv(v(a))
let ex = 2*pi*1k*cos(2*pi*1k*time)
let e = abs(d - ex) / (2*pi*1k)
let ei = e[2,length(e)-3]
let w = vecmax(ei)
print w
.endc
.end
"""

w = num(run("d3", DERIV % (3, "500m")), "w")
check("[1] deriv at dpolydegree=3 over 500 ms is within 1e-7 of the derivative",
      w is not None and w < 1e-7, f"{w}")
w = num(run("d4", DERIV % (4, "50m")), "w")
check("[2] deriv at dpolydegree=4 over 50 ms is within 1e-9", w is not None and w < 1e-9, f"{w}")
w = num(run("d2", DERIV % (2, "500m")), "w")
check("[3] (control) deriv at the default degree 2 has the method's own error, 6.58e-6",
      w is not None and 6.5e-6 < w < 6.7e-6, f"{w}")

# the campaign's Family F seed 1072: four harmonics of 5.07 MHz, one period
FOUR = """* four stacked harmonics
v1 h1 0 sin(-1.4182395840848394 0.975116148381898 5068014.274396805 0 0 126.12578469845499)
v2 h2 h1 sin(0.0 0.061510848318040934 10136028.54879361 0 0 -34.65076821186261)
v3 h3 h2 sin(0.0 0.001832256328080693 15204042.823190415 0 0 -121.8268268070475)
v4 h4 h3 sin(0.0 0.018014554830284024 20272057.09758722 0 0 36.345720450822085)
rl h4 0 1k
.tran 1.9731593990409981e-10 1.9731593990409983e-06 0.0 1.9731593990409981e-10
.four 5068014.274396805 v(h4)
.control
set nfreqs=18
set nperiods=1
set polydegree=%d
set fourgridsize=1000
run
.endc
.end
"""


def harmonics(out):
    rows = {}
    for m in re.finditer(r"^\s*(\d+)\s+(\S+)\s+(\S+)\s+(\S+)\s+(\S+)\s+(\S+)\s*$", out, re.M):
        try:
            rows[int(m.group(1))] = (float(m.group(3)), float(m.group(4)))
        except ValueError:
            pass
    return rows


h = harmonics(run("f3", FOUR % 3))
ok = all(k in h for k in (4, 5, 6))
dph = abs(h[4][1] - 36.345720450822085) if ok else None
check("[4] fourier at polydegree=3: the 4th harmonic's phase within 0.001 degree, the zero ones below 1e-9",
      ok and dph < 1e-3 and h[5][0] < 1e-9 and h[6][0] < 1e-9,
      f"phase off {dph}, h5 {h.get(5)}, h6 {h.get(6)}" if ok else "no table")
h = harmonics(run("f4", FOUR % 4))
check("[5] fourier at polydegree=4: the fundamental within 1e-5 of 0.975116",
      1 in h and abs(h[1][0] - 0.975116148381898) < 1e-5, f"{h.get(1)}")

SINE = """* a pure 1 kHz sine, fourier over the last period of 2000
v1 a 0 sin(0 1 1k)
r1 a 0 1k
.control
set polydegree=%d
tran 1u 2000m 0 1u
fourier 1k v(a)
.endc
.end
"""
thd = {}
for deg in (1, 2, 3, 4):
    m = re.search(r"THD:\s*(\S+)\s*%", run("s%d" % deg, SINE % deg))
    try:
        thd[deg] = float(m.group(1)) if m else None
    except ValueError:
        thd[deg] = None
check("[6] a pure sine over 2000 ms reads a THD below 1e-9 % at polydegree 1 to 4",
      all(v is not None and math.isfinite(v) and v < 1e-9 for v in thd.values()), f"{thd}")

print(f"\n{passed}/{checks} checks passed")
sys.exit(0 if passed == checks else 1)
