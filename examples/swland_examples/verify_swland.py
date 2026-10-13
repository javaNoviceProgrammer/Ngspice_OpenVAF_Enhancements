#!/usr/bin/env python3
"""verify_swland.py -- Enhancement-884: built-in switches land on their crossing.

N1 (and the switching half of N3) of the transient stress campaign of
2026-10-12. A switch (`sw`, `csw`) that turns over inside a step asks for the
step to be redone at its crossing, keeps its accepted state there, and the step
after it is taken at order 1, as after a source's corner.

  [1] a charge pump whose switches have no hysteresis runs to the end at
      reltol 1e-6 and 1e-7 (E-883: "Timestep too small" at both)
  [2] a voltage-controlled switch with vh=0 closes at 500 ns and opens at
      1500 ns on a 100 ns step: the output crosses within 0.3 ns of the exact
      times (E-883: 11.2 ns late and 19.7 ns early)
  [3] with vh=0.1 and vh=-0.1 it turns over at the band edge that applies,
      within 0.5 ns (E-883: closed 8.8 ns early)
  [4] a current-controlled switch lands on its crossing as well (E-883: 11.2 ns
      late and 19.7 ns early)
  [5] Family C's seed-9 charge pump under default trap ends within 0.05 % of
      the reltol=1e-6 result, and its switch node rises at most 1 % above the
      supply (E-883: 1.1 % off, and 2.66 V on a 2.49 V supply)
  [6] (control) with vh=0.01 the charge pump runs at reltol 1e-6, as before,
      and ends at 4.24334 V, where [1] ends

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

WORK = tempfile.mkdtemp(prefix="swland_")
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


PUMP = """* charge pump, switches without hysteresis
vdd vdd 0 3
vp p 0 pulse(0 1 0 1n 1n 45n 100n)
vn n 0 pulse(1 0 0 1n 1n 45n 100n)
s1 vdd x p 0 swm
s2 x 0 n 0 swm
cf x y 1n
d1 vdd y dm
d2 y out dm
co out 0 10n
rl out 0 1e4
.model swm sw vt=0.5 vh=%s ron=1 roff=1e9
.model dm d is=1e-14 cjo=1e-12
.option reltol=%s
.control
tran 0.1n 2u
let z = v(out)[length(v(out))-1]
print z
.endc
.end
"""

res = {}
for rt in ("1e-6", "1e-7"):
    out = run("pump_" + rt, PUMP % ("0", rt))
    res[rt] = (num(out, "z"), "too small" in out)
check("[1] a charge pump with vh=0 runs to the end at reltol 1e-6 and 1e-7",
      all(z is not None and not small and abs(z - 4.243345) < 1e-4 for z, small in res.values()),
      ", ".join("%s: %s%s" % (k, v[0], " (too small)" if v[1] else "") for k, v in res.items()))

TIMING = """* switch timing
vc c 0 pwl(0 0 1u 1 2u 0)
vdd vdd 0 1
r1 vdd o 1k
s1 o 0 c 0 swm
c1 o 0 1p
.model swm sw vt=0.5 vh=%s ron=1 roff=1e12
.control
tran 100n 2u
meas tran tfall WHEN v(o)=0.5 FALL=1
meas tran trise WHEN v(o)=0.5 RISE=1
.endc
.end
"""
# the output falls within a picosecond of the closing (1 ohm x 1 pF) and rises
# 0.69 ns after the opening (1 kohm x 1 pF, ln 2)
out = run("t0", TIMING % "0")
tf, tr = num(out, "tfall"), num(out, "trise")
check("[2] vh=0: the switch closes at 500 ns and opens at 1500 ns, within 0.3 ns",
      tf is not None and tr is not None and abs(tf - 500.0e-9) < 0.3e-9 and abs(tr - 1500.69e-9) < 0.3e-9,
      "fall %s, rise %s" % (tf, tr))

ok = True
det = []
for vh, (ton, toff) in (("0.1", (600e-9, 1600e-9)), ("-0.1", (400e-9, 1400e-9))):
    out = run("t" + vh, TIMING % vh)
    tf, tr = num(out, "tfall"), num(out, "trise")
    ok = ok and tf is not None and tr is not None and abs(tf - ton) < 0.5e-9 and abs(tr - toff - 0.69e-9) < 0.5e-9
    det.append("vh=%s: %s, %s" % (vh, tf, tr))
check("[3] vh=0.1 and vh=-0.1: the switch turns over at the band edge that applies, within 0.5 ns",
      ok, "; ".join(det))

CSW = """* current-controlled switch timing
vc c 0 pwl(0 0 1u 1 2u 0)
vs c cs 0
rcs cs 0 1k
vdd vdd 0 1
r1 vdd o 1k
w1 o 0 vs swm
c1 o 0 1p
.model swm csw it=0.5m ih=0 ron=1 roff=1e12
.control
tran 100n 2u
meas tran tfall WHEN v(o)=0.5 FALL=1
meas tran trise WHEN v(o)=0.5 RISE=1
.endc
.end
"""
out = run("csw", CSW)
tf, tr = num(out, "tfall"), num(out, "trise")
check("[4] a current-controlled switch lands on its crossing, within 0.3 ns",
      tf is not None and tr is not None and abs(tf - 500.0e-9) < 0.3e-9 and abs(tr - 1500.69e-9) < 0.3e-9,
      "fall %s, rise %s" % (tf, tr))

SEED9 = """* Family C seed 9 charge pump
vdd vdd 0 2.493247725580168
vp p 0 pulse(0 1 0 4.082986336248532e-08 4.082986336248532e-08 1.8373438513118395e-06 4.082986336248532e-06)
vn n 0 pulse(1 0 0 4.082986336248532e-08 4.082986336248532e-08 1.8373438513118395e-06 4.082986336248532e-06)
s1 vdd x p 0 swm
s2 x 0 n 0 swm
cf x y 2.6038636419789744e-10
d1 vdd y dm
d2 y out dm
co out 0 3.978190261898515e-07
rl out 0 1045.4545624207897
.model swm sw vt=0.5 ron=1.0128943768008276 roff=1e9
.model dm d is=1e-14 cjo=1e-12
%s
.control
tran 3.919666882798591e-07 0.00019598334413992955
let z = v(out)[length(v(out))-1]
print z
meas tran vxmax MAX v(x)
.endc
.end
"""
d = run("seed9", SEED9 % "")
r = run("seed9_ref", SEED9 % ".option reltol=1e-6")
zd, zr, vx = num(d, "z"), num(r, "z"), num(d, "vxmax")
check("[5] seed-9 charge pump, default trap: within 0.05 % of reltol=1e-6, switch node within 1 % of the supply",
      zd is not None and zr is not None and vx is not None and abs(zd - zr) / zr < 5e-4 and vx < 1.01 * 2.493247725580168,
      "default %s, tight %s, switch-node peak %s" % (zd, zr, vx))

out = run("pump_h", PUMP % ("0.01", "1e-6"))
z = num(out, "z")
check("[6] (control) vh=0.01 runs at reltol 1e-6 and ends at 4.24334 V",
      z is not None and "too small" not in out and abs(z - 4.243345) < 1e-4, str(z))

print(f"\n{passed}/{checks} checks passed")
sys.exit(0 if passed == checks else 1)
