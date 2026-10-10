#!/usr/bin/env python3
"""verify_osdinonfinite.py -- Enhancement-854: an OSDI device's non-finite load
is named.

F10 of the second robustness campaign of 2026-10-10.

`V(o) <+ ln(V(x))` is evaluated at Newton's zero start, ln(0) = -inf, and every
homotopy restarts from the same point. The operating point ended "Timestep too
small; cause unrecorded", naming neither the device nor the value. Each OSDI
instance's right-hand side rows and Jacobian entries are now checked as it
loads: a value that is not finite makes it the trouble element the failure
names, and a warning, once per instance, says which value and at what
terminal voltages.

  [1] lnout at the zero start: the op fails "trouble with lm-instance n1", not
      "cause unrecorded"
  [2] the warning names n1, module lnout, the residual of flow(o), NaN, and
      x = 0 V, once
  [3] the same model in a transient: "initial timepoint: trouble with
      lm-instance n1"
  [4] a current 1/(1 + 1/V), 0 at 0 V with a derivative that is not: named too
  [5] (control) the same ln() with a guard converges, with no warning

Exit code 0 = pass.
"""
import os
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from _setup import VAF as OPENVAF, NG as NGSPICE  # noqa: E402
from _setup import check_both_solvers as _check_both_solvers; _check_both_solvers(__file__)  # noqa: E402

WORK = tempfile.mkdtemp(prefix="osdinonfinite_")
checks = passed = 0


def check(label, ok, detail=""):
    global checks, passed
    checks += 1
    passed += bool(ok)
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  [{detail}]" if detail else ""))


def osdi(stem):
    out = os.path.join(WORK, stem + ".osdi")
    if not os.path.exists(out):
        subprocess.run([OPENVAF, os.path.join(HERE, stem + ".va"), "-o", out], cwd=WORK,
                       capture_output=True, text=True, timeout=300)
    return out


def run(name, stem, netlist, analysis):
    path = os.path.join(WORK, name + ".cir")
    with open(path, "w") as f:
        f.write("* %s\n%s\n.control\npre_osdi %s\n%s\n.endc\n.end\n" % (name, netlist, osdi(stem), analysis))
    p = subprocess.run([NGSPICE, "-b", path], cwd=WORK, capture_output=True, text=True, timeout=300,
                       errors="replace")
    return p.stdout + p.stderr


LN = "vx x 0 1.056\nn1 x o lm\nr1 o 0 1k\n.model lm %s"

# [1], [2]
out = run("lnop", "lnout", LN % "lnout", "op\nprint v(o)")
check("[1] ln(V(x)) at the zero start: the op fails naming n1 (cause unrecorded on E-852)",
      "trouble with lm-instance n1" in out and "cause unrecorded" not in out,
      (re.search(r"doAnalyses:.*", out) or [""])[0])
warns = re.findall(r"Warning: n1 \(Verilog-A module lnout\) loaded a value that is not finite: (.*)", out)
check("[2] the warning names n1, lnout, the residual of flow(o), NaN and x = 0 V, once",
      len(warns) == 1 and "the residual of flow(o) is NaN" in warns[0] and "x = 0 V" in warns[0],
      f"{len(warns)} warning(s)")

# [3]
out = run("lntran", "lnout", LN % "lnout", "tran 1n 10n\nprint v(o)")
check("[3] in a transient: the failure names n1 at the initial timepoint",
      "initial timepoint: trouble with lm-instance n1" in out,
      (re.search(r"doAnalyses:.*", out) or [""])[0])

# [4]
out = run("div", "divg", "v1 a 0 1\nr1 a b 1k\nn1 b 0 dm\n.model dm divg", "op\nprint v(b)")
check("[4] a current 1/(1 + 1/V), whose derivative at 0 V is not finite: named",
      "trouble with dm-instance n1" in out and "Warning: n1 (Verilog-A module divg)" in out,
      (re.search(r"doAnalyses:.*", out) or ["converged?"])[0])

# [5]
out = run("guard", "lnguard", LN % "lnguard", "op\nprint v(o)")
m = re.search(r"^v\(o\) = (\S+)", out, re.M)
check("[5] (control) the same ln() with a guard converges to ln(1.056), with no warning",
      m is not None and abs(float(m.group(1)) - 0.054488185284069776) < 1e-6 and "not finite" not in out,
      m.group(1) if m else "no v(o)")

print(f"\n{passed}/{checks} checks passed")
sys.exit(0 if passed == checks else 1)
