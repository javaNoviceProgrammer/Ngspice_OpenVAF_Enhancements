#!/usr/bin/env python3
"""verify_measquad.py -- Enhancement-855: AVG and INTEG integrate by one rule.

F11 of the second robustness campaign of 2026-10-10.

AVG integrated by trapezoids; INTEG and RMS by Simpson's 3/8 or 1/3 rule on
runs of equal steps and trapezoids elsewhere. So INTEG/(to-from) and AVG over one
window differed -- by 2e-3 on a sampled sine -- where Enhancement-302 calls them
the same quantity. AVG now integrates its points with INTEG's rule.

  [1] a sampled sine: AVG = INTEG/(to-from) over a window (2e-3 apart on E-852)
  [2] (control) ...over a window across PWL corners, where the rules agree
  [3] ...over the whole run, without a window
  [4] the sine's AVG is within 5e-4 of the analytic average (1.9e-3 on E-852)
  [5] a dc sweep, rising and falling: AVG = INTEG/(to-from)
  [6] (control) a constant and a ramp: AVG exact

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

WORK = tempfile.mkdtemp(prefix="measquad_")
checks = passed = 0


def check(label, ok, detail=""):
    global checks, passed
    checks += 1
    passed += bool(ok)
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  [{detail}]" if detail else ""))


def measure(name, netlist, analysis, meas):
    lines = ["* " + name, netlist] + [".meas %s %s %s" % (analysis.split()[0], n, c) for n, c in meas]
    lines += ["." + analysis, ".control", "set numdgt=17", "run"] + ["print " + n for n, _ in meas]
    lines += [".endc", ".end", ""]
    path = os.path.join(WORK, name + ".cir")
    with open(path, "w") as f:
        f.write("\n".join(lines))
    p = subprocess.run([NGSPICE, "-b", path], cwd=WORK, capture_output=True, text=True, timeout=300,
                       errors="replace")
    got = {}
    for n, _ in meas:
        m = re.search(r"^%s = (\S+)" % n, p.stdout + p.stderr, re.M)
        got[n] = float(m.group(1)) if m else float("nan")
    return got


def agree(avg, integ, span, tol=1e-14):
    return avg == avg and integ == integ and abs(avg * span / integ - 1) <= tol


NET = ("v1 1 0 sin(0.2 1.3 1.5meg)\nv2 2 0 pwl(0 0 0.3u 1 0.7u -0.5 1u 0.2)\n"
       "v3 3 0 dc 0.7\nv4 4 0 pwl(0 0 1u 2)\nr1 1 0 1k\nr2 2 0 1k\nr3 3 0 1k\nr4 4 0 1k")
A, B = 0.13e-6, 0.71e-6
got = measure("tran", NET, "tran 10n 1u",
              [("a1", "avg v(1) from=0.13u to=0.71u"), ("i1", "integ v(1) from=0.13u to=0.71u"),
               ("a2", "avg v(2) from=0.13u to=0.91u"), ("i2", "integ v(2) from=0.13u to=0.91u"),
               ("aw", "avg v(1)"), ("iw", "integ v(1)"),
               ("a3", "avg v(3) from=0.13u to=0.71u"), ("a4", "avg v(4) from=0.13u to=0.71u")])
check("[1] a sampled sine: AVG = INTEG/(to-from) (2e-3 apart on E-852)", agree(got["a1"], got["i1"], B - A),
      f"avg*span/integ - 1 = {got['a1'] * (B - A) / got['i1'] - 1:.2e}")
check("[2] (control) ...across PWL corners, where the rules agree", agree(got["a2"], got["i2"], 0.91e-6 - A),
      f"{got['a2'] * (0.91e-6 - A) / got['i2'] - 1:.2e}")
check("[3] ...over the whole run, without a window", agree(got["aw"], got["iw"], 1e-6),
      f"{got['aw'] * 1e-6 / got['iw'] - 1:.2e}")
w = 2 * math.pi * 1.5e6
exact = 0.2 + 1.3 * (math.cos(w * A) - math.cos(w * B)) / w / (B - A)
check("[4] the sine's AVG is within 5e-4 of the analytic average (1.9e-3 on E-852)",
      abs(got["a1"] / exact - 1) < 5e-4, f"{got['a1'] / exact - 1:.2e}")
check("[6] (control) a constant and a ramp: AVG exact",
      abs(got["a3"] - 0.7) < 1e-12 and abs(got["a4"] - (A + B) / 1e-6) < 1e-12,
      f"{got['a3']!r}, {got['a4']!r}")

DC = "v1 1 0 0\nb2 2 0 v=sin(3*v(1))\nr2 2 0 1k"
for name, sweep in (("up", "dc v1 0 1 0.01"), ("down", "dc v1 1 0 -0.01")):
    got = measure("dc" + name, DC, sweep,
                  [("a", "avg v(2) from=0.123 to=0.877"), ("i", "integ v(2) from=0.123 to=0.877")])
    check(f"[5] a dc sweep, {'rising' if name == 'up' else 'falling'}: AVG = INTEG/(to-from)",
          agree(got["a"], got["i"], 0.877 - 0.123, 1e-12),
          f"{got['a'] * (0.877 - 0.123) / got['i'] - 1:.2e}")

print(f"\n{passed}/{checks} checks passed")
sys.exit(0 if passed == checks else 1)
