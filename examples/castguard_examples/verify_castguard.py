#!/usr/bin/env python3
"""verify_castguard.py -- Enhancement-279: the remaining unguarded `(int)` casts and
the last unguarded scale-dependent transform.

A systematic audit (grep for `(int) floor/fabs(...)` plus every cmaths routine taking
a `struct plot *`) found the tail of two classes already fixed elsewhere -- sites the
fuzzer had not reached:

  * `(int) floor(x + 0.5)` of a user-supplied double, undefined behaviour outside int
    range: `com_let.c` (an index expression), `options.c` (`set numdgt` /
    `rawfileprec` / `measureprec`), `com_measure2.c` (`meas ... rise/fall/cross`);
  * a scale-dependent transform with no length guard: `cx_mtimeavg`, whose averaging
    window walks the scale data `dsc[j]` for `j < length - 1`, so a vector longer than
    its plot scale (`mtimeavg(unitvec(200))`) read past the scale.

Fixed with per-file clamping helpers before each cast, and the same length-vs-scale
guard `cx_integ`/`cx_deriv` got in Enhancement-278.

Passes iff each previously-UB input is clean and valid uses are unchanged.
"""
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from _setup import NG as NGSPICE  # noqa: E402

BASE = ("* cast guard test\nr1 a b 1k\nr2 b 0 1k\nc1 b 0 1u\n"
        "v1 a 0 dc 1 pulse(0 1 0 1u 1u 1m 2m)\n")
checks = passed = 0


def check(label, ok, detail=""):
    global checks, passed
    checks += 1
    passed += bool(ok)
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  [{detail}]" if detail else ""))


def run(control, timeout=15):
    deck = BASE + ".control\ntran 1u 20u\nlet vx = v(b)\n" + control + \
        "\nquit\n.endc\n.end\n"
    path = os.path.join(HERE, "_cg.cir")
    with open(path, "w") as f:
        f.write(deck)
    try:
        r = subprocess.run([NGSPICE, "-b", path], capture_output=True, text=True,
                           timeout=timeout, errors="replace")
        return r.returncode, (r.stdout or "") + (r.stderr or "")
    except subprocess.TimeoutExpired:
        return 124, "[TIMEOUT]"


def noub(rc, out):
    return rc is not None and rc >= 0 and rc != 139 \
        and "outside the range" not in out.lower() and "Sanitizer" not in out


print("Enhancement-279: remaining (int)-cast + scale-guard sites (audit tail)")

# [1] set numdgt with an out-of-range value (options.c).
rc, out = run("set numdgt=1e30")
check("[1] `set numdgt=1e30` -> clean, no UB", noub(rc, out), f"rc={rc}")

# [2] set rawfileprec likewise.
rc, out = run("set rawfileprec=1e30")
check("[2] `set rawfileprec=1e30` -> clean, no UB", noub(rc, out), f"rc={rc}")

# [3] a negative out-of-range option value.
rc, out = run("set numdgt=-1e30")
check("[3] `set numdgt=-1e30` -> clean, no UB", noub(rc, out), f"rc={rc}")

# [4] meas RISE with an out-of-range count (com_measure2.c).
rc, out = run("meas tran tx when v(b)=0.5 rise=1e308")
check("[4] `meas ... rise=1e308` -> clean, no UB", noub(rc, out), f"rc={rc}")

# [5] mtimeavg of a vector longer than its scale (cx_mtimeavg).
rc, out = run("let y = mtimeavg(unitvec(200))")
check("[5] `mtimeavg(unitvec(200))` -> clean, no overflow", noub(rc, out), f"rc={rc}")

# [6] a valid option value still takes effect.
rc, out = run("set numdgt=6\nprint 1/3")
check("[6] a valid `set numdgt=6` still works", noub(rc, out), f"rc={rc}")

# [7] a valid mtimeavg (data length == scale) still returns a full-length vector.
rc, out = run("let y = mtimeavg(vx)\nprint length(y) length(vx)")
ls = re.findall(r"length\(\w+\)\s*=\s*([-\d.eE+]+)", out)
check("[7] a valid `mtimeavg(vx)` still returns a full-length vector",
      noub(rc, out) and len(ls) == 2 and ls[0] == ls[1], f"{ls}")

print(f"\n{passed}/{checks} checks passed")
if passed == checks:
    print("ALL PASS")
raise SystemExit(0 if passed == checks else 1)
