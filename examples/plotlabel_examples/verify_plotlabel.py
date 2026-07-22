#!/usr/bin/env python3
"""verify_plotlabel.py -- Enhancement-282: `asciiplot` no longer reads past its axis
label buffer when a label carries a 3-digit exponent.

`ft_agraf` (src/frontend/plotting/agraf.c) sizes its two axis-label lines as
`maxy + margin + FUDGE + 1` (FUDGE = 7) and NUL-terminates them at the last byte. It
budgets for the exponent width like this:

    sprintf(buf, "%1.1e", 0.0);      /* expect 0.0e+00 */
    shift = (int) strlen(buf) - 7;

Formatting **0.0** always yields a 2-digit exponent, so `shift` is 0 and the budget
silently assumes 2 digits. Real data can need three: plotting denormal or very large
values gives labels like `1.00e-320` (9 chars vs 8). The last label's `memcpy` then
runs one byte too far and overwrites the line's terminating `'\\0'`, after which
`out_printf("%s\\n%s\\n", line2, line1)` reads past the end of the heap buffer --
AddressSanitizer reports a `heap-buffer-overflow READ` inside vsnprintf.

Fixed by remembering the allocation bound (`maxy` is reassigned later, so it cannot be
recomputed at the label loop), clamping the label copy to that bound, and re-asserting
the terminator after the loop.

Passes iff plotting extreme-exponent data is clean and ordinary plots are unchanged.
"""
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from _setup import NG as NGSPICE  # noqa: E402

BASE = "* asciiplot label test\nr1 a 0 1k\nv1 a 0 dc 1\n"
checks = passed = 0


def check(label, ok, detail=""):
    global checks, passed
    checks += 1
    passed += bool(ok)
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  [{detail}]" if detail else ""))


def run(control, timeout=20):
    deck = BASE + ".control\n" + control + "\nquit\n.endc\n.end\n"
    path = os.path.join(HERE, "_pl.cir")
    with open(path, "w") as f:
        f.write(deck)
    try:
        r = subprocess.run([NGSPICE, "-b", path], capture_output=True, text=True,
                           timeout=timeout, errors="replace")
        return r.returncode, (r.stdout or "") + (r.stderr or "")
    except subprocess.TimeoutExpired:
        return 124, "[TIMEOUT]"


def ok_run(rc, out):
    return rc is not None and rc >= 0 and rc != 139 and "Sanitizer" not in out


print("Enhancement-282: asciiplot 3-digit-exponent labels -> no buffer over-read")

# [1] denormal data: labels like 1.00e-320 (the fuzz-found case).
rc, out = run("let y = 1e-320*unitvec(10)\nasciiplot y")
check("[1] `asciiplot` of denormal data (1e-320) -> clean, no over-read",
      ok_run(rc, out), f"rc={rc}")

# [2] a large 3-digit positive exponent.
rc, out = run("let y = 1e300*vector(10)\nasciiplot y")
check("[2] `asciiplot` of 1e300 data -> clean", ok_run(rc, out), f"rc={rc}")

# [3] a small 3-digit negative exponent.
rc, out = run("let y = 1e-300*vector(10)\nasciiplot y")
check("[3] `asciiplot` of 1e-300 data -> clean", ok_run(rc, out), f"rc={rc}")

# [4] two vectors spanning both extremes at once.
rc, out = run("let y = 1e-320*vector(10)\nlet z = 1e300*vector(10)\nasciiplot y z")
check("[4] `asciiplot` of both extremes together -> clean", ok_run(rc, out),
      f"rc={rc}")

# [5] an ordinary plot still renders: axis rule, legend and a plotted point.
rc, out = run("let y = vector(8)\nasciiplot y")
ok5 = ok_run(rc, out) and "Legend:" in out and "+" in out and "---" in out
check("[5] an ordinary `asciiplot` still renders (legend, axis, points)", ok5,
      f"rc={rc}")

print(f"\n{passed}/{checks} checks passed")
if passed == checks:
    print("ALL PASS")
raise SystemExit(0 if passed == checks else 1)
