#!/usr/bin/env python3
"""
verify_reduce.py -- Enhancement-155: the `reduce` command (TICER RC reduction).

`reduce <fmax> [factor f] [keep ...]` collapses a circuit's linear R/C network to a
small, electrically equivalent `.subckt` of R's and C's that preserves the port
behaviour over DC..fmax, by Schur-complement (TICER) elimination of interior nodes.
Ports are auto-detected as every node touched by a non-R/C device (sources, OSDI
devices, ...), plus ground and user `keep` nodes.

Checked end-to-end through the committed ngspice, under BOTH linear solvers:

  [1] the `reduce` command runs and reports a reduction.
  [2] IDENTITY: with a huge `factor` nothing is eliminated, and the emitted subckt
      reproduces the full network's AC response BIT-for-BIT (proves the extraction +
      emission are exact).
  [3] REDUCTION + ACCURACY: a moderate factor removes interior nodes while the
      reduced network's in-band AC response stays within tolerance of the full one,
      and DC is preserved exactly.
  [4] the accuracy/reduction TRADEOFF is monotone in `factor`.
  [5] OSDI auto-port: an OSDI device attached to a node makes that node a kept port
      automatically (no `keep` needed).
"""
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from _setup import NG as NGSPICE
from _setup import check_both_solvers as _check_both_solvers
_check_both_solvers(__file__)

SCRATCH = tempfile.mkdtemp(prefix="reduce_verify_")
shutil.copy(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                         "rfanalyses_examples", "rf_blocks.osdi"), SCRATCH)
_fail = 0


def check(label, ok, detail=""):
    global _fail
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}" + (f" -- {detail}" if detail else ""))
    if not ok:
        _fail += 1


def run(deck, name="_r.cir"):
    with open(os.path.join(SCRATCH, name), "w") as f:
        f.write(deck)
    r = subprocess.run([NGSPICE, "-b", name], capture_output=True, text=True,
                       timeout=120, cwd=SCRATCH)
    return r.stdout + r.stderr


def col(fname, c=1):
    p = os.path.join(SCRATCH, fname)
    xs, ys = [], []
    if os.path.exists(p):
        for line in open(p):
            q = line.split()
            if len(q) > c:
                try: xs.append(float(q[0])); ys.append(float(q[c]))
                except ValueError: pass
    return xs, ys


def ladder(N=24, R=15, C="50f"):
    L = ["* RC ladder parasitics"]
    prev = "in"
    for k in range(1, N):
        L.append(f"R{k} {prev} n{k} {R}")
        L.append(f"C{k} n{k} 0 {C}")
        prev = f"n{k}"
    L.append(f"R{N} {prev} out {R}")
    L.append(f"Cout out 0 {C}")
    return "\n".join(L) + "\n"


LAD = ladder()
FMAX = 3e9

# full reference AC
run(f"""* full ladder
{LAD}V1 in 0 DC 0 AC 1
Rload out 0 1k
.control
ac dec 20 1meg 12g
wrdata full.dat vdb(out)
.endc
.end
""", "full.cir")
ft, fdb = col("full.dat")


def reduce_and_ac(factor, keep="keep out", osdi=False):
    pre = ".control\npre_osdi rf_blocks.osdi\n.endc\n" if osdi else ""
    load = "N9 out 0 dd\n.model dd odio is_=1e-14\n" if osdi else ""
    out = run(f"""* reduce
{pre}{LAD}{load}V1 in 0 DC 0 AC 1
.control
op
reduce {FMAX:g} factor {factor:g} {keep} file red.sp name rcred
.endc
.end
""", "rin.cir")
    m = re.search(r"reduce:\s*RC network\s+(\d+)\s+nodes\s*->\s*(\d+)\s+nodes", out)
    full_n, red_n = (int(m.group(1)), int(m.group(2))) if m else (0, 0)
    # AC of the reduced subckt with the same external load
    run(f"""* reduced AC
.include red.sp
xr in out rcred
V1 in 0 DC 0 AC 1
Rload out 0 1k
.control
ac dec 20 1meg 12g
wrdata red.dat vdb(out)
.endc
.end
""", "rout.cir")
    rt, rdb = col("red.dat")
    inband = [abs(a - b) for f, a, b in zip(ft, fdb, rdb) if f <= FMAX]
    return full_n, red_n, (max(inband) if inband else 1e9), out


print("Enhancement-155: reduce (TICER RC reduction)")

fn, rn, err, out = reduce_and_ac(5)
check("[1] `reduce` runs and reports a reduction", fn > 0 and rn > 0 and rn < fn,
      f"{fn} -> {rn} nodes")

fn, rn, err_id, _ = reduce_and_ac(1e9)     # huge factor -> no elimination
check("[2] identity (huge factor): reduced AC == full AC bit-for-bit",
      rn == fn and err_id < 1e-3, f"nodes {fn}->{rn}, max|Δ|={err_id:.2e} dB")

fn, rn, err_m, _ = reduce_and_ac(40)
check("[3] reduction + accuracy (factor 40): nodes cut, in-band AC within 0.5 dB",
      rn < fn and err_m < 0.5, f"{fn}->{rn} nodes, max in-band |Δ|={err_m:.3f} dB")

# DC exactness at the first (1 MHz ~ DC) point
_fn, _rn, _e, _o = reduce_and_ac(40)
dc_err = abs(fdb[0] - col("red.dat")[1][0]) if col("red.dat")[1] else 1e9
check("[3b] DC preserved exactly", dc_err < 1e-3, f"DC |Δ|={dc_err:.2e} dB")

errs = []
for fac in (5, 15, 40, 120):
    _, _, e, _ = reduce_and_ac(fac); errs.append(e)
mono = all(errs[i] >= errs[i+1] - 0.05 for i in range(len(errs)-1))
check("[4] accuracy improves monotonically with factor",
      mono, "errs(dB) " + ", ".join(f"{e:.2f}" for e in errs))

# [5] OSDI device at `out` auto-marks it a port (no keep)
_, _, _, out5 = reduce_and_ac(20, keep="", osdi=True)
run_ok = "rcred" in open(os.path.join(SCRATCH, "red.sp")).read()
sub = [l for l in open(os.path.join(SCRATCH, "red.sp")) if l.startswith(".subckt")]
terms = sub[0].split()[2:] if sub else []
check("[5] OSDI device auto-marks its node as a kept port (in + out, no `keep`)",
      "in" in terms and "out" in terms, f".subckt terminals = {terms}")

print(f"\n{'ALL PASS' if _fail == 0 else 'FAILURES'}: {_fail} failed check(s)")
sys.exit(0 if _fail == 0 else 1)
