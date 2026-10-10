#!/usr/bin/env python3
"""verify_meascmd.py -- Enhancement-851: the `meas` command keeps every digit.

F7 of the second robustness campaign of 2026-10-10.

The `meas` command stored its result with `let name = %e`, 7 significant
digits, where the same `.meas` card's result had 16 (Enhancement-802). A vector
named after `val=`, `at=` and the like was put back into the line the same way.
Two crossings 1.8 fs apart read the same time and their difference was 0, and
`find ... at=t2` was read at a rounded t2. Both now carry 17 digits, which
round-trip.

  [1] the command's FIND equals the same .meas card's, bit for bit
  [2] two crossings 1.8 fs apart: their difference is the cards' difference
  [3] `find v(1) at=t2`, with t2 a vector, reads v(1) at t2: 0.50000001
  [4] (control) the card's result is the linear interpolation of the samples, to
      1e-15

Exit code 0 = pass.
"""
import os
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from _setup import NG as NGSPICE  # noqa: E402
from _setup import check_both_solvers as _check_both_solvers; _check_both_solvers(__file__)  # noqa: E402

WORK = tempfile.mkdtemp(prefix="meascmd_")
checks = passed = 0


def check(label, ok, detail=""):
    global checks, passed
    checks += 1
    passed += bool(ok)
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  [{detail}]" if detail else ""))


AT = 0.123456789e-6
TXT = os.path.join(WORK, "w.txt")
DECK = """* meas command
v1 1 0 sin(0 1 1meg)
r1 1 0 1k
.meas tran card find v(1) at=0.123456789u
.meas tran c1 when v(1)=0.5 rise=1
.meas tran c2 when v(1)=0.50000001 rise=1
.tran 1n 1u
.control
set numdgt=17
set wr_singlescale
run
wrdata %s v(1)
meas tran cmd find v(1) at=0.123456789u
meas tran t1 when v(1)=0.5 rise=1
meas tran t2 when v(1)=0.50000001 rise=1
let dt = t2 - t1
let dc = c2 - c1
meas tran v2 find v(1) at=t2
print card cmd t1 t2 dt dc v2
.endc
.end
""" % TXT

path = os.path.join(WORK, "d.cir")
with open(path, "w") as f:
    f.write(DECK)
p = subprocess.run([NGSPICE, "-b", path], cwd=WORK, capture_output=True, text=True, timeout=300,
                   errors="replace")
out = p.stdout + p.stderr
got = {}
for name in ("card", "cmd", "t1", "t2", "dt", "dc", "v2"):
    m = re.search(r"^%s = (\S+)" % name, out, re.M)
    got[name] = float(m.group(1)) if m else float("nan")

check("[1] the command's FIND equals the same .meas card's, bit for bit (8th digit on E-844)",
      got["card"] == got["cmd"], f"card {got['card']!r}, cmd {got['cmd']!r}")
check("[2] two crossings 1.8 fs apart: the commands' difference is the cards' (0 on E-844)",
      got["dt"] > 0 and got["dt"] == got["dc"], f"dt {got['dt']!r}, cards {got['dc']!r}")
check("[3] `find v(1) at=t2`, t2 a vector: v(1) at t2 is 0.50000001 (0.5 on E-844)",
      abs(got["v2"] - 0.50000001) < 1e-12, f"got {got['v2']!r}")

# [4] the card against the samples
rows = []
if os.path.exists(TXT):
    for line in open(TXT):
        v = line.split()
        if len(v) >= 2:
            rows.append((float(v[0]), float(v[1])))
ref = float("nan")
for (ta, va), (tb, vb) in zip(rows, rows[1:]):
    if ta <= AT <= tb:
        ref = va + (vb - va) * (AT - ta) / (tb - ta)
        break
check("[4] (control) the card's result is the linear interpolation of the samples, to 1e-15",
      abs(got["card"] - ref) <= 1e-15 * abs(ref), f"card {got['card']!r}, samples {ref!r}")

print(f"\n{passed}/{checks} checks passed")
sys.exit(0 if passed == checks else 1)
