#!/usr/bin/env python3
"""Enhancement-194: particle swarm optimization (`optimize -method pso`).

The built-in `optimize` command (E-130/143/144/145) had a local Nelder-Mead
simplex and a gradient Levenberg-Marquardt least-squares fit. Both are *local*:
they descend into whichever basin the start point sits in. E-194 adds a third
method -- particle swarm optimization (`-method pso`) -- a global,
population-based, derivative-free search: a swarm of trial points flies through
the parameter box, each pulled toward its own and the swarm's best-seen point
(Clerc-Kennedy constriction). It finds the GLOBAL optimum of multimodal
objectives that trap a local method.

The testbed is the classic multimodal 1-D function

    f(p) = sin(p) + sin(10 p / 3)        on p in [2.7, 7.5]

evaluated through numparam as a voltage source `V1 out 0 dc {f(p)}`, with p tuned
via `-dparam`. Its GLOBAL minimum is p* = 5.1457, f* = -1.8996; it has several
higher local minima (e.g. ~ -1.20 near p = 3.39) that trap a downhill method
started at the p = 2.7 corner.

It is a front-end command, independent of the linear solver, so it runs once.

Every SPICE deck starts with a title line (SPICE treats line 1 as the title!).
"""
import math
import os
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from _setup import NG as NGSPICE

SCRATCH = tempfile.mkdtemp(prefix="psoopt_")
passed = failed = 0
P_STAR, F_STAR = 5.14573, -1.89960          # true 1-D global optimum


def check(label, ok, detail=""):
    global passed, failed
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  {detail}" if detail else ""))
    if ok:
        passed += 1
    else:
        failed += 1


def run(deck):
    open(os.path.join(SCRATCH, "o.cir"), "w").write(deck)
    r = subprocess.run([NGSPICE, "-b", "o.cir"], capture_output=True, text=True,
                       cwd=SCRATCH, timeout=120)
    return r.stdout + r.stderr


def optval(out, name):
    m = re.search(rf"(?im)^\s+{re.escape(name)}\s*=\s*([-\d.eE+]+)\s*$", out)
    return float(m.group(1)) if m else None


def objective(out):
    m = re.search(r"objective = ([-\d.eE+]+)", out)
    return float(m.group(1)) if m else None


def residual(out):
    m = re.search(r"sum-sq residual = ([-\d.eE+]+)", out)
    return float(m.group(1)) if m else None


# the shared 1-D multimodal circuit; %s = the optimize command
D1 = ("* pso multimodal 1-D\n"
      ".param p=2.7\n"
      "V1 out 0 dc {sin(p) + sin(10*p/3)}\n"
      "R1 out 0 1\n"
      ".control\n%s\n.endc\n.end\n")


def opt1d(method, seed=1, extra=""):
    cmd = (f"optimize -dparam p 2.7 2.7 7.5 -analysis op -minimize v(out) "
           f"-method {method} -swarmsize 24 -maxiter 60 -seed {seed} -tol 1e-8 {extra}")
    return run(D1 % cmd)


# ---- 1. PSO finds the GLOBAL optimum from the trapping corner start ----
o = opt1d("pso")
p_pso, f_pso = optval(o, "p"), objective(o)
glob = (p_pso is not None and abs(p_pso - P_STAR) < 0.05
        and f_pso is not None and f_pso < -1.88)
check("[pso] finds the global optimum p*=5.146, f*=-1.900 (from the p=2.7 corner)",
      glob, f"(p={p_pso}, f={f_pso})")

# ---- 2. Nelder-Mead from the SAME start is trapped in a local minimum ----
onm = opt1d("nm")
p_nm, f_nm = optval(onm, "p"), objective(onm)
trapped = (f_nm is not None and f_nm > -1.5)     # a local min, well above the global
check("[nm] the local simplex is trapped in a higher local minimum (PSO's advantage)",
      trapped and f_pso is not None and f_pso < f_nm - 0.3,
      f"(nm f={f_nm} at p={p_nm}; pso f={f_pso})")

# ---- 3. reproducible: the same seed gives an identical result ----
a = objective(opt1d("pso", seed=7))
b = objective(opt1d("pso", seed=7))
check("[repro] a fixed -seed is reproducible (same objective twice)",
      a is not None and b is not None and a == b, f"({a} vs {b})")

# ---- 4. robust: several seeds all reach the global basin ----
fs = [objective(opt1d("pso", seed=s)) for s in (1, 3, 11, 29)]
allglobal = all(f is not None and f < -1.88 for f in fs)
check("[robust] independent seeds all reach the global (f < -1.88)",
      allglobal, f"({[f'{f:.4f}' if f else None for f in fs]})")

# ---- 5. PSO works in least-squares (-target) mode too ----
cmd = ("optimize -dparam p 2.7 2.7 7.5 -analysis op -target v(out) -1.8996 "
       "-method pso -swarmsize 24 -maxiter 60 -seed 1")
ols = run(D1 % cmd)
p_ls, r_ls = optval(ols, "p"), residual(ols)
check("[lsq] PSO minimizes a -target least-squares objective (recovers p*)",
      p_ls is not None and abs(p_ls - P_STAR) < 0.05 and r_ls is not None and r_ls < 1e-6,
      f"(p={p_ls}, resid={r_ls})")

# ---- 6. 2-D separable multimodal: PSO finds both coordinates ----
D2 = ("* pso multimodal 2-D\n"
      ".param a=2.7\n.param b=2.7\n"
      "V1 out 0 dc {sin(a)+sin(10*a/3) + sin(b)+sin(10*b/3)}\n"
      "R1 out 0 1\n"
      ".control\n"
      "optimize -dparam a 2.7 2.7 7.5 -dparam b 2.7 2.7 7.5 -analysis op "
      "-minimize v(out) -method pso -swarmsize 40 -maxiter 120 -seed 1 -tol 1e-9\n"
      ".endc\n.end\n")
o2 = run(D2)
a2, b2, f2 = optval(o2, "a"), optval(o2, "b"), objective(o2)
ok2d = (a2 is not None and b2 is not None and f2 is not None
        and abs(a2 - P_STAR) < 0.1 and abs(b2 - P_STAR) < 0.1 and f2 < -3.75)
check("[2-D] PSO finds both coordinates of a 2-D multimodal min (f*=-3.799)",
      ok2d, f"(a={a2}, b={b2}, f={f2})")

# tidy
import glob
for g in glob.glob(os.path.join(SCRATCH, "*")):
    try:
        os.remove(g)
    except OSError:
        pass
try:
    os.rmdir(SCRATCH)
except OSError:
    pass

print(f"\n{passed} passed, {failed} failed")
raise SystemExit(1 if failed else 0)
