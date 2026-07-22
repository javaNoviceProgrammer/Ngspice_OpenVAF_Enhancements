#!/usr/bin/env python3
"""verify_rndcast.py -- Enhancement-276: rnd() guards its (int) cast against an
out-of-range operand.

`cx_rnd` (src/maths/cmaths/cmath2.c) turned each operand into a modulus with
`j = (int) floor(x); rand() % j`. Casting a `double` outside int range to `int` is
undefined behaviour, so `rnd(1e30)` (or an inf/NaN operand) tripped UBSan. This is
the same class as Enhancement-273, which had hardened cx_mod / cx_vector but not
cx_rnd. Fixed with `cx_rnd_i()`, which clamps the value to int range (NaN -> 0)
before the cast.

Passes iff the out-of-range operand is clean (no UB) and a valid rnd() still yields
a value in range. Reported via exit code (0 = pass).
"""
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from _setup import NG as NGSPICE  # noqa: E402

BASE = "* rnd cast test\nv1 n 0 dc 0\nr1 n 0 1\n"
checks = passed = 0


def check(label, ok, detail=""):
    global checks, passed
    checks += 1
    passed += bool(ok)
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  [{detail}]" if detail else ""))


def run(control, timeout=15):
    deck = BASE + ".control\ntran 1 10 0\n" + control + "\nquit\n.endc\n.end\n"
    path = os.path.join(HERE, "_rc.cir")
    with open(path, "w") as f:
        f.write(deck)
    try:
        r = subprocess.run([NGSPICE, "-b", path], capture_output=True, text=True,
                           timeout=timeout, errors="replace")
        return r.returncode, (r.stdout or "") + (r.stderr or "")
    except subprocess.TimeoutExpired:
        return 124, "[TIMEOUT]"


def nocrash(rc):
    return rc is not None and rc >= 0 and rc != 139


print("Enhancement-276: rnd() (int)-cast guarded against out-of-range operand")

# [1] rnd(1e30): was (int)floor(1e30) UB.
rc, out = run("let y = rnd(1e30)\nprint y[0]")
check("[1] `rnd(1e30)` -> clean, no UB", nocrash(rc)
      and "outside the range" not in out.lower(), f"rc={rc}")

# [2] rnd of an inf operand.
rc, out = run("let y = rnd(1e300*1e300)\nprint y[0]")
check("[2] `rnd(inf)` -> clean, no UB", nocrash(rc)
      and "outside the range" not in out.lower(), f"rc={rc}")

# [3] a valid rnd(5) yields an integer in [0,5).  rnd of a scalar is a scalar.
rc, out = run("let y = rnd(5)\nprint y")
m = re.search(r"\by\s*=\s*([-\d.eE+]+)", out)
val = float(m.group(1)) if m else None
check("[3] a valid `rnd(5)` is in [0,5)", nocrash(rc) and val is not None
      and 0.0 <= val < 5.0, f"y={m.group(1) if m else '?'}")

print(f"\n{passed}/{checks} checks passed")
if passed == checks:
    print("ALL PASS")
raise SystemExit(0 if passed == checks else 1)
