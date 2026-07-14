#!/usr/bin/env python3
"""Enhancement-189: `sweep ... -overlay` -- .step-style waveform overlay.

The `sweep` command (Enhancement-146) steps any circuit knob, runs an inner
analysis at each point, and records each output's LAST value into a `sweep`
plot (a transfer curve vs the knob). The per-point analysis plots are retained
but overlaying their full waveforms was a manual chore.

`-overlay` collects each point's full output WAVEFORM, linearly resamples them
onto a common independent-variable grid (the runs land on different adaptive
time/frequency grids), and builds a single `sweepwave` plot -- one vector per
(output, knob value), named `<output>_<value>` -- so the whole family plots at
once (the classic HSPICE `.step` overlay).

This suite sweeps R on an RC step response, whose exact answer is
`v(out) = 1 - exp(-t/RC)`, and checks each overlaid curve against it. It is a
front-end command, independent of the linear solver, so it runs once.

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

SCRATCH = tempfile.mkdtemp(prefix="sweepwave_")
passed = failed = 0


def check(label, ok, detail=""):
    global passed, failed
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  {detail}" if detail else ""))
    if ok:
        passed += 1
    else:
        failed += 1


def run(deck):
    open(os.path.join(SCRATCH, "sw.cir"), "w").write(deck)
    r = subprocess.run([NGSPICE, "-b", "sw.cir"], capture_output=True, text=True,
                       cwd=SCRATCH, timeout=120)
    return r.stdout + r.stderr


def read_cols(fname, ncol):
    """wrdata writes each vector as a (scale, value) column pair, so N vectors
    give 2N columns: (t0,v0, t1,v1, ...)."""
    cols = [[] for _ in range(ncol)]
    for ln in open(os.path.join(SCRATCH, fname)):
        p = ln.split()
        if len(p) >= 2 * ncol:
            try:
                fv = [float(x) for x in p[:2 * ncol]]
            except ValueError:
                continue
            for k in range(ncol):
                cols[k].append((fv[2 * k], fv[2 * k + 1]))
    return cols


RC = ("* RC step, sweep R, overlay\n"
      "Vin in 0 PULSE(0 1 0 0.1n 0.1n 100u 200u)\n"
      "R1 in out 1k\n"
      "C1 out 0 1n\n")

# ---- 1. the overlay family matches the analytic RC step response ----
log = run(RC +
          ".control\n"
          "sweep R1 list 1k 2k 4k -analysis tran 5n 5u -output vo=v(out) -overlay\n"
          "wrdata ov.dat vo_1000 vo_2000 vo_4000\n"
          ".endc\n.end\n")
made = re.search(r"overlay of (\d+) waveforms.*resampled to (\d+) points", log)
check("[overlay] sweepwave plot created", made is not None,
      f"({made.group(0)})" if made else log.strip().splitlines()[-1][:70])

if made and os.path.exists(os.path.join(SCRATCH, "ov.dat")):
    cols = read_cols("ov.dat", 3)          # 3 output vectors, each (t, value)
    worst = 0.0
    for k, rc in enumerate((1e-6, 2e-6, 4e-6)):
        for (t, v) in cols[k]:
            if t <= 0:
                continue
            worst = max(worst, abs(v - (1.0 - math.exp(-t / rc))))
    check("[overlay] each curve == 1-exp(-t/RC) (RC=1/2/4 us)", worst < 2e-3,
          f"(worst |err| = {worst:.2e})")
else:
    check("[overlay] each curve == 1-exp(-t/RC)", False, "no ov.dat")

# ---- 2. distinct per-value vector names ----
log = run(RC +
          ".control\n"
          "sweep R1 list 1k 2k 4k -analysis tran 5n 5u -output vo=v(out) -overlay\n"
          "echo NAMES: $&vo_1000[0] $&vo_2000[0] $&vo_4000[0]\n"
          ".endc\n.end\n")
check("[overlay] one vector per knob value (vo_1000/2000/4000)",
      "NAMES:" in log and "no such vector" not in log.lower())

# ---- 3. -overlay on `op` (no waveform) is ignored gracefully, not an error ----
log = run(RC +
          ".control\n"
          "sweep R1 list 1k 2k 4k -output v(out) -overlay\n"
          ".endc\n.end\n")
check("[overlay] gracefully ignored for a scalar (op) analysis",
      "no waveform to overlay" in log and "overlay of" not in log)

# ---- 4. the E-146 last-value summary curve is intact (shared data[] path) ----
# A plain sweep (no -overlay) leaves the summary plot current, so `print vo`
# reads the transfer curve directly. After 50us >> 4*RC the step has settled to
# ~1 for every R, so all three last-values must be ~1.
log = run(RC +
          ".control\n"
          "sweep R1 list 1k 2k 4k -analysis tran 5n 50u -output vo=v(out)\n"
          "print vo\n"
          ".endc\n.end\n")
# `print vo` on a 3-point vector prints one "index  value" row per point
vals = re.findall(r"^\s*\d+\s+([\d.eE+-]+)\s*$", log, re.M)
settled = [float(x) for x in vals] if vals else []
check("[summary] last-value curve intact (settled ~1)",
      len(settled) >= 3 and all(abs(v - 1.0) < 0.05 for v in settled[-3:]),
      f"(settled {settled[-3:]})" if settled else "no summary values")

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
