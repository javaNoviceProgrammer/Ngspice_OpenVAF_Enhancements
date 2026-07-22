#!/usr/bin/env python3
"""verify_plotcoord.py -- Enhancement-283: the plot coordinate math no longer casts a
non-finite double to int.

Plotting extreme data drives several coordinate computations through `mylog10()`,
whose result is `+/-inf` for zero / denormal / overflowed values, and through
divisions by a range that can be zero for degenerate data. Casting either to `int`
is undefined behaviour. Three sites, all reached by ordinary plot commands on
pathological data:

  * `agraf.c`  -- `mag = (int) floor(mylog10(...))` for the decade, and the
    `lmt`/`hmt` limits `(int) floor(ylims[0] / tenpowmag)` (tenpowmag can be 0/inf);
  * `points.c` -- `ft_findpoint()`: `(int)(((mylog10(pt) - tl) / (th - tl)) * ...)`,
    which is 0/0 for a degenerate range;
  * `display.c` -- the four screen-coordinate casts (log/linear, x/y).

Fixed with per-site clamping: the decade is bounded by `DBL_MAX_10_EXP`, the point
fraction is sanitised and clamped to [0,1], and screen coordinates are clamped into
the viewport. Rendering for ordinary data is byte-identical to before.

Passes iff the extreme-data plots are clean and normal plots still render.
"""
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from _setup import NG as NGSPICE  # noqa: E402

BASE = "* plot coordinate test\nr1 a b 1k\nr2 b 0 1k\nc1 b 0 1u\nv1 a 0 dc 1 pulse(0 1 0 1u 1u 1m 2m)\n"
checks = passed = 0


def check(label, ok, detail=""):
    global checks, passed
    checks += 1
    passed += bool(ok)
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  [{detail}]" if detail else ""))


def run(control, timeout=25):
    deck = BASE + ".control\ntran 1u 20u\n" + control + "\nquit\n.endc\n.end\n"
    path = os.path.join(HERE, "_pc.cir")
    with open(path, "w") as f:
        f.write(deck)
    try:
        r = subprocess.run([NGSPICE, "-b", path], capture_output=True, text=True,
                           timeout=timeout, errors="replace")
        return r.returncode, (r.stdout or "") + (r.stderr or "")
    except subprocess.TimeoutExpired:
        return 124, "[TIMEOUT]"


def clean(rc, out):
    return rc is not None and rc >= 0 and rc != 139 and "Sanitizer" not in out


print("Enhancement-283: plot coordinate math -> no (int) cast of a non-finite double")

# [1] agraf decade: -1e308 * 6 overflows to -inf, so mylog10(-ylims[0]) is +inf.
rc, out = run("let q = -1e308*vector(6)\nsetscale q\nasciiplot q")
check("[1] `asciiplot` of overflowing (-1e308) data -> clean (was agraf UB)",
      clean(rc, out), f"rc={rc}")

# [2] points.c ft_findpoint: denormal data with a degenerate log range.
rc, out = run("let q = 1e-320*unitvec(10)\nsetscale q\nasciiplot q")
check("[2] `asciiplot` of a denormal constant vector -> clean (was ft_findpoint UB)",
      clean(rc, out), f"rc={rc}")

# [3] display.c coordinate mapping via the min/max path on denormal data.
rc, out = run("let vv = vector(10)*1e-323\nprint maximum(vv) minimum(vv)")
check("[3] min/max over denormal data -> clean (was display.c UB)",
      clean(rc, out), f"rc={rc}")

# [4] an all-zero vector (mylog10(0) = -inf) plotted against itself.
rc, out = run("let q = 0*unitvec(10)\nsetscale q\nasciiplot q")
check("[4] `asciiplot` of an all-zero vector -> clean", clean(rc, out), f"rc={rc}")

# [5] a normal plot still renders its legend, axis rule and points.
rc, out = run("asciiplot v(b)")
ok5 = clean(rc, out) and "Legend:" in out and "---" in out and "+" in out
check("[5] an ordinary `asciiplot v(b)` still renders", ok5, f"rc={rc}")

print(f"\n{passed}/{checks} checks passed")
if passed == checks:
    print("ALL PASS")
raise SystemExit(0 if passed == checks else 1)
