#!/usr/bin/env python3
"""Enhancement-246: out-of-bounds read in the XSPICE `pwl` and `pwlts` code models.

Both models (xspice/icm/analog/pwl and .../pwlts) take two independent vector
parameters, `x_array` (breakpoint abscissae) and `y_array` (ordinates). The
XSPICE parameter framework allocates each vector to its OWN length. At setup the
models size their working buffer from the x_array only:

    size = PARAM_SIZE(x_array) + 2;
    for (i = 1; i < size - 1; i++) {
        x[i] = PARAM(x_array[i - 1]);
        y[i] = PARAM(y_array[i - 1]);   /* indexed by the x_array length */
    }

so if `y_array` is SHORTER than `x_array`, `PARAM(y_array[i-1])` reads off the end
of the y_array parameter -- a heap out-of-bounds read (confirmed with
AddressSanitizer: `heap-buffer-overflow READ of size 8 ... in cm_pwl cfunc.c:321`
and `... in cm_pwlts cfunc.c:202`). The read returns adjacent/uninitialised heap
into the interpolation table (undefined behaviour; it can also crash outright when
the mismatch is large enough to run past the mapped heap).

The sibling models `oneshot` (cntl_array vs pw_array) and `multi_input_pwl`
(x vs y) already guard this with an equal-length check; `pwl`/`pwlts` predate it.
E-246 adds the same guard: if `PARAM_SIZE(x_array) != PARAM_SIZE(y_array)` the
model reports a clean error and returns instead of reading out of bounds.

The XSPICE code models load from the prebuilt bundle via SPICE_LIB_DIR, which
`_setup` points at bin/<os>/<arch>/. If the bundle/codemodels are unavailable in
this checkout, the a-devices cannot load and this test self-skips.

Checks (batch mode, -b; run under both solvers):
 1. valid `pwl` interpolates exactly: x=[-1 0 1 2] y=[-1 0 2 3], in=0.5 -> 1.0 V;
 2. mismatched `pwl` (x longer than y) reports the size error and does not crash;
 3. mismatched `pwl` the other way (y longer than x) is also rejected cleanly;
 4. valid `pwlts` time-series source still runs;
 5. mismatched `pwlts` reports the size error and does not crash.

Line 1 of every SPICE deck is the title (ignored).
"""
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from _setup import NG as NGSPICE  # noqa: E402  (also sets SPICE_LIB_DIR)
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


def run(deck):
    cir = os.path.join(HERE, "_pwl.cir")
    open(cir, "w").write(deck)
    r = subprocess.run([NGSPICE, "-b", cir], capture_output=True, text=True,
                       timeout=60)
    return r.returncode, r.stdout.replace("\r", "\n") + r.stderr


def num(out, name):
    m = re.search(name + r"\s*=\s*([-\d.eE+]+)", out)
    return float(m.group(1)) if m else None


SIZE_MSG = "must have the same length"


def pwl_deck(x, y):
    return (f"* pwl test\nV1 in 0 dc 0.5\nA1 in out mod\n"
            f".model mod pwl(x_array=[{x}] y_array=[{y}])\nR1 out 0 1k\n"
            f".op\n.control\nop\nprint v(out)\n.endc\n.end\n")


def pwlts_deck(x, y):
    return (f"* pwlts test\nA1 out mod\n"
            f".model mod pwlts(x_array=[{x}] y_array=[{y}])\nR1 out 0 1k\n"
            f".tran 1u 5u\n.control\ntran 1u 5u\n.endc\n.end\n")


# Availability gate: a valid pwl must load & interpolate (proves codemodels present)
rc, out = run(pwl_deck("-1 0 1 2", "-1 0 2 3"))
v = num(out, r"v\(out\)")
if rc < 0 or v is None:
    print(f"  SKIP  XSPICE code models unavailable in this checkout (rc={rc}) "
          "-- cannot exercise pwl/pwlts")
    raise SystemExit(0)

# 1: valid pwl exact interpolation at x=0.5 between (0,0) and (1,2) -> 1.0 V
check("valid pwl interpolates exactly (in=0.5 -> 1.0 V)",
      rc >= 0 and abs(v - 1.0) < 1e-9, f"rc={rc} v(out)={v}")

# 2: x longer than y -- the OOB case -- now a clean size error, no crash/OOB
rc, out = run(pwl_deck("0 0.25 0.5 0.75 1 1.5 2 2.5", "0 1"))
check("pwl x_array longer than y_array: clean size error, no crash (was OOB read)",
      rc >= 0 and SIZE_MSG in out, f"rc={rc} msg={'yes' if SIZE_MSG in out else 'no'}")

# 3: y longer than x -- also rejected by the equal-length guard, no crash
rc, out = run(pwl_deck("0 1", "0 0.25 0.5 0.75 1 1.5 2 2.5"))
check("pwl y_array longer than x_array: clean size error, no crash",
      rc >= 0 and SIZE_MSG in out, f"rc={rc} msg={'yes' if SIZE_MSG in out else 'no'}")

# 4: valid pwlts time-series source still runs (no error, no crash)
rc, out = run(pwlts_deck("0 0.1 0.2 0.8 0.9 1 1.1", "0.1 0.1 1 1 0 0 0.2"))
check("valid pwlts time-series source still runs",
      rc >= 0 and SIZE_MSG not in out, f"rc={rc}")

# 5: mismatched pwlts -- clean size error, no crash (was OOB read)
rc, out = run(pwlts_deck("0 0.1 0.2 0.3 0.4 0.5 0.6 0.7", "0 1"))
check("pwlts x_array longer than y_array: clean size error, no crash (was OOB read)",
      rc >= 0 and SIZE_MSG in out, f"rc={rc} msg={'yes' if SIZE_MSG in out else 'no'}")

p = os.path.join(HERE, "_pwl.cir")
if os.path.exists(p):
    os.remove(p)

print(f"\n{passed} passed, {failed} failed")
raise SystemExit(1 if failed else 0)
