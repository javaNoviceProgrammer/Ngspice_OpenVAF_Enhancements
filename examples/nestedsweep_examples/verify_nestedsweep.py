#!/usr/bin/env python3
"""Enhancement-190: nested multi-knob `sweep` (`-vs`) -- cartesian curve families.

The `sweep` command (Enhancement-146) stepped ONE knob and recorded each output's
last value into a `sweep` transfer curve. `-vs <knob> <spec>` adds OUTER knobs:
the inner (positional) knob stays the x-axis, and the outer knobs' cartesian
product forms a curve FAMILY -- one curve per output per outer combination, named
`<output>_<outerknob>_<value>...`. A single knob reduces exactly to E-146.

The testbed is an RC low-pass driven by a 1 V step. Sweeping R (inner) and C
(outer) makes each family curve the exact transfer curve at fixed C:

    v(out)|_{t=T} = 1 - exp(-T / (R*C))     as a function of R.

Checks: the family curves are created and match that closed form; the cartesian
run count is right; a `.param` outer knob (which forces an `alterparam`+`reset`
per outer step, re-applying the inner `alter` after each reset) still matches;
`-overlay` composes with the family; and a single knob still names its curve
plainly `vo` (E-146 unchanged). Front-end / solver-independent, so it runs once.

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

SCRATCH = tempfile.mkdtemp(prefix="nestedsweep_")
passed = failed = 0
T = 4e-6                                  # tran stop time; last value is recorded


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


def read_pairs(fname, ncol):
    """wrdata writes each vector as a (scale, value) column pair."""
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


def analytic(R, C):
    return 1.0 - math.exp(-T / (R * C))


# instance-knob RC (both R and C are device instances)
RC = ("* nested sweep RC, R inner x C outer\n"
      "Vin in 0 PULSE(0 1 0 0.1n 0.1n 100u 200u)\n"
      "R1 in out 1k\n"
      "C1 out 0 1n\n")

# ---- 1. the family is created: message reports the cartesian product ----
log = run(RC +
          ".control\n"
          f"sweep R1 list 1k 2k 4k -vs C1 list 1n 2n -analysis tran 5n {T:g} -output vo=v(out)\n"
          ".endc\n.end\n")
m = re.search(r"=\s*(\d+)\s+runs\s*->\s*(\d+)\s+curve", log)
check("[family] cartesian run/curve count reported (3x2=6 runs, 2 curves)",
      m is not None and m.group(1) == "6" and m.group(2) == "2",
      f"({m.group(0)})" if m else log.strip().splitlines()[-1][:70])

# ---- 2. each family curve == 1-exp(-T/(R*C)) ----
log = run(RC +
          ".control\n"
          f"sweep R1 list 1k 2k 4k -vs C1 list 1n 2n -analysis tran 5n {T:g} -output vo=v(out)\n"
          "wrdata fam.dat vo_c1_1e_09 vo_c1_2e_09\n"
          ".endc\n.end\n")
if os.path.exists(os.path.join(SCRATCH, "fam.dat")):
    cols = read_pairs("fam.dat", 2)        # 2 family curves, each (R, value)
    worst = 0.0
    for k, C in enumerate((1e-9, 2e-9)):
        for (R, v) in cols[k]:
            worst = max(worst, abs(v - analytic(R, C)))
    check("[family] each curve == 1-exp(-T/(R*C)) vs R", worst < 2e-3,
          f"(worst |err| = {worst:.2e})")
else:
    check("[family] each curve == 1-exp(-T/(R*C)) vs R", False, "no fam.dat")

# ---- 3. a `.param` OUTER knob (alterparam+reset per outer step) matches ----
# C is a symbolic .param, so each outer step re-sources the deck; the inner R
# `alter` must be re-applied after every reset. If the ordering were wrong the
# curves would not track the closed form.
RCP = ("* .param outer knob\n"
       "Vin in 0 PULSE(0 1 0 0.1n 0.1n 100u 200u)\n"
       ".param cval=1n\n"
       "R1 in out 1k\n"
       "C1 out 0 {cval}\n")
log = run(RCP +
          ".control\n"
          f"sweep R1 list 1k 2k 4k -vs cval list 1n 2n -analysis tran 5n {T:g} -output vo=v(out)\n"
          "wrdata fp.dat vo_cval_1e_09 vo_cval_2e_09\n"
          ".endc\n.end\n")
if os.path.exists(os.path.join(SCRATCH, "fp.dat")):
    cols = read_pairs("fp.dat", 2)
    worst = 0.0
    for k, C in enumerate((1e-9, 2e-9)):
        for (R, v) in cols[k]:
            worst = max(worst, abs(v - analytic(R, C)))
    check("[.param] outer .param knob family matches (reset/alter ordering)",
          worst < 2e-3, f"(worst |err| = {worst:.2e})")
else:
    check("[.param] outer .param knob family matches", False, "no fp.dat")

# ---- 4. -overlay composes with the family: one waveform per (output, point),
# named with BOTH knob values (<output>_<R>_<C>) ----
log = run(RC +
          ".control\n"
          f"sweep R1 list 1k 2k -vs C1 list 1n 2n -analysis tran 5n {T:g} -output vo=v(out) -overlay\n"
          "print vo_1000_1e_09[0] vo_2000_2e_09[0]\n"
          ".endc\n.end\n")
check("[overlay] family overlay names carry both knob values",
      "overlay of 4 waveforms" in log and
      "vo_1000_1e_09[0] =" in log and "vo_2000_2e_09[0] =" in log)

# ---- 5. backward-compat: a single knob still names its curve plainly `vo` ----
log = run(RC +
          ".control\n"
          f"sweep R1 list 1k 2k 4k -analysis tran 5n {T:g} -output vo=v(out)\n"
          "wrdata one.dat vo\n"
          ".endc\n.end\n")
one_ok = os.path.exists(os.path.join(SCRATCH, "one.dat"))
if one_ok:
    cols = read_pairs("one.dat", 1)
    worst = max(abs(v - analytic(R, 1e-9)) for (R, v) in cols[0]) if cols[0] else 9
    check("[compat] single knob -> curve named `vo`, matches E-146",
          worst < 2e-3 and "curve" not in log.split("into the 'sweep'")[0][-40:],
          f"(worst |err| = {worst:.2e})")
else:
    check("[compat] single knob -> curve named `vo`", False, "no one.dat")

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
