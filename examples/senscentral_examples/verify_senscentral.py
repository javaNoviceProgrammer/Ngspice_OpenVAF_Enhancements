#!/usr/bin/env python3
"""verify_senscentral.py -- Enhancement-861: sensitivities by a central
difference.

F6 of the third robustness campaign of 2026-10-10.

sens perturbed each parameter by Sens_Delta = 1e-6 of its value and divided
the change in the device's stamp by that step, against the nominal stamp. A
parameter that enters the stamp linearly, a gain or a source, came out exact; a
resistance enters as 1/R, and (1/(R+d) - 1/R)/d = -1/(R(R+d)) is low by the
factor 1/(1 + 1e-6): every sensitivity to a resistance was low by exactly
that. The step is now central, (p + d) against (p - d) over 2 d, where the
parameter is not zero, with the same number of loads.

  [1] dV(4)/dR1..dR4 of a resistive network with a VCVS, to 1e-9 of the
      analytic values (low by 1e-6 on E-859)
  [2] an ac sensitivity: dH/dR of an RC low-pass at three frequencies, to 1e-9
  [3] a diode's series resistance rs, against a central difference of two
      tight operating points, to 1e-7 (1e-6 off on E-859)
  [4] (control) the gain of the VCVS, exact before and after
  [5] (control) a diode's is, against the same reference

Exit code 0 = pass.
"""
import cmath
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

WORK = tempfile.mkdtemp(prefix="senscentral_")
checks = passed = 0


def check(label, ok, detail=""):
    global checks, passed
    checks += 1
    passed += bool(ok)
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  [{detail}]" if detail else ""))


def run(name, body, control):
    path = os.path.join(WORK, name + ".cir")
    with open(path, "w") as f:
        f.write("* %s\n%s\n.control\nset numdgt=17\n%s\n.endc\n.end\n" % (name, body, control))
    p = subprocess.run([NGSPICE, "-b", path], cwd=WORK, capture_output=True, text=True, timeout=120,
                       errors="replace")
    return p.stdout + p.stderr


def scalars(out):
    return {m.group(1): float(m.group(2)) for m in re.finditer(r"^(\S+) = (\S+)$", out, re.M)
            if re.match(r"^[-+0-9.]", m.group(2))}


def rel(a, b):
    return abs(a - b) / abs(b) if b else abs(a)


# [1], [4]
NET = """vin 1 0 dc 1
r1 1 2 1k
r2 2 0 2k
e1 3 0 2 0 5
r3 3 4 500
r4 4 0 1k"""
R1, R2, R3, R4, G = 1e3, 2e3, 500.0, 1e3, 5.0
v2 = R2 / (R1 + R2)
EXACT = {"r1": -G * R2 / (R1 + R2) ** 2 * R4 / (R3 + R4), "r2": G * R1 / (R1 + R2) ** 2 * R4 / (R3 + R4),
         "r3": -G * v2 * R4 / (R3 + R4) ** 2, "r4": G * v2 * R3 / (R3 + R4) ** 2, "e1_gain": v2 * R4 / (R3 + R4)}
got = scalars(run("dc", NET, "sens v(4)\nprint r1 r2 r3 r4 e1_gain"))
errs = {k: rel(got[k], v) if k in got else None for k, v in EXACT.items()}
res = [k for k in ("r1", "r2", "r3", "r4")]
check("[1] dV(4)/dR1..dR4 to 1e-9 of the analytic values",
      all(errs[k] is not None and errs[k] < 1e-9 for k in res),
      ", ".join("%s %.2g" % (k, errs[k]) for k in res if errs[k] is not None))

# [2]
R, C = 1e3, 1e-9
out = run("ac", "vin 1 0 dc 0 ac 1\nr1 1 2 %r\nc1 2 0 %r" % (R, C),
          "sens v(2) ac dec 1 10k 1meg\nprint frequency r1")
fr = re.findall(r"^\d+\s+(\S+)\s+(\S+),\s*(\S+)\s*$", out, re.M)
worst = None
for f, re_, im_ in fr:
    s = 2j * math.pi * float(f)
    want = -s * C / (1 + s * R * C) ** 2
    e = abs(complex(float(re_), float(im_)) - want) / abs(want)
    worst = e if worst is None else max(worst, e)
check("[2] ac: dH/dR of an RC low-pass to 1e-9 at 10k, 100k, 1meg",
      worst is not None and worst < 1e-9 and len(fr) == 3, "%d points, worst %.2g" % (len(fr), worst or -1))

# [3], [5]
DIODE = """vin 1 0 dc 2
r1 1 2 1k
d1 2 0 dm
.model dm d(is=%r n=1.5 rs=%r)
.options reltol=1e-14 abstol=1e-20 vntol=1e-16 itl1=500"""
sens = scalars(run("diode", DIODE % (1e-14, 10.0), "sens v(2)\nprint all"))


def op(is_, rs):
    o = run("dop", DIODE % (is_, rs), "op\nprint v(2)")
    return float(re.search(r"^v\(2\) = (\S+)", o, re.M).group(1))


def richardson(f, p0):
    d1 = (f(1e-3) - f(-1e-3)) / (2e-3 * p0)
    d2 = (f(5e-4) - f(-5e-4)) / (1e-3 * p0)
    return (4 * d2 - d1) / 3


ref_rs = richardson(lambda h: op(1e-14, 10.0 * (1 + h)), 10.0)
ref_is = richardson(lambda h: op(1e-14 * (1 + h), 10.0), 1e-14)
e_rs = rel(sens.get("d1:rs", 0.0), ref_rs)
e_is = rel(sens.get("d1:is", 0.0), ref_is)
check("[3] a diode's rs: dV/drs to 1e-7 of two tight operating points", e_rs < 1e-7,
      "%r vs %r, %.2g" % (sens.get("d1:rs"), ref_rs, e_rs))
check("[4] (control) the VCVS's gain: dV(4)/dE1 to 1e-9", errs["e1_gain"] is not None and errs["e1_gain"] < 1e-9,
      "%.2g" % (errs["e1_gain"] or -1))
check("[5] (control) a diode's is: dV/dis to 1e-7 of the same reference", e_is < 1e-7,
      "%r vs %r, %.2g" % (sens.get("d1:is"), ref_is, e_is))

print(f"\n{passed}/{checks} checks passed")
sys.exit(0 if passed == checks else 1)
