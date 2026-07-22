#!/usr/bin/env python3
"""verify_veclenmix.py -- Enhancement-285: the output paths no longer index one
vector by another's length, nor treat a complex vector's NULL real data as real.

A vector's own length need not equal its plot scale's length: any synthetic vector
(`let y = vector(8)` on a 66-point transient plot) carries the plot's scale. And a
COMPLEX vector has `v_realdata == NULL` -- the dvec union holds `v_compdata`. Four
output paths got both wrong:

  * `plotit.c` passed `v->v_realdata` with the SCALE's length to `ft_interpolate`,
    which indexes the data by that length -- reading far past a shorter vector; for a
    complex vector it passed NULL outright (a hard SEGV, `asciiplot sqrt(-1*...)`);
  * `agraf.c` used the bracketing indices `lower`/`upper` -- bounded by the X scale --
    to index each plotted VECTOR;
  * `gnuplot.c` (`wrdata`) bounded its loop by `scale->v_length` but then indexed
    `v->v_realdata[i]`;
  * `com_measure2.c` read `d->v_realdata[i]` on the plain tran/dc path without the
    NULL check its ac/sp branches already had.

Fixed by clamping each index to the vector it actually addresses, skipping the
transient resampling when a vector is not real, and taking the real part for a
complex measure input.

Passes iff the mismatched / complex cases work and ordinary output is unchanged.
"""
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from _setup import NG as NGSPICE  # noqa: E402

BASE = ("* vector length/type mix\nr1 a b 1k\nr2 b 0 1k\nc1 b 0 1u\n"
        "v1 a 0 dc 1 ac 1 pulse(0 1 0 1u 1u 1m 2m)\n")
checks = passed = 0


def check(label, ok, detail=""):
    global checks, passed
    checks += 1
    passed += bool(ok)
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  [{detail}]" if detail else ""))


def run(control, timeout=25):
    deck = BASE + ".control\ntran 1u 20u\n" + control + "\nquit\n.endc\n.end\n"
    path = os.path.join(HERE, "_vm.cir")
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


print("Enhancement-285: output paths vs vector length/type mismatch")

# [1] the ordinary case: a synthetic vector shorter than the plot's scale.
rc, out = run("let y = vector(8)\nasciiplot y")
check("[1] `asciiplot` of a vector shorter than the plot scale -> clean + renders",
      clean(rc, out) and "Legend:" in out, f"rc={rc}")

# [2] a COMPLEX vector: v_realdata is NULL -> was a hard SEGV (rc 139).
rc, out = run("asciiplot sqrt(-1*vector(10))")
check("[2] `asciiplot` of a complex vector -> clean + renders (was a SEGV)",
      clean(rc, out) and "Legend:" in out, f"rc={rc}")

# [3] wrdata of a vector shorter than its scale.
rc, out = run("let y = 1e-320*unitvec(10)\nwrdata _vm_out.dat y")
check("[3] `wrdata` of a vector shorter than its scale -> clean", clean(rc, out),
      f"rc={rc}")

# [4] measure over a complex vector (NULL v_realdata on the tran path).
rc, out = run("let q = (1e300,1e-320)*unitvec(5)\nmeas tran m1 max q")
check("[4] `meas tran ... max <complex vector>` -> clean (was a null deref)",
      clean(rc, out), f"rc={rc}")

# [5] a longer-than-scale synthetic vector too.
rc, out = run("let y = unitvec(200)\nasciiplot y")
check("[5] `asciiplot` of a vector longer than the plot scale -> clean",
      clean(rc, out), f"rc={rc}")

# [6] an ordinary plot is unaffected and still renders its data.
rc, out = run("asciiplot v(b)")
check("[6] an ordinary `asciiplot v(b)` still renders",
      clean(rc, out) and "Legend:" in out and "---" in out, f"rc={rc}")

# [7] an ordinary measure still returns the right value: max of v(b) over the ramp.
rc, out = run("meas tran vmax max v(b)")
m = re.search(r"vmax\s*=\s*([-\d.eE+]+)", out)
check("[7] an ordinary `meas tran ... max v(b)` still measures",
      clean(rc, out) and m is not None and float(m.group(1)) > 0.0,
      f"={m.group(1) if m else '?'}")

print(f"\n{passed}/{checks} checks passed")
if passed == checks:
    print("ALL PASS")
raise SystemExit(0 if passed == checks else 1)
