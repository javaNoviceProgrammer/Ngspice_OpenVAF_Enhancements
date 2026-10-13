#!/usr/bin/env python3
"""verify_newtonretry.py -- Enhancement-878: a transient step whose Newton
iteration fails is retried from where the step started.

F5 of the transient stress campaign of 2026-10-12.

PREDICTOR is not compiled in, so a step starts at CKTrhsOld. After a failed
step that held the failed iteration, and the retry started there. A Van der
Pol oscillator built from a cubic B-source ran one iteration out to 1e10 V and
beyond; from there a cubic needs some 60 Newton steps back against itl4's 10,
so no smaller step converged, and the run ended in "Timestep too small" under
every method, solver and tolerance. Its limit cycle peaks at 2.0198 V (scipy
Radau, rtol 1e-10).

  [1] the oscillator runs to the end under trap, gear, trbdf2 and sdirk
      (E-875: "Timestep too small" at 38 ns under all four)
  [2] at reltol=1e-6 its peak is within 0.1 % of 2.0198 V
  [3] with the cubic's argument clamped at +-1e10 V it also runs (E-875:
      failed as unclamped)
  [4] (control) clamped at +-1 kV, which the true path never reaches, it runs
      at reltol=1e-6 and peaks within 0.1 % of 2.0198 V

Exit code 0 = pass.
"""
import os
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from _setup import NG as NGSPICE  # noqa: E402
from _setup import check_both_solvers as _check_both_solvers; _check_both_solvers(__file__)  # noqa: E402

WORK = tempfile.mkdtemp(prefix="newtonretry_")
checks = passed = 0
PEAK = 2.0198          # scipy Radau, rtol 1e-10, atol 1e-13


def check(label, ok, detail=""):
    global checks, passed
    checks += 1
    passed += bool(ok)
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  [{detail}]" if detail else ""))


VDP = """* Van der Pol from a B-source
l1 x 0 78.66u
c1 x 0 1.113p
b1 x 0 i=0.000595*(%s^3/3 - v(x))
r1 x 0 1e6
.ic v(x)=0.0458
.option %s
.control
tran 1.41n 0.706u uic
let m = maximum(abs(v(x)))
let t = time[length(time)-1]
print m
print t
.endc
.end
"""


def run(name, arg, opts):
    path = os.path.join(WORK, name + ".cir")
    with open(path, "w") as f:
        f.write(VDP % (arg, opts))
    r = subprocess.run([NGSPICE, "-b", path], cwd=WORK, capture_output=True, text=True, timeout=120)
    out = r.stdout + r.stderr

    def num(n):
        m = re.search(r"^%s\s*=\s*(\S+)" % n, out, re.M)
        return float(m.group(1)) if m else None
    return num("m"), num("t"), "too small" in out


ends = []
for m in ("trap", "gear", "trbdf2", "sdirk"):
    pk, t, small = run("vdp_" + m, "v(x)", "method=%s" % m)
    ends.append((m, t is not None and t > 0.7e-6 and not small, pk))
check("[1] the oscillator runs to the end under trap, gear, trbdf2 and sdirk", all(e[1] for e in ends),
      "; ".join("%s %s, peak %s" % (m, "ends" if ok else "FAILS", pk) for m, ok, pk in ends))

pk, t, small = run("vdp_tight", "v(x)", "reltol=1e-6 abstol=1e-14 vntol=1e-9 chgtol=1e-17")
check("[2] at reltol=1e-6 the peak is within 0.1 % of 2.0198 V",
      pk is not None and abs(pk - PEAK) < 1e-3 * PEAK, "peak %s" % pk)

pk, t, small = run("vdp_1e10", "min(max(v(x),-1e10),1e10)", "")
check("[3] clamped at +-1e10 V the oscillator also runs",
      t is not None and t > 0.7e-6 and not small, "end %s, peak %s" % (t, pk))

pk, t, small = run("vdp_1k", "min(max(v(x),-1e3),1e3)", "reltol=1e-6 abstol=1e-14 vntol=1e-9 chgtol=1e-17")
check("[4] (control) clamped at +-1 kV it runs and peaks within 0.1 % of 2.0198 V",
      t is not None and t > 0.7e-6 and pk is not None and abs(pk - PEAK) < 1e-3 * PEAK, "peak %s" % pk)

print(f"\n{passed}/{checks} checks passed")
sys.exit(0 if passed == checks else 1)
