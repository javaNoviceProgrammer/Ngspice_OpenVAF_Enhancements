#!/usr/bin/env python3
"""
verify_rcpss.py -- verifies Enhancement-117 (periodic steady state, PSS, is now a
shipped, hardened analysis) through the committed ngspice.

PSS was experimental: gated behind `--enable-pss` (so `.pss` was unimplemented in
every shipped build) and, when enabled, it flooded stderr with ~230 lines of
shooting-loop trace per run. E-117 makes PSS build by default and routes the
per-iteration trace through `set ngdebug`, leaving a clean converged summary and
the harmonic table.

This runs a driven RC low-pass through `.pss` and checks the periodic steady
state matches the analytic AC response:

  [1] `.pss` is implemented (not "unimplemented dot command")
  [2] PSS converges and reports the fundamental frequency (~1 MHz)
  [3] the fundamental harmonic magnitude equals |H(1MHz)| = 0.15714 (R=1k, C=1n)
  [4] output is clean by default -- no shooting-loop trace unless `set ngdebug`

NOTE: PSS is a shooting method (it simulates many drive periods), so this single
deck takes ~1-2 minutes. It is intentionally NOT run under both linear solvers.
"""
import math
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from _setup import NG as NGSPICE

checks = passed = 0
def check(label, ok, detail=""):
    global checks, passed
    checks += 1; passed += bool(ok)
    print(f"[{'PASS' if ok else 'FAIL'}] {label}" + (f"  ({detail})" if detail and not ok else ""))

def run(name):
    r = subprocess.run([NGSPICE, "-b", name], capture_output=True, text=True, cwd=HERE)
    return r.stdout + r.stderr

# analytic fundamental of the RC low-pass at the 1 MHz drive
R, C, f0 = 1e3, 1e-9, 1e6
H = 1.0 / math.hypot(1.0, 2 * math.pi * f0 * R * C)   # 0.157136...

log = run("rc_pss.cir")

check("`.pss` is implemented", "unimplemented dot command" not in log,
      "PSS not built into this ngspice")

m = re.search(r"predicted fundamental frequency is\s+([-\d.eE+]+)\s*Hz", log)
freq = float(m.group(1)) if m else None
check("PSS converges and reports the fundamental frequency",
      "Convergence reached" in log and freq is not None,
      "no convergence line")
check(f"fundamental frequency ~ 1 MHz (got {freq})",
      freq is not None and abs(freq - f0) / f0 < 0.01, str(freq))

# frequency-domain table rows: "<idx>\t<freq>\t<mag>"; row 1 is the fundamental
fund = None
for line in log.splitlines():
    p = line.split()
    if len(p) == 3 and p[0] == "1":
        try:
            ffreq, fmag = float(p[1]), abs(float(p[2]))
            if abs(ffreq - f0) / f0 < 0.05:
                fund = fmag
                break
        except ValueError:
            pass
check(f"fundamental magnitude == |H(1MHz)| = {H:.5f} (got {fund})",
      fund is not None and abs(fund - H) / H < 0.02, str(fund))

# default output must not carry the shooting-loop trace
trace = sum(1 for ln in log.splitlines()
            if re.search(r"Shooting cycle iteration|Updated guessed frequency|IN_PSS", ln))
check(f"clean default output -- no shooting-loop trace ({trace} trace lines)",
      trace == 0, f"{trace} trace lines leaked")

print()
print(("ALL PASS" if passed == checks else "FAILURES")
      + f": {passed} passed, {checks - passed} failed")
raise SystemExit(0 if passed == checks else 1)
