#!/usr/bin/env python3
"""Enhancement-191: `.ac lin 2` / `.sp lin 2` off-by-one fix.

The linear frequency-sweep step was guarded by `numberSteps - 1 > 1` in the AC
(`acan.c`) and S-parameter (`span.c`) analyses -- i.e. a real step was computed
only for N >= 3. Exactly `lin 2` fell through to the single-point patch
(`freqDelta = 0`, which stops the sweep after the first point), so a two-point
linear AC/SP sweep produced ONE frequency point instead of two. Changing the
guard to `> 1` restores the two-endpoint sweep while preserving the genuine
`lin 1` single-point case (the noise analysis already used this correct form).

Checks (under both solvers):
  1. `ac lin 2` gives exactly the two endpoints [fstart, fstop];
  2. both points are real solved points, matching the RC transfer function
     H(jw) = 1/(1 + jwRC) -- so the recovered point is genuine, not a duplicate;
  3. `ac lin 1` still gives ONE point at fstart (single-point case preserved);
  4. `ac lin N` gives N linearly-spaced points (N = 3, 5, 10);
  5. `sp lin 2` gives two points with the analytic series-R S-parameters
     (S11 = 1/3, S21 = 2/3 for a 50 ohm series R between 50 ohm ports).

Every SPICE deck starts with a title line (SPICE treats line 1 as the title!).
"""
import cmath
import math
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from _setup import NG as NGSPICE
from _setup import check_both_solvers as _check_both_solvers
_check_both_solvers(__file__)   # verify under BOTH KLU and Sparse solvers

SCRATCH = tempfile.mkdtemp(prefix="aclin2_")
passed = failed = 0
R, C = 1e3, 100e-9


def check(label, ok, detail=""):
    global passed, failed
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  {detail}" if detail else ""))
    if ok:
        passed += 1
    else:
        failed += 1


def run(deck):
    open(os.path.join(SCRATCH, "d.cir"), "w").write(deck)
    r = subprocess.run([NGSPICE, "-b", "d.cir"], capture_output=True, text=True,
                       cwd=SCRATCH, timeout=120)
    return r.stdout + r.stderr


def read_rows(fname, ncomplex=1):
    """Read a wrdata file of ONE complex vector: each row is freq, re, im."""
    rows = []
    for ln in open(os.path.join(SCRATCH, fname)):
        p = ln.split()
        if len(p) >= 1 + 2 * ncomplex:
            try:
                rows.append([float(x) for x in p[:1 + 2 * ncomplex]])
            except ValueError:
                pass
    return rows


RC = ("* RC low-pass for the AC linear-sweep fix\n"
      "V1 in 0 AC 1\n"
      f"R1 in out {R:g}\n"
      f"C1 out 0 {C:g}\n")


def H(f):
    return 1.0 / (1.0 + 1j * 2 * math.pi * f * R * C)


# ---- 1 & 2. ac lin 2 -> two endpoints, each matching the RC transfer fn ----
run(RC + ".control\nac lin 2 1k 5k\nwrdata l2.dat v(out)\n.endc\n.end\n")
rows = read_rows("l2.dat")
freqs = [r[0] for r in rows]
two_pts = len(rows) == 2 and abs(freqs[0] - 1e3) < 1 and abs(freqs[-1] - 5e3) < 1
check("ac lin 2 -> exactly two points at [fstart, fstop]", two_pts,
      f"(got {len(rows)} pts: {freqs})")
if two_pts:
    worst = max(abs(complex(r[1], r[2]) - H(r[0])) for r in rows)
    check("ac lin 2 -> both are real solved points (match 1/(1+jwRC))",
          worst < 1e-6, f"(worst |err| = {worst:.2e})")
else:
    check("ac lin 2 -> both match 1/(1+jwRC)", False, "wrong point count")

# ---- 3. ac lin 1 -> one point at fstart (single-point case preserved) ----
run(RC + ".control\nac lin 1 2k 9k\nwrdata l1.dat v(out)\n.endc\n.end\n")
rows = read_rows("l1.dat")
check("ac lin 1 -> one point at fstart (patch preserved)",
      len(rows) == 1 and abs(rows[0][0] - 2e3) < 1,
      f"(got {len(rows)} pts)")

# ---- 4. ac lin N -> N linearly-spaced points ----
allN = True
detail = []
for N in (3, 5, 10):
    run(RC + f".control\nac lin {N} 1k 10k\nwrdata lN.dat v(out)\n.endc\n.end\n")
    rows = read_rows("lN.dat")
    freqs = [r[0] for r in rows]
    exp = [1e3 + i * (10e3 - 1e3) / (N - 1) for i in range(N)]
    okN = len(rows) == N and all(abs(a - b) < 1 for a, b in zip(freqs, exp))
    allN = allN and okN
    detail.append(f"N={N}:{len(rows)}")
check("ac lin N -> N linearly-spaced points (N=3,5,10)", allN, f"({', '.join(detail)})")

# ---- 5. sp lin 2 -> two points, analytic series-R S-parameters ----
SR = ("* series R=50 two-port, Z0=50: S11=1/3, S21=2/3\n"
      "V1 in 0 DC 0 AC 1 portnum 1 z0 50\n"
      "R1 in out 50\n"
      "V2 out 0 DC 0 AC 1 portnum 2 z0 50\n")
run(SR + ".control\nsp lin 2 1meg 2meg\n"
        "set wr_singlescale\nwrdata sp.dat S_1_1 S_2_1\n.endc\n.end\n")
rows = read_rows("sp.dat", ncomplex=2)   # freq, S11re, S11im, S21re, S21im (single scale)
if len(rows) == 2:
    worst = 0.0
    for r in rows:
        worst = max(worst, abs(complex(r[1], r[2]) - (1.0 / 3.0)))
        worst = max(worst, abs(complex(r[3], r[4]) - (2.0 / 3.0)))
    check("sp lin 2 -> two points, S11=1/3, S21=2/3", worst < 1e-6,
          f"(worst |err| = {worst:.2e})")
else:
    check("sp lin 2 -> two points", False, f"(got {len(rows)} pts)")

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
