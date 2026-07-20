#!/usr/bin/env python3
"""Enhancement-248: out-of-bounds accesses in the CPL coupled-transmission-line device.

The `p` device (coupled multiconductor lossy line, model type `cpl`) describes a
line of `noL` conductors. `noL` (the instance's `dimension`) comes from the node
count on the `p` card; each of the symmetric R/L/C/G matrices is given as its
upper triangle, `noL*(noL+1)/2` values. `CPLsetup` / `ReadCpL`
(spicelib/devices/cpl/cplsetup.c) never validated either count, so a valid-syntax
netlist could drive two out-of-bounds accesses:

  1. Under-specified matrix (heap OOB read). ReadCpL fills the matrices with
         f = CPLmodPtr(here)->Rm[counter];   /* ... Lm/Cm/Gm[counter] */
     where `counter` runs 0 .. noL*(noL+1)/2-1, but the Rm/Lm/Cm/Gm arrays are
     allocated to the number of values the user actually supplied. Fewer values
     than the triangle needs -> read past the end (AddressSanitizer:
     heap-buffer-overflow READ at cplsetup.c:474).

  2. Too many conductors (fixed-array overflow). ReadCpL uses
     `RLINE *lines[MAX_CP_TX_LINES]` and `CPLine.in_node[MAX_CP_TX_LINES]` with
     MAX_CP_TX_LINES == 8, indexed by `noL`. A `p` card with more than 8
     conductors writes past those arrays (UBSan: index 8 out of bounds for
     'NODE *[8]' at cplsetup.c:430).

E-248 validates both up front in CPLsetup, right after `noL = here->dimension`:
reject `noL < 1 || noL > MAX_CP_TX_LINES`, and reject any R/L/C/G matrix with
fewer than noL*(noL+1)/2 entries -- a clean `E_BADPARM` error instead of the OOB.

Checks (batch mode, -b; run under both solvers). A crash shows up as a NEGATIVE
return code (signal).
 1. a valid 2-conductor coupled line still simulates (produces v(v3));
 2. a 2-conductor line whose R/L/C/G give only 1 value each is rejected with a
    clean "needs 3 entries" error and no crash (was the heap OOB read);
 3. a 9-conductor line is rejected with a clean "between 1 and 8" error and no
    crash (was the fixed-array overflow).

Line 1 of every SPICE deck is the title (ignored).
"""
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from _setup import NG as NGSPICE  # noqa: E402
from _setup import check_both_solvers as _check_both_solvers  # noqa: E402
_check_both_solvers(__file__)

passed = failed = 0


def check(label, ok, detail=""):
    global passed, failed
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  {detail}" if detail else ""))
    if ok:
        passed += 1
    else:
        failed += 1


def is_crash(rc):
    return rc < 0 or rc >= 128


def run(deck):
    cir = os.path.join(HERE, "_cpl.cir")
    open(cir, "w").write(deck)
    r = subprocess.run([NGSPICE, "-b", cir], capture_output=True, text=True,
                       timeout=60, cwd=HERE)
    return r.returncode, r.stdout.replace("\r", "\n") + r.stderr


VALID = """cpl valid 2-conductor
VES IN 0 PULSE(0 1 0N 1.5N 1.5N 4.5N 200N)
R1 IN V1 50
R2 V2 0 10
p1 V1 V2 0 V3 V4 0 cpl1
.model cpl1 cpl
+R = 0.5 0 0.5
+L = 247.3e-9 31.65e-9 247.3e-9
+C = 31.4e-12 -2.45e-12 31.4e-12
+G = 0 0 0
+length = 0.3048
R3 V3 0 100
R4 V4 0 100
.tran 0.1N 5N
.print tran v(v3)
.end
"""

SHORT = """cpl short matrices
VES IN 0 PULSE(0 1 0N 1.5N 1.5N 4.5N 200N)
R1 IN V1 50
R2 V2 0 10
p1 V1 V2 0 V3 V4 0 cpl1
.model cpl1 cpl
+R = 0.5
+L = 247.3e-9
+C = 31.4e-12
+G = 0
+length = 0.3048
R3 V3 0 100
R4 V4 0 100
.tran 0.1N 5N
.print tran v(v3)
.end
"""


def wide9():
    n = 9
    ins = " ".join(f"a{i}" for i in range(n))
    outs = " ".join(f"b{i}" for i in range(n))
    tri = n * (n + 1) // 2
    r = " ".join("0.5" for _ in range(tri))
    l = " ".join("2e-7" for _ in range(tri))
    c = " ".join("3e-11" for _ in range(tri))
    g = " ".join("0" for _ in range(tri))
    src = "\n".join(f"V{i} a{i} 0 dc 0 ac 1" for i in range(n))
    loads = "\n".join(f"Rb{i} b{i} 0 100" for i in range(n))
    return (f"cpl 9 conductors\n{src}\np1 {ins} 0 {outs} 0 cpl1\n.model cpl1 cpl\n"
            f"+R = {r}\n+L = {l}\n+C = {c}\n+G = {g}\n+length = 0.3\n{loads}\n"
            f".tran 0.1n 2n\n.print tran v(b0)\n.end\n")


# 1: valid 2-conductor line still simulates
rc, out = run(VALID)
has_data = bool(re.search(r"v\(v3\)", out, re.I)) and "Index" in out
check("valid 2-conductor coupled line still simulates",
      not is_crash(rc) and has_data, f"rc={rc}")

# 2: under-specified matrices -> clean error, no crash (was heap OOB read)
rc, out = run(SHORT)
check("under-specified R/L/C/G: clean 'needs N entries' error, no crash (was OOB read)",
      not is_crash(rc) and "entries" in out and "needs" in out, f"rc={rc}")

# 3: 9 conductors -> clean error, no crash (was fixed-array overflow)
rc, out = run(wide9())
check("9-conductor line: clean 'between 1 and 8' error, no crash (was array overflow)",
      not is_crash(rc) and "between 1 and 8" in out, f"rc={rc}")

p = os.path.join(HERE, "_cpl.cir")
if os.path.exists(p):
    os.remove(p)

print(f"\n{passed} passed, {failed} failed")
raise SystemExit(1 if failed else 0)
