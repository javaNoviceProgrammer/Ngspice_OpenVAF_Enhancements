#!/usr/bin/env python3
"""verify_mathcast.py -- Enhancement-273: the cmaths integer operators guard their
`(int)` casts against out-of-range doubles.

Several `cmath2.c` routines convert a double operand to `int` with a plain cast,
which is undefined behaviour when the value is non-finite or outside int range:

  * `cx_mod` (the `%` operator) computed `(int) floor(fabs(op))` -- `1e30 % 5`
    tripped UBSan and, on the shipped build, returned a garbage value (2) instead
    of erroring;
  * `cx_vector` / `cx_cvector` / `cx_unitvec` set the vector length with
    `(int) fabs(arg)` -- `vector(1e30)` / `unitvec(1e30)` produced a saturated
    (INT_MAX-ish) length and then ran away allocating and filling it: a hang on
    the shipped build, not just under a sanitizer.

Fixed by range-checking before every cast: `%` rejects an out-of-range operand
with the existing "argument out of range for mod" error, and the vector builders
reject a non-representable length ("vector length ... is out of range"). Valid
expressions are unchanged.

The test passes iff the out-of-range inputs error cleanly (no hang, no UB, no
garbage) and valid expressions still evaluate correctly. Reported via exit code.
"""
import os
import re
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from _setup import NG as NGSPICE  # noqa: E402

BASE = "* cmaths cast test\nr1 a 0 1k\nv1 a 0 1\n"
checks = passed = 0


def check(label, ok, detail=""):
    global checks, passed
    checks += 1
    passed += bool(ok)
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  [{detail}]" if detail else ""))


def run(control, timeout=15):
    deck = BASE + ".control\n" + control + "\nquit\n.endc\n.end\n"
    path = os.path.join(HERE, "_mc.cir")
    with open(path, "w") as f:
        f.write(deck)
    t0 = time.time()
    try:
        r = subprocess.run([NGSPICE, "-b", path], capture_output=True, text=True,
                           timeout=timeout, errors="replace")
        return r.returncode, (r.stdout or "") + (r.stderr or ""), time.time() - t0
    except subprocess.TimeoutExpired:
        return 124, "[TIMEOUT]", time.time() - t0


def nocrash(rc):
    return rc is not None and rc >= 0 and rc != 139


print("Enhancement-273: cmaths (int) casts guard out-of-range doubles (no UB, no hang)")

# [1] `1e30 % 5`: was UB (UBSan) and a garbage result on the shipped build.
rc, out, dt = run("print 1e30 % 5")
check("[1] `1e30 % 5` -> clean 'out of range' error (was UB / garbage result)",
      nocrash(rc) and "out of range for mod" in out.lower() and dt < 10, f"rc={rc} {dt:.1f}s")

# [2] `vector(1e30)`: was a multi-GB alloc/fill runaway (hang) on the shipped build.
rc, out, dt = run("let x = vector(1e30)")
check("[2] `vector(1e30)` -> clean 'length out of range' error, fast (was a hang)",
      nocrash(rc) and "out of range" in out.lower() and dt < 10, f"rc={rc} {dt:.1f}s")

# [3] `unitvec(1e30)`: same runaway.
rc, out, dt = run("let x = unitvec(1e30)")
check("[3] `unitvec(1e30)` -> clean 'length out of range' error, fast (was a hang)",
      nocrash(rc) and "out of range" in out.lower() and dt < 10, f"rc={rc} {dt:.1f}s")

# [4] a valid modulo still evaluates correctly (17 % 5 = 2).
rc, out, dt = run("print 17 % 5")
m = re.search(r"17 % 5\s*=\s*([-\d.eE+]+)", out)
check("[4] a valid `17 % 5` still evaluates to 2", nocrash(rc) and m is not None
      and abs(float(m.group(1)) - 2.0) < 1e-9, f"={m.group(1) if m else '?'}")

# [5] a valid vector(4) still yields [0,1,2,3].
rc, out, dt = run("print vector(4)")
vals = [float(x) for x in re.findall(r"^\s*\d+\s+([-\d.eE+]+)", out, re.M)]
check("[5] a valid `vector(4)` still yields [0,1,2,3]",
      nocrash(rc) and vals[:4] == [0.0, 1.0, 2.0, 3.0], f"{vals[:4]}")

print(f"\n{passed}/{checks} checks passed")
if passed == checks:
    print("ALL PASS")
raise SystemExit(0 if passed == checks else 1)
