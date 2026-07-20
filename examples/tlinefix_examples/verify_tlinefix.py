#!/usr/bin/env python3
"""Enhancement-249: input validation for the URC and LTRA transmission-line devices.

Two core transmission-line models accepted degenerate / out-of-range parameters
that led to a silently wrong result or a resource-exhaustion hang rather than a
clean error.

  [URC]  (spicelib/devices/urc/urcsetup.c) The URC uniform-RC line expands into a
         ladder of `n` (lumps) resistor+capacitor(/diode) sections at setup, and
         uses `n` as an exponent of pow(k, n). The user-supplied lump count `n`
         was never validated: n <= 0 built no lumps at all (a silently
         unconnected output, v(out)=0), and a large n (a typo like
         n=100000000) exhausted memory / hung while instantiating the ladder
         (already ~20000 lumps takes tens of seconds). E-249 requires
         1 <= n <= URC_MAX_LUMPS (1000; the auto-computed count is ~3..30), a
         clean error otherwise.

  [LTRA] (spicelib/devices/ltra/ltraset.c) The lossy line selects its RLGC
         "special case" with `!= 0` tests, so a NEGATIVE L or C passed the
         checks and reached sqrt(L/C) / sqrt(L*C) in LTRAtemp -> NaN
         characteristic impedance / delay and a degenerate (all-zero) run.
         E-249 rejects any negative R/L/G/C up front. (A zero/too-few-parameter
         line was already a clean error -- "at least two ... must be ...
         nonzero".)

Checks (batch mode, -b; run under both solvers). A crash/hang shows up as a
negative/timeout return code.
 1. a valid 5-lump URC line still simulates (v(out) ~ 0.5 divider);
 2. URC n=0 and n=-3 are rejected with a clean "out of range" error;
 3. URC n=100000000 is rejected instantly (was an out-of-memory hang);
 4. URC n=1000 (the maximum) still simulates;
 5. a valid LTRA lossless line still simulates;
 6. LTRA with negative C is rejected with a clean "non-negative" error;
 7. LTRA with C=0 is still the pre-existing clean "nonzero" error.

Line 1 of every SPICE deck is the title (ignored).
"""
import os
import re
import subprocess
import sys
import time

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


def run(deck, timeout=15):
    cir = os.path.join(HERE, "_tl.cir")
    open(cir, "w").write(deck)
    t0 = time.time()
    try:
        r = subprocess.run([NGSPICE, "-b", cir], capture_output=True, text=True,
                           timeout=timeout, cwd=HERE)
        return r.returncode, r.stdout.replace("\r", "\n") + r.stderr, time.time() - t0
    except subprocess.TimeoutExpired:
        return None, "TIMEOUT", time.time() - t0


def urc(n):
    return (f"urc n={n}\nV1 in 0 dc 1 ac 1\nU1 in out 0 m l=1 n={n}\n"
            f".model m urc(k=1.5 rperl=1000 cperl=1e-12)\nR1 out 0 1k\n"
            f".op\n.control\nop\nprint v(out)\n.endc\n.end\n")


def ltra(extra):
    return (f"ltra\nV1 in 0 dc 1 pulse(0 1 1n 0.1n 0.1n 5n 10n)\n"
            f"O1 in 0 out 0 m\n.model m ltra {extra} len=1\nR1 out 0 50\n"
            f".tran 0.1n 10n\n.print tran v(out)\n.end\n")


def crash(rc):
    return rc is None or rc < 0 or rc >= 128

# 1: valid URC (resistive divider: URC series R with 1k load -> v(out)~0.5)
rc, out, _ = run(urc(5))
m = re.search(r"v\(out\)\s*=\s*([-\d.eE+]+)", out)
v = float(m.group(1)) if m else None
check("valid 5-lump URC line still simulates",
      not crash(rc) and v is not None and abs(v - 0.5) < 0.05, f"rc={rc} v={v}")

# 2: degenerate n
for n in (0, -3):
    rc, out, _ = run(urc(n))
    check(f"URC n={n} rejected cleanly (was silent wrong result)",
          not crash(rc) and "out of range" in out, f"rc={rc}")

# 3: huge n rejected instantly (was OOM hang)
rc, out, dt = run(urc(100000000), timeout=15)
check("URC n=100000000 rejected instantly, no hang (was OOM)",
      not crash(rc) and "out of range" in out and dt < 5, f"rc={rc} t={dt:.1f}s")

# 4: maximum n=1000 still works
rc, out, _ = run(urc(1000))
check("URC n=1000 (maximum) still simulates",
      not crash(rc) and "v(out)" in out and "out of range" not in out, f"rc={rc}")

# 5: valid LTRA
rc, out, _ = run(ltra("r=0 l=1n c=1p"))
check("valid LTRA lossless line still simulates",
      not crash(rc) and "Index" in out, f"rc={rc}")

# 6: negative C -> clean error
rc, out, _ = run(ltra("r=0 l=1n c=-1p"))
check("LTRA negative C rejected cleanly (was NaN-degenerate)",
      not crash(rc) and "non-negative" in out, f"rc={rc}")

# 7: C=0 -> pre-existing clean error
rc, out, _ = run(ltra("r=0 l=1n c=0"))
check("LTRA C=0 still the pre-existing clean 'nonzero' error",
      not crash(rc) and "nonzero" in out, f"rc={rc}")

p = os.path.join(HERE, "_tl.cir")
if os.path.exists(p):
    os.remove(p)

print(f"\n{passed} passed, {failed} failed")
raise SystemExit(1 if failed else 0)
