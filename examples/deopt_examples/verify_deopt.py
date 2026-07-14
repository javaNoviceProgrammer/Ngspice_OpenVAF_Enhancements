#!/usr/bin/env python3
"""Enhancement-195: differential evolution (`optimize -method de`).

E-194 added particle swarm (`-method pso`) as the optimizer's first GLOBAL method.
E-195 adds a second: differential evolution (`-method de`), the other workhorse
global, population-based, derivative-free optimizer. Instead of pulling particles
toward remembered bests, DE builds each trial from a scaled DIFFERENCE of random
population members -- v = a + F*(b - c) -- then binomially crosses it with the
target vector, and keeps it only if it is no worse (greedy selection). The
difference vector self-scales to the population's own spread, so DE adapts its
step size automatically and is robust on rugged / discontinuous landscapes.

Same multimodal testbed as PSO: f(p) = sin(p) + sin(10 p / 3) over [2.7, 7.5]
(global p* = 5.1457, f* = -1.8996; higher local minima that trap a downhill
method started at the p = 2.7 corner), evaluated through numparam as
`V1 out 0 dc {f(p)}` with p tuned via `-dparam`.

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

SCRATCH = tempfile.mkdtemp(prefix="deopt_")
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


D1 = ("* de multimodal 1-D\n"
      ".param p=2.7\n"
      "V1 out 0 dc {sin(p) + sin(10*p/3)}\n"
      "R1 out 0 1\n"
      ".control\n%s\n.endc\n.end\n")


def opt1d(method, seed=1):
    cmd = (f"optimize -dparam p 2.7 2.7 7.5 -analysis op -minimize v(out) "
           f"-method {method} -swarmsize 24 -maxiter 60 -seed {seed} -tol 1e-8")
    return run(D1 % cmd)


# ---- 1. DE finds the GLOBAL optimum from the trapping corner start ----
o = opt1d("de")
p_de, f_de = optval(o, "p"), objective(o)
glob = (p_de is not None and abs(p_de - P_STAR) < 0.05
        and f_de is not None and f_de < -1.88)
check("[de] finds the global optimum p*=5.146, f*=-1.900 (from the p=2.7 corner)",
      glob, f"(p={p_de}, f={f_de})")

# ---- 2. Nelder-Mead from the SAME start is trapped in a local minimum ----
onm = opt1d("nm")
f_nm, p_nm = objective(onm), optval(onm, "p")
trapped = (f_nm is not None and f_nm > -1.5)
check("[nm] the local simplex is trapped in a higher local minimum (DE's advantage)",
      trapped and f_de is not None and f_de < f_nm - 0.3,
      f"(nm f={f_nm} at p={p_nm}; de f={f_de})")

# ---- 3. reproducible: the same seed gives an identical result ----
a = objective(opt1d("de", seed=7))
b = objective(opt1d("de", seed=7))
check("[repro] a fixed -seed is reproducible (same objective twice)",
      a is not None and b is not None and a == b, f"({a} vs {b})")

# ---- 4. robust: several seeds all reach the global basin ----
fs = [objective(opt1d("de", seed=s)) for s in (1, 3, 11, 29)]
allglobal = all(f is not None and f < -1.88 for f in fs)
check("[robust] independent seeds all reach the global (f < -1.88)",
      allglobal, f"({[f'{f:.4f}' if f else None for f in fs]})")

# ---- 5. DE works in least-squares (-target) mode too ----
cmd = ("optimize -dparam p 2.7 2.7 7.5 -analysis op -target v(out) -1.8996 "
       "-method de -swarmsize 24 -maxiter 60 -seed 1")
ols = run(D1 % cmd)
p_ls, r_ls = optval(ols, "p"), residual(ols)
check("[lsq] DE minimizes a -target least-squares objective (recovers p*)",
      p_ls is not None and abs(p_ls - P_STAR) < 0.05 and r_ls is not None and r_ls < 1e-6,
      f"(p={p_ls}, resid={r_ls})")

# ---- 6. 2-D separable multimodal: DE finds both coordinates ----
D2 = ("* de multimodal 2-D\n"
      ".param a=2.7\n.param b=2.7\n"
      "V1 out 0 dc {sin(a)+sin(10*a/3) + sin(b)+sin(10*b/3)}\n"
      "R1 out 0 1\n"
      ".control\n"
      "optimize -dparam a 2.7 2.7 7.5 -dparam b 2.7 2.7 7.5 -analysis op "
      "-minimize v(out) -method de -swarmsize 40 -maxiter 120 -seed 1 -tol 1e-9\n"
      ".endc\n.end\n")
o2 = run(D2)
a2, b2, f2 = optval(o2, "a"), optval(o2, "b"), objective(o2)
ok2d = (a2 is not None and b2 is not None and f2 is not None
        and abs(a2 - P_STAR) < 0.1 and abs(b2 - P_STAR) < 0.1 and f2 < -3.75)
check("[2-D] DE finds both coordinates of a 2-D multimodal min (f*=-3.799)",
      ok2d, f"(a={a2}, b={b2}, f={f2})")

# ---- 7. the global toolbox: DE and PSO agree on the global; NM does not ----
f_pso = objective(opt1d("pso"))
agree = (f_de is not None and f_pso is not None
         and abs(f_de - f_pso) < 0.01               # both at the global
         and f_nm is not None and f_nm > f_de + 0.3)  # NM stuck above it
check("[toolbox] DE and PSO both reach the global; the local NM does not",
      agree, f"(de={f_de}, pso={f_pso}, nm={f_nm})")

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
