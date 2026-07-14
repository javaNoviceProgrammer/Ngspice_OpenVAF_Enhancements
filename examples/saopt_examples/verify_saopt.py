#!/usr/bin/env python3
"""Enhancement-196: simulated annealing (`optimize -method sa`).

E-194/195 added two population-based global methods (particle swarm, differential
evolution). E-196 adds the classic single-walker global optimizer: simulated
annealing (`-method sa`). From the current point it proposes a random neighbour
and accepts it if it is better, OR -- with probability exp(-Dcost/T) -- if it is
worse (the Metropolis rule), so it climbs out of a local minimum while the
"temperature" T is high, then settles as T is cooled geometrically toward zero.
It evaluates ONE candidate per step (no population), so it is the lightest-weight
global method -- attractive when each analysis is expensive. The initial
temperature and step size are auto-scaled to the problem.

Same multimodal testbed as PSO/DE: f(p) = sin(p) + sin(10 p / 3) over [2.7, 7.5]
(global p* = 5.1457, f* = -1.8996; higher local minima that trap a downhill method
started at the p = 2.7 corner), via numparam `V1 out 0 dc {f(p)}` and `-dparam`.
A single walker refines a little more loosely than a population, so the tolerances
below are set to the global BASIN (f < -1.85, |p - p*| < 0.05) rather than machine
precision.

It is a front-end command, independent of the linear solver, so it runs once.

Every SPICE deck starts with a title line (SPICE treats line 1 as the title!).
"""
import os
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from _setup import NG as NGSPICE

SCRATCH = tempfile.mkdtemp(prefix="saopt_")
passed = failed = 0
P_STAR = 5.14573                       # true 1-D global optimum


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


D1 = ("* sa multimodal 1-D\n"
      ".param p=2.7\n"
      "V1 out 0 dc {sin(p) + sin(10*p/3)}\n"
      "R1 out 0 1\n"
      ".control\n%s\n.endc\n.end\n")


def opt1d(method, seed=1, maxiter=60):
    cmd = (f"optimize -dparam p 2.7 2.7 7.5 -analysis op -minimize v(out) "
           f"-method {method} -swarmsize 24 -maxiter {maxiter} -seed {seed} -tol 1e-8")
    return run(D1 % cmd)


# ---- 1. SA finds the GLOBAL basin from the trapping corner start ----
o = opt1d("sa")
p_sa, f_sa = optval(o, "p"), objective(o)
glob = (p_sa is not None and abs(p_sa - P_STAR) < 0.05
        and f_sa is not None and f_sa < -1.85)
check("[sa] finds the global optimum p*=5.146, f*=-1.900 (from the p=2.7 corner)",
      glob, f"(p={p_sa}, f={f_sa})")

# ---- 2. Nelder-Mead from the SAME start is trapped in a local minimum ----
onm = opt1d("nm")
f_nm, p_nm = objective(onm), optval(onm, "p")
trapped = (f_nm is not None and f_nm > -1.5)
check("[nm] the local simplex is trapped in a higher local minimum (SA's advantage)",
      trapped and f_sa is not None and f_sa < f_nm - 0.3,
      f"(nm f={f_nm} at p={p_nm}; sa f={f_sa})")

# ---- 3. reproducible: the same seed gives an identical result ----
a = objective(opt1d("sa", seed=7))
b = objective(opt1d("sa", seed=7))
check("[repro] a fixed -seed is reproducible (same objective twice)",
      a is not None and b is not None and a == b, f"({a} vs {b})")

# ---- 4. robust: several seeds all reach the global basin ----
fs = [objective(opt1d("sa", seed=s)) for s in (1, 3, 11, 29)]
allglobal = all(f is not None and f < -1.85 for f in fs)
check("[robust] independent seeds all reach the global basin (f < -1.85)",
      allglobal, f"({[f'{f:.4f}' if f else None for f in fs]})")

# ---- 5. SA works in least-squares (-target) mode too ----
cmd = ("optimize -dparam p 2.7 2.7 7.5 -analysis op -target v(out) -1.8996 "
       "-method sa -maxiter 80 -seed 3")
ols = run(D1 % cmd)
p_ls, r_ls = optval(ols, "p"), residual(ols)
check("[lsq] SA minimizes a -target least-squares objective (recovers p*)",
      p_ls is not None and abs(p_ls - P_STAR) < 0.05 and r_ls is not None and r_ls < 1e-3,
      f"(p={p_ls}, resid={r_ls})")

# ---- 6. 2-D separable multimodal: SA finds both coordinates ----
D2 = ("* sa multimodal 2-D\n"
      ".param a=2.7\n.param b=2.7\n"
      "V1 out 0 dc {sin(a)+sin(10*a/3) + sin(b)+sin(10*b/3)}\n"
      "R1 out 0 1\n"
      ".control\n"
      "optimize -dparam a 2.7 2.7 7.5 -dparam b 2.7 2.7 7.5 -analysis op "
      "-minimize v(out) -method sa -maxiter 150 -seed 3 -tol 1e-9\n"
      ".endc\n.end\n")
o2 = run(D2)
a2, b2, f2 = optval(o2, "a"), optval(o2, "b"), objective(o2)
ok2d = (a2 is not None and b2 is not None and f2 is not None
        and abs(a2 - P_STAR) < 0.06 and abs(b2 - P_STAR) < 0.06 and f2 < -3.7)
check("[2-D] SA finds both coordinates of a 2-D multimodal min (f*=-3.799)",
      ok2d, f"(a={a2}, b={b2}, f={f2})")

# ---- 7. the complete toolbox: the three GLOBAL methods reach the global; the
#         local NM does not ----
f_pso = objective(opt1d("pso"))
f_de = objective(opt1d("de"))
allg = (f_sa is not None and f_pso is not None and f_de is not None
        and all(f < -1.85 for f in (f_sa, f_pso, f_de))
        and f_nm is not None and f_nm > -1.5)
check("[toolbox] all three global methods (sa/pso/de) reach the global; local nm does not",
      allg, f"(sa={f_sa}, pso={f_pso}, de={f_de}, nm={f_nm})")

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
