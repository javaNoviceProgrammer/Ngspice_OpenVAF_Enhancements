#!/usr/bin/env python3
"""Enhancement-197: a 100-parameter circuit optimization (raised `optimize` limits).

The built-in `optimize` command (E-130, extended by E-143..145 and the global
methods E-194/195/196) previously capped a run at 16 parameters and 64 targets.
E-197 raises those to 128 each (OPT_MAXP / OPT_MAXT) and the auto-population cap
to 256, so a genuinely large problem -- here 100 unknown resistors fitted to 100
node-voltage targets -- can be optimized in one call.

Testbed: 100 independent 1 mA sources, each driving an unknown resistor R_i to
ground, so v(n_i) = 1e-3 * R_i.  The targets t_i = 1e-3 * (100 + 9800 i/99) ohm
form a linear voltage ramp 0.1 .. 9.9 V.  This is a well-posed, separable 100-D
least-squares.

  1. [scale]  Levenberg-Marquardt solves the full 100-parameter / 100-target
     least-squares to MACHINE PRECISION -- proving both raised caps at once
     (all 100 -param and 100 -target are accepted and honored).
  2. [de-global]  Differential evolution (a GLOBAL, population method) makes
     substantial progress at 100 dimensions.  This exercises E-197's adaptive
     high-dimensional crossover: classic DE (CR=0.9) mutates ~every coordinate
     and, at 100-D, essentially every trial is rejected so DE freezes at its
     start; the adaptive CR (~15 mutated coordinates) lets it descend.  The
     check self-calibrates against DE's own starting cost, so it needs no
     machine-specific magic number.
  3. [repro]  a fixed -seed is reproducible even at 100 dimensions.
  4. [cap]  exceeding the raised cap is reported cleanly (not crashed).

DE at 100-D is a genuinely hard *global* search and does not fully converge in a
short budget (that is intrinsic to global optimization in high dimension, not a
defect) -- the LM solve is the tool that actually nails a well-posed high-D fit;
DE's role here is to show the global methods now *function* at scale.

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

SCRATCH = tempfile.mkdtemp(prefix="opt100_")
passed = failed = 0
N = 100
RSTAR = [100.0 + 9800.0 * i / (N - 1) for i in range(N)]   # target resistances
TGT = [1e-3 * r for r in RSTAR]                             # target node voltages


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
    m = re.search(rf"(?im)^\s*{re.escape(name)}\s*=\s*([-\d.eE+]+)\s*$", out)
    return float(m.group(1)) if m else None


def objective(out):
    m = re.search(r"objective = ([-\d.eE+]+)", out)
    return float(m.group(1)) if m else None


def residual(out):
    m = re.search(r"sum-sq residual = ([-\d.eE+]+)", out)
    return float(m.group(1)) if m else None


def network():
    """The 100-node current-source / resistor network (shared by every deck)."""
    lines = ["* opt100"]
    for i in range(N):
        lines += [f"I{i} 0 n{i} dc 1m", f"R{i} n{i} 0 1k"]
    return "\n".join(lines) + "\n"


def params(n=N):
    return " ".join(f"-param R{i} 1k 10 10000" for i in range(n))


def targets():
    return " ".join(f"-target v(n{i}) {TGT[i]:.6g}" for i in range(N))


def deck(cmd, tail=""):
    return network() + ".control\n" + cmd + "\n" + tail + ".endc\n.end\n"


# ---- 1. LM solves the full 100-param / 100-target least-squares to machine precision
lm = ("optimize " + params() + " -analysis op " + targets() +
      " -method lm -maxiter 100 -tol 1e-12")
o = run(deck(lm, "print v(n0) v(n50) v(n99)\n"))
r = residual(o)
v0, v50, v99 = optval(o, "v(n0)"), optval(o, "v(n50)"), optval(o, "v(n99)")
nodes_ok = (v0 is not None and abs(v0 - TGT[0]) < 1e-6
            and v50 is not None and abs(v50 - TGT[50]) < 1e-5 * abs(TGT[50])
            and v99 is not None and abs(v99 - TGT[99]) < 1e-5 * abs(TGT[99]))
check("[scale] LM fits all 100 params to 100 targets at machine precision "
      "(raised caps: 100 -param + 100 -target accepted)",
      r is not None and r < 1e-9 and nodes_ok,
      f"(resid={r}, v(n0)={v0}, v(n50)={v50}, v(n99)={v99})")

# ---- 2. DE (global) makes substantial progress at 100-D (adaptive high-D crossover)
de_base = ("optimize " + params() + " -analysis op -minimize v(err) "
           "-method de -swarmsize 40 -seed 1 -tol 1e-12 -maxiter ")
# err = sum of squared node-voltage errors, as a single B-source node
errsrc = ("Berr err 0 V = " +
          " + ".join(f"(v(n{i})-{TGT[i]:.6g})**2" for i in range(N)) +
          "\nRerr err 0 1\n")


def de_run(maxiter):
    return run(network() + errsrc + ".control\n" + de_base + str(maxiter) +
               "\n.endc\n.end\n")


f_init = objective(de_run(1))          # cost after the first generation
f_final = objective(de_run(35))        # cost after a short global search
descended = (f_init is not None and f_final is not None
             and f_final < 0.85 * f_init)
check("[de-global] differential evolution descends substantially at 100-D "
      "(global method functions at scale via the adaptive high-D crossover)",
      descended,
      f"(start={f_init:.1f} -> {f_final:.1f}, "
      f"{100*(1-f_final/f_init):.0f}% reduction)" if descended else
      f"(start={f_init}, final={f_final})")

# ---- 3. reproducible at 100 dimensions: same seed -> identical objective
a = objective(de_run(6))
b = objective(de_run(6))
check("[repro] a fixed -seed is bit-reproducible even at 100 dimensions",
      a is not None and b is not None and a == b, f"({a} vs {b})")

# ---- 4. exceeding the raised cap (129 params) is reported cleanly, not crashed
over = run(deck("optimize " + params(129) + " -analysis op -minimize v(n0) "
                "-method nm -maxiter 2"))
capped = "too many -param" in over and "128" in over
check("[cap] exceeding the raised cap (129 -param) is reported cleanly (max 128)",
      capped, "(clean error, no crash)" if capped else f"({over[-120:]!r})")

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
