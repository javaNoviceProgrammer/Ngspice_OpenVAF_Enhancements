#!/usr/bin/env python3
"""
verify_optimize.py -- Enhancement-130: the built-in Nelder-Mead `optimize` command.

`optimize` varies circuit/device parameters (via in-place `alter`), re-runs an
analysis, and minimizes a scalar objective expression -- a derivative-free
downhill-simplex search in normalized [0,1] parameter space.

Each check optimizes a circuit with a KNOWN analytic optimum and confirms the
command reaches it:

  [1] DC divider: minimize (v(out)-0.3)^2 over R1 (R2=1k, Vin=1). v(out)=R2/(R1+R2)
      => R1 = 1k*(1/0.3 - 1) = 2333.3 ohm exactly.
  [2] AC low-pass: minimize (mag(v(out))-0.5)^2 over R1 at 1 kHz (C=100n).
      |H|=1/sqrt(1+(2pi f R C)^2)=0.5 => 2pi f R C = sqrt(3) => R = 2756.6 ohm.
  [3] Two parameters at once (2-D simplex): a divider where R1=3k, R2=2k is the
      unique solution of v(out)=0.4 AND R1+R2=5k (i(V1)=-0.2 mA); minimize the
      compound objective (v(out)-0.4)^2 + (abs(i(v1))-0.2m)^2.
  [4] the inner analyses are quiet by default (few "Doing analysis" banners) but
      `-verbose` prints per-iteration progress.

It is a front-end command, independent of the linear solver, so it is checked once.
"""
import math
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))  # the examples/ dir, for _setup.py
from _setup import NG as NGSPICE

checks = passed = 0
def check(label, ok, detail=""):
    global checks, passed
    checks += 1; passed += bool(ok)
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  [{detail}]" if detail and not ok else ""))


def run(deck):
    p = os.path.join(HERE, "_opt.cir")
    with open(p, "w") as f:
        f.write(deck)
    try:
        r = subprocess.run([NGSPICE, "-b", p], capture_output=True, text=True, timeout=120)
    finally:
        if os.path.exists(p):
            os.remove(p)
    return r.stdout + r.stderr


def val(out, name):
    m = re.search(rf"(?im)^\s*{re.escape(name)}\s*=\s*([-\d.eE+]+)", out)
    return float(m.group(1)) if m else None


def optval(out, name):
    """the 'name = value' the optimizer prints for a converged parameter"""
    m = re.search(rf"(?im)^\s+{re.escape(name)}\s*=\s*([-\d.eE+]+)\s*$", out)
    return float(m.group(1)) if m else None


print("Enhancement-130: built-in Nelder-Mead optimizer")

# [1] DC divider -> R1 = 2333.3
d1 = ("optimizer dc divider\nV1 in 0 dc 1\nR1 in out 1k\nR2 out 0 1k\n.control\n"
      "optimize -param R1 1k 100 10k -analysis op -minimize (v(out)-0.3)^2 -tol 1e-14\n"
      "let vout = v(out)\nprint vout\n.endc\n.end\n")
o1 = run(d1)
r1 = optval(o1, "r1") or optval(o1, "R1")
vout1 = val(o1, "vout")
check(f"DC divider: R1 -> 2333.3 ohm (got {r1})",
      r1 is not None and abs(r1 - 2333.333) / 2333.333 < 1e-3, str(r1))
check(f"DC divider: v(out) -> 0.3 target (got {vout1})",
      vout1 is not None and abs(vout1 - 0.3) < 1e-4, str(vout1))

# [2] AC low-pass -> R1 = 2756.6
R_ac = math.sqrt(3.0) / (2 * math.pi * 1e3 * 100e-9)     # 2756.6
d2 = ("optimizer ac lowpass\nV1 in 0 ac 1\nR1 in out 1k\nC1 out 0 100n\n.control\n"
      "optimize -param R1 1k 100 100k -analysis ac lin 1 1k 1k "
      "-minimize (mag(v(out))-0.5)^2 -tol 1e-14\n"
      "let g = mag(v(out))\nprint g\n.endc\n.end\n")
o2 = run(d2)
r2 = optval(o2, "r1") or optval(o2, "R1")
g2 = val(o2, "g")
check(f"AC low-pass: R1 -> {R_ac:.1f} ohm (got {r2})",
      r2 is not None and abs(r2 - R_ac) / R_ac < 2e-3, str(r2))
check(f"AC low-pass: |H(1kHz)| -> 0.5 target (got {g2})",
      g2 is not None and abs(g2 - 0.5) < 1e-3, str(g2))

# [3] two-parameter compound objective -> R1=3k, R2=2k
d3 = ("optimizer two-param\nV1 in 0 dc 1\nR1 in out 1k\nR2 out 0 1k\n.control\n"
      "optimize -param R1 1k 100 10k -param R2 1k 100 10k -analysis op "
      "-minimize (v(out)-0.4)^2+(abs(i(v1))-0.2m)^2 -maxiter 400 -tol 1e-15\n"
      "let vout = v(out)\nprint vout\n.endc\n.end\n")
o3 = run(d3)
r1b = optval(o3, "r1") or optval(o3, "R1")
r2b = optval(o3, "r2") or optval(o3, "R2")
check(f"2-param: R1 -> 3k (got {r1b})", r1b is not None and abs(r1b - 3000) / 3000 < 5e-3, str(r1b))
check(f"2-param: R2 -> 2k (got {r2b})", r2b is not None and abs(r2b - 2000) / 2000 < 5e-3, str(r2b))
check(f"2-param: v(out) -> 0.4 (got {val(o3,'vout')})",
      val(o3, "vout") is not None and abs(val(o3, "vout") - 0.4) < 2e-3)

# [4] output is quiet by default; -verbose prints progress
quiet_banners = o1.count("Doing analysis")
check(f"inner analyses are suppressed by default ({quiet_banners} banner(s) for ~67 evals)",
      quiet_banners <= 3, f"{quiet_banners} banners")
o_verbose = run(d1.replace("-tol 1e-14", "-tol 1e-14 -verbose"))
check("-verbose prints per-iteration progress",
      "best cost" in o_verbose)

print(f"\n{'ALL PASS' if passed == checks else 'FAILURES'}: {passed}/{checks} passed")
sys.exit(0 if passed == checks else 1)
