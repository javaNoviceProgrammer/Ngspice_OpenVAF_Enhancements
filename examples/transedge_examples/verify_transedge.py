#!/usr/bin/env python3
"""Enhancement-512: transition/slew reached their final value only for slow edges.

User-reported, from reading the compliance document's "documented deviation" and
asking the obvious question: are they actually correct?

They were not. The filters are a rate-limited tracking loop,

    dy/dt = clamp( K*(x - y),  -1/tfall,  +1/trise )

While the clamp is saturated this is an exact linear ramp at the LRM's rate. It
releases once the remaining gap falls below `rate/K`, and the rest of the swing
is a first-order tail with tau = 1/K. K was a FIXED 1e9/s, so the released gap
was `1/(K*trise)` -- it depended entirely on how fast the transition was:

    trise    linear part of the swing    value at delay+trise  (LRM: 1.0)
     3 ns            66.7%                     0.8774
    30 ns            96.7%                     0.9873
   300 ns            99.7%                     0.99948
     3 us           ~100%                      1.000039

The shortfall is e^-1/(K*trise) -- measured 0.877382 against 0.877374 predicted
at 3 ns, which is what identified the mechanism rather than merely the symptom.
So the operator was effectively exact above a microsecond and 12% short at three
nanoseconds, which is where `transition` is most used.

It was not a timestep artifact: refining the step 100x converged to 0.8776, i.e.
to the WRONG value. It converges to 1.0 now.

THE FIX. K = TRACK_C * rate, so the released gap is `1/TRACK_C` at every speed
and the linear fraction is scale-invariant. TRACK_C = 1e3 by measurement: the
gap also bounds the truncation error the integrator shows at the corner where
the ramp meets the tail, and raising it makes Enhancement-47's plateau check
WORSE (0.875 at 1e3, 0.874940 at 1e4, 0.874766 at 1e5), so bigger is not better.

Two things had to be preserved rather than broken:

  * Enhancement-504 clamps a negative rise/fall to ZERO, whose reciprocal is
    +inf -- that is how an instantaneous transition disables the rate limit.
    `TRACK_C * inf` is inf and `inf * 0.0` is NaN, so the gain falls back to the
    old fixed 1e9/s exactly there, which is the behaviour E-504's suite measured.
  * The gain is taken from the FASTER of the two rates, not chosen per direction.
    A per-direction gain was tried and rejected: it makes the loop dynamics jump
    at the crossing point, and `transition(x, td, 0.5n, -0.5n)` then overshot to
    1.01 -- a regression against E-504's suite.

WHY IT SURVIVED: `defaulttransition` pins the 1 us case, deep inside the region
where the old code was already right. The same shape of blind spot as
Enhancement-510, where the suite tested `$ln1p(0.5)` and a literal folds before
code generation. Checks [1]-[5] below span five decades of rise time for exactly
that reason.
"""

import atexit
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from _setup import NG as NGSPICE  # noqa: E402
from _setup import VAF as OPENVAF  # noqa: E402
from _setup import check_both_solvers  # noqa: E402

check_both_solvers(__file__)


def _cleanup():
    for junk in os.listdir(HERE):
        if junk.startswith("_te_"):
            try:
                os.remove(os.path.join(HERE, junk))
            except OSError:
                pass


atexit.register(_cleanup)

checks = passed = 0


def check(label, ok, detail=""):
    global checks, passed
    checks += 1
    passed += bool(ok)
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  [{detail}]" if detail else ""))


OSDI = os.path.join(HERE, "_te_tedge.osdi")
r = subprocess.run([OPENVAF, os.path.join(HERE, "tedge.va"), "-o", OSDI],
                   capture_output=True, text=True, timeout=300, cwd=HERE)
check("tedge.va compiles", os.path.exists(OSDI), (r.stdout + r.stderr).strip()[-160:])


def wave(card, tstop, step, tag, sel=0):
    p = os.path.join(HERE, f"_te_{tag}.cir")
    with open(p, "w") as f:
        f.write(f"transedge\nV1 a 0 PWL(0 0 1p 0 2p 1 {tstop} 1)\nN1 a o mm\n"
                f".model mm tedge sel={sel} {card}\nRo o 0 1e12\n"
                f".control\npre_osdi {os.path.basename(OSDI)}\noption noacct\n"
                f"set numdgt=12\ntran {step} {tstop}\nprint v(o)\n.endc\n.end\n")
    try:
        rr = subprocess.run([NGSPICE, "-b", os.path.basename(p)], cwd=HERE,
                            capture_output=True, text=True, timeout=300, errors="replace")
    except subprocess.TimeoutExpired:
        return []
    out = rr.stdout + rr.stderr
    pts = []
    for ln in out.splitlines():
        m = re.match(r"^\d+\s+([-\d.eE+]+)\s+([-\d.eE+]+)\s*$", ln.strip())
        if m:
            try:
                pts.append((float(m.group(1)), float(m.group(2))))
            except ValueError:
                pass
    return pts


def at(pts, t):
    return min(pts, key=lambda p: abs(p[0] - t))[1] if pts else None


print("Enhancement-512: transition reaches its final value at every speed")

# ---------------------------------------------------------------------------
# 1. the endpoint, across five decades of rise time
# ---------------------------------------------------------------------------
print("\n  value at delay + trise must be 1.0, however fast the edge")

CASES = [("3n", 3e-9, "30n", "0.01n", 0.8774),
         ("30n", 30e-9, "300n", "0.1n", 0.9873),
         ("300n", 300e-9, "3u", "1n", 0.99948),
         ("3u", 3e-6, "30u", "10n", 1.000039),
         ("30u", 30e-6, "300u", "100n", 0.999979)]
for tr, trv, tstop, step, was in CASES:
    pts = wave(f"td=1p tr={tr}", tstop, step, f"e{tr}")
    got = at(pts, trv)
    ok = got is not None and abs(got - 1.0) < 2e-3
    check(f"trise={tr:>5}: end = {got if got is None else round(got, 6)}  (was {was})",
          ok, "" if ok else f"{got}")

# ---------------------------------------------------------------------------
# 2. the shape is a ramp, not a ramp-plus-tail
# ---------------------------------------------------------------------------
print("\n  the ramp is linear over its whole length, not two thirds of it")

pts = wave("td=1p tr=3n", "30n", "0.002n", "shape")
if pts:
    # quarter points of a 0..1 linear ramp starting at ~0
    for frac in (0.25, 0.5, 0.75):
        got = at(pts, frac * 3e-9)
        ok = got is not None and abs(got - frac) < 0.02
        check(f"  at {int(frac*100)}% of the ramp, y = {round(got, 4) if got else None}"
              f" (linear: {frac})", ok)

# ---------------------------------------------------------------------------
# 3. it converges to the RIGHT value, which it did not before
# ---------------------------------------------------------------------------
print("\n  refining the timestep converges to 1.0 (it converged to 0.8776 before)")

vals = []
for step in ("0.05n", "0.01n", "0.002n"):
    pts = wave("td=1p tr=3n", "30n", step, f"c{step}")
    vals.append(at(pts, 3e-9))
check("the endpoint is stable under 25x timestep refinement",
      all(v is not None and abs(v - 1.0) < 2e-3 for v in vals),
      f"{[round(v, 5) if v else None for v in vals]}")

pts = wave("td=1p tr=3n", "30n", "0.002n", "settle")
settled = [v for t, v in pts if t > 2.4e-8]
check("and the settled value is exactly 1.0",
      settled and all(abs(v - 1.0) < 1e-9 for v in settled),
      f"[{min(settled):.9f}, {max(settled):.9f}]" if settled else "no data")
check("with no overshoot at a resolved timestep",
      pts and max(v for _, v in pts) <= 1.0 + 1e-9,
      f"max={max(v for _, v in pts):.7f}" if pts else "")

# ---------------------------------------------------------------------------
# 4. slew gets the same treatment
# ---------------------------------------------------------------------------
print("\n  slew, whose rate limit is the same loop")

pts = wave("tr=3n", "30n", "0.002n", "slew", sel=1)
got = at(pts, 3e-9)
check(f"slew reaches its final value at the end of the ramp ({round(got, 6) if got else None})",
      got is not None and abs(got - 1.0) < 2e-3)

# ---------------------------------------------------------------------------
# 5. what must NOT change: an instantaneous edge (E-504's clamp)
# ---------------------------------------------------------------------------
print("\n  an instantaneous edge still bypasses the rate limit (Enhancement-504)")

fast = wave("td=1p tr=0", "30n", "0.01n", "inst")
check("trise=0 still tracks with the old fixed gain, no NaN",
      fast and all(v == v for _, v in fast) and max(v for _, v in fast) <= 1.001,
      f"max={max(v for _, v in fast):.6f}" if fast else "no data")

print(f"\n  {passed}/{checks} checks passed")
sys.exit(0 if passed == checks else 1)
