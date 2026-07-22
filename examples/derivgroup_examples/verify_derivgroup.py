#!/usr/bin/env python3
"""verify_derivgroup.py -- Enhancement-281: deriv() no longer reads past its input
when the vector's grouping (v_dims[0]) differs from its length.

`cx_deriv` (src/maths/cmaths/cmath4.c) walks the input in blocks:

    for (base = 0; base < length; base += grouping)
        for (i = degree; i < grouping; i += 1)
            ... read the fit window around  i + base ...

`grouping` is the vector's `v_dims[0]`. For an ordinary vector that equals
`v_length`, so there is a single block and the window always fits. But a vector
whose declared dimension differs from its length -- as produced by a binary op on
operands of unequal length, e.g. `min(v(b), ac.v(b))` (a 66-point real and a 5-point
complex vector yields length 66 with dims[0] = 5) -- leaves a **partial last block**:
`base` climbs to `length - 1` while the window still spans `base + grouping - 1`,
reading past the end of the input (AddressSanitizer heap-buffer-overflow READ).

Fixed by bounding the inner loop with `i + base < length` in both the real and
complex branches -- a no-op whenever `grouping == length`.

Passes iff the mixed-length case is clean and ordinary derivatives are unchanged.
"""
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from _setup import NG as NGSPICE  # noqa: E402

BASE = ("* deriv grouping test\nr1 a b 1k\nr2 b 0 1k\nc1 b 0 1u\n"
        "v1 a 0 dc 1 ac 1 pulse(0 1 0 1u 1u 1m 2m)\n")
checks = passed = 0


def check(label, ok, detail=""):
    global checks, passed
    checks += 1
    passed += bool(ok)
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  [{detail}]" if detail else ""))


def run(control, timeout=15):
    deck = (BASE + ".control\ntran 1u 20u\nac lin 5 1k 10k\nsetplot previous\n"
            + control + "\nquit\n.endc\n.end\n")
    path = os.path.join(HERE, "_dg.cir")
    with open(path, "w") as f:
        f.write(deck)
    try:
        r = subprocess.run([NGSPICE, "-b", path], capture_output=True, text=True,
                           timeout=timeout, errors="replace")
        return r.returncode, (r.stdout or "") + (r.stderr or "")
    except subprocess.TimeoutExpired:
        return 124, "[TIMEOUT]"


def noub(rc, out):
    return rc is not None and rc >= 0 and rc != 139 and "Sanitizer" not in out


print("Enhancement-281: deriv() with grouping != length -> no over-read")

# [1] the fuzz-found case: deriv of a mixed real/complex binary op.
rc, out = run("let m = min(v(b), ac.v(b))\nlet d = deriv(m)")
check("[1] `deriv(min(v(b), ac.v(b)))` -> clean, no over-read", noub(rc, out),
      f"rc={rc}")

# [2] the same shape via a different mixed-length op.
rc, out = run("let m2 = max(v(b), ac.v(b))\nlet d2 = deriv(m2)")
check("[2] `deriv(max(v(b), ac.v(b)))` -> clean", noub(rc, out), f"rc={rc}")

# [3] an ordinary real derivative is numerically unchanged: d/dt(2t) = 2.
rc, out = run("let dr = deriv(2*time)\nprint dr[3]")
m = re.search(r"dr\[3\]\s*=\s*([-\d.eE+]+)", out)
check("[3] an ordinary real `deriv(2t)` still == 2", noub(rc, out) and m is not None
      and abs(float(m.group(1)) - 2.0) < 1e-6, f"={m.group(1) if m else '?'}")

# [4] a complex derivative is still correct (Enhancement-277): d/dt(t + 2t*i) = 1 + 2i.
rc, out = run("let z = time + 2*time*i\nlet dz = deriv(z)\nprint dz[3]")
line = next((ln for ln in out.splitlines() if "dz[3]" in ln), "")
mm = re.search(r"=\s*([-\d.eE+]+)\s*,\s*([-\d.eE+]+)", line)
check("[4] a complex `deriv(t + 2t*i)` is still (1, 2i)",
      noub(rc, out) and mm is not None and abs(float(mm.group(1)) - 1.0) < 1e-6
      and abs(float(mm.group(2)) - 2.0) < 1e-6,
      f"{(mm.group(1), mm.group(2)) if mm else '?'}")

print(f"\n{passed}/{checks} checks passed")
if passed == checks:
    print("ALL PASS")
raise SystemExit(0 if passed == checks else 1)
