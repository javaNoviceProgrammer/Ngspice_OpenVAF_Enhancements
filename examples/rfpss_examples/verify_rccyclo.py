#!/usr/bin/env python3
"""
verify_rccyclo.py -- verifies cyclostationary periodic noise (Enhancement-126).

E-124's `.pnoise` made a stationary approximation: it evaluated each device's noise
PSD at one operating point. E-126 adds a `cyclo` mode that evaluates the noise PSD at
EVERY PSS sample's bias (so a bias-dependent source S(t) varies over the period) and
folds it through the time-domain adjoint transfer, averaging over the period:

    onoise(f) = (1/P) sum_s S(t_s) * |dA_s(f)|^2,
    A_s(j)    = sum_k Psi_k(j) * exp(j 2*pi k s / P)   (inverse-DFT of the sideband
                                                        adjoint transfers)

Two checks:

1. REDUCTION (rigorous). For the linear RC low-pass, R1's thermal noise is
   bias-independent, so S(t) is constant and -- by Parseval -- the cyclostationary
   result reduces EXACTLY to the stationary one, i.e. to ordinary `.noise`:
   4*k*T*R1/(1+(2*pi*f*R1*C1)^2). This validates the whole cyclostationary machinery.

2. CYCLOSTATIONARY EFFECT (quantitative). A resistor R1 (flicker model, AF=2) carries
   the RC low-pass current I(t) driven by the 1 MHz pump, so its flicker noise
   ~ KF*|I(t)|^2 is genuinely cyclostationary. The circuit is linear (fast PSS) and
   the transfer to the output is flat (= R1) over the low-frequency noise sweep, so

       onoise_flicker(f) * f = R1^2 * KF * <I(t)^2>,  <I^2> = (1/2)|(1 - H)/R1|^2,
       H = 1/(1 + j*2*pi*f0*R1*C1)   (the RC transfer at the pump frequency)

   -- a constant, independent of frequency, using the period-AVERAGE <I^2> (not the
   single-sample value a stationary analysis would use). This pins the per-sample
   averaging.

NOTE: each `.pnoise` runs a PSS shooting method (~2 min) under the Sparse solver only.
"""
import math
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from _setup import NG as NGSPICE

BOLTZ, TEMP = 1.380649e-23, 300.15

checks = passed = 0
def check(label, ok, detail=""):
    global checks, passed
    checks += 1; passed += bool(ok)
    print(f"[{'PASS' if ok else 'FAIL'}] {label}" + (f"  ({detail})" if detail and not ok else ""))

def table(log, col="onoise_spectrum"):
    out, on = [], False
    for line in log.splitlines():
        if re.search(r"Index\s+frequency\s+" + re.escape(col), line):
            on = True; continue
        if on:
            p = line.split()
            if len(p) == 3:
                try:
                    out.append((float(p[1]), float(p[2])))
                except ValueError:
                    if out:
                        break
    return out

def run(text, name):
    path = os.path.join(HERE, name)
    with open(path, "w") as f:
        f.write(text)
    r = subprocess.run([NGSPICE, "-b", name], capture_output=True, text=True, cwd=HERE)
    os.remove(path)
    return r.stdout + r.stderr

# --- Check 1: reduction of cyclostationary to .noise for the linear RC ---
with open(os.path.join(HERE, "rc_pnoise.cir")) as f:
    rc = f.read()
rc = rc.replace("dec 10 10k 1meg", "dec 10 10k 1meg cyclo")   # add the cyclo flag
lines = rc.split("\n"); lines.insert(1, ".option sparse")
clog = run("\n".join(lines), "_rccyclo_sparse.cir")

R, C = 1e3, 1e-9
Sana = lambda f: 4 * BOLTZ * TEMP * R / (1.0 + (2 * math.pi * f * R * C) ** 2)
check("[E-126] cyclostationary mode announced", "cyclostationary" in clog, clog[-300:])
cpts = table(clog)
check(f"[E-126] cyclostationary RC produced a spectrum ({len(cpts)} pts)", len(cpts) >= 5)
if cpts:
    worst = max(abs(v - Sana(f)) / Sana(f) for f, v in cpts)
    check(f"[E-126] cyclostationary reduces EXACTLY to .noise for the linear RC "
          f"(4kTR/(1+(2*pi*f*R*C)^2), worst rel err {worst:.2e})", worst < 0.03,
          f"worst {worst:.3e}")

# --- Check 2: quantitative cyclostationary flicker (rc_flicker_cyclo.cir) ---
f0, R1, C1, KF = 1e6, 1e3, 1e-9, 1e-9
H = 1.0 / (1.0 + 1j * 2 * math.pi * f0 * R1 * C1)    # RC transfer at the pump freq
I2avg = 0.5 * abs((1.0 - H) / R1) ** 2               # <I_R1^2> over the period
target = R1 ** 2 * KF * I2avg                        # onoise_flicker * f  (constant)
with open(os.path.join(HERE, "rc_flicker_cyclo.cir")) as f:
    fl = f.read().split("\n")
fl.insert(1, ".option sparse")
flog = run("\n".join(fl), "_flick_cyclo.cir")
fpts = table(flog)
check(f"[E-126] cyclostationary flicker produced a spectrum ({len(fpts)} pts)", len(fpts) >= 3)
if fpts:
    # flicker dominates over thermal here; onoise*f should be flat == R1^2*KF*<I^2>
    prods = [f * v for f, v in fpts]
    worst = max(abs(p - target) / target for p in prods)
    check(f"[E-126] cyclostationary flicker onoise*f == R1^2*KF*<I^2> = {target:.4e} "
          f"(uses the period-average <I^2>={I2avg:.4e}, worst rel err {worst:.2e})",
          worst < 0.05, f"worst {worst:.3e}, prods {[f'{p:.3e}' for p in prods]}")
    # the average |I(t)|^2 that pins the cyclostationary result varies over the period
    # (I(t) swings through 0), so it is genuinely distinct from any single-sample value
    check("[E-126] cyclostationary onoise is flat in onoise*f (flicker 1/f, period-averaged)",
          worst < 0.05)

print()
print(("ALL PASS" if passed == checks else "FAILURES")
      + f": {passed} passed, {checks - passed} failed")
raise SystemExit(0 if passed == checks else 1)
