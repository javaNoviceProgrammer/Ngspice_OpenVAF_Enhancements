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

# ---------------------------------------------------------------------------
# 4. Enhancement-697 (hunt F7 of 2026-09-21): a rate at or above 1e12 V/s is
#    instantaneous. With K = 1e3 * rate a slew at 1e13 V/s had a 0.1 fs tail that
#    ngspice could not resolve at the corner where the clamp releases: the step
#    shrank to 1e-17 s and the transient ABORTED at the first edge ("Timestep too
#    small ... implicit_equation"), from 1e13 up to 1e297 where the infinite-rate
#    guard finally took over. Such a side takes the infinite-rate path now (no
#    clamp, the fixed 1e9/s gain); 1e12 V/s and below are the exact ramp as before.
# ---------------------------------------------------------------------------
print("\n  a rate at or above 1e12 V/s is instantaneous, not an abort")
for tr, sel, what in (("1e-13", 1, "slew at 1e13 V/s"), ("1e-30", 1, "slew at 1e30 V/s"), ("1e-13", 0, "transition with a 0.1 ps rise")):
    pts = wave(f"tr={tr}", "1u", "10n", f"inst_{sel}_{tr}", sel=sel)
    got = at(pts, 0.5e-6)
    check(f"{what} runs the transient and settles at 1.0 (it aborted at the first edge)",
          pts and got is not None and abs(got - 1.0) < 1e-6, f"{len(pts)} points, y(0.5u)={got}")

# ---------------------------------------------------------------------------
# 5. Enhancement-698 (hunt F1 and F2 of 2026-09-21): transition and slew are the
#    simulator's. The tracking loop compiled into the model ran at the fixed
#    RATE 1/tr, so a 5 V swing took 5 * tr and a 0.2 V swing 0.2 * tr (LRM
#    4.5.8: every transition takes rise_time); and, a stiff ODE, it rang under
#    the trapezoidal rule when the edge fell inside a timestep -- the plateau
#    read 0.99981 for the rest of the run and `ddt` of it a spurious current of
#    up to 0.84 mA where the true current is 0. Now the simulator schedules
#    the ramp from the accepted change of the input, with the corners as
#    breakpoints: exact amplitude, exact plateau at any step, a clean `ddt`,
#    the LRM's interrupted-transition rule, and a continuous input that no
#    longer breeds breakpoints.
# ---------------------------------------------------------------------------
print("\n  Enhancement-698: the ramp takes rise_time whatever the swing, at any step")

TRAMP = os.path.join(HERE, "_te_tramp.osdi")
r = subprocess.run([OPENVAF, os.path.join(HERE, "tramp.va"), "-o", TRAMP],
                   capture_output=True, text=True, timeout=300, cwd=HERE)
check("tramp.va compiles", os.path.exists(TRAMP), (r.stdout + r.stderr).strip()[-160:])

AT = "@"


def meas(card, src, tstop, step, tag, lines, opts=""):
    """run the comparator model on `src`, return {name: value} of the meas lines"""
    p = os.path.join(HERE, f"_te_{tag}.cir")
    with open(p, "w") as f:
        f.write(f"transedge 698\n{src}\nN1 a o mm\n.model mm tramp {card}\nRo o 0 1e12\n"
                f"{opts}\n.control\npre_osdi {os.path.basename(TRAMP)}\noption noacct\n"
                f"save all {AT}n1[ic]\ntran {step} {tstop}\n{lines}\n.endc\n.end\n")
    try:
        rr = subprocess.run([NGSPICE, "-b", os.path.basename(p)], cwd=HERE,
                            capture_output=True, text=True, timeout=300, errors="replace")
    except subprocess.TimeoutExpired:
        return {}
    vals = {}
    for ln in (rr.stdout + rr.stderr).splitlines():
        m = re.match(r"^(\w+)\s*=\s*([-\d.eE+]+)", ln.strip())
        if m:
            try:
                vals[m.group(1)] = float(m.group(2))
            except ValueError:
                pass
    return vals


PULSE = "V1 a 0 PULSE(0 1 1m 1n 1n 2m 10m)"
for amp in (1.0, 5.0, 0.2, -3.0):
    v = meas(f"amp={amp} tr=1u tf=1u", PULSE, "6m", "10u", f"amp{amp}",
             "meas tran vmid FIND v(o) AT=1.0005m\nmeas tran vtop FIND v(o) AT=1.0011m\n"
             "meas tran vfmid FIND v(o) AT=3.0005m\nmeas tran vlow FIND v(o) AT=3.0011m\n"
             "meas tran vpl FIND v(o) AT=2.5m\nmeas tran vpl0 FIND v(o) AT=5.5m")
    ok = (abs(v.get("vmid", 9) - amp / 2) < 0.02 * abs(amp) and abs(v.get("vtop", 9) - amp) < 1e-9
          and abs(v.get("vfmid", 9) - amp / 2) < 0.02 * abs(amp) and abs(v.get("vlow", 9)) < 1e-9
          and abs(v.get("vpl", 9) - amp) < 1e-9 and abs(v.get("vpl0", 9)) < 1e-9)
    check(f"a swing of {amp}: half way at 0.5 us, done at 1 us, both edges; plateaus exactly "
          f"{amp} and 0 at a 10 us step under trap (was {amp} * 1 us, and 0.99981)", ok,
          " ".join(f"{k}={v[k]:.6g}" for k in ("vmid", "vtop", "vfmid", "vlow", "vpl", "vpl0") if k in v))

v = meas("amp=1 tr=1u tf=1u c=1n", PULSE, "4m", "0.1u", "ddt",
         f"let aic = abs({AT}n1[ic])\nmeas tran peak MAX aic from=0 to=4m\n"
         f"meas tran tail MAX aic from=1.2m to=2.9m\nmeas tran ic25 FIND {AT}n1[ic] AT=2.5m")
check("ddt(1n * transition) at a 0.1 us step: the edge current is 1 mA and the plateau "
      "current is 0 (was 2e-4 V ringing: up to 0.84 mA across the plateau)",
      abs(v.get("peak", 9) - 1e-3) < 1e-8 and abs(v.get("tail", 9)) < 1e-15
      and abs(v.get("ic25", 9)) < 1e-15,
      " ".join(f"{k}={v[k]:.6g}" for k in ("peak", "tail", "ic25") if k in v))

v = meas("amp=1 tr=1u tf=1u sel=1", PULSE, "6m", "10u", "slew",
         "meas tran vpl FIND v(o) AT=2.5m\nmeas tran vpl0 FIND v(o) AT=5.5m\n"
         "meas tran vmax MAX v(o) from=0 to=6m\nmeas tran vmin MIN v(o) from=0 to=6m")
check("slew of the comparator at 1 V/us, 10 us step: plateaus exactly 1 and 0, never outside "
      "[0, 1] (was 0.99981 / 1.82e-4 with an overshoot to 1.00020)",
      abs(v.get("vpl", 9) - 1) < 1e-9 and abs(v.get("vpl0", 9)) < 1e-9
      and v.get("vmax", 9) <= 1 + 1e-9 and v.get("vmin", -9) >= -1e-9,
      " ".join(f"{k}={v[k]:.6g}" for k in ("vpl", "vpl0", "vmax", "vmin") if k in v))

# LRM 4.5.8, Figure 4-7: a 0 -> 2 ramp over 100 us reversed after 50 us is at
# 1.0 when interrupted; the readjusted fall takes its slope from the original
# DESTINATION, (0 - 2)/100u, so it reaches 0 at 1.05 ms + 50 us.
v = meas("amp=2 tr=100u tf=100u", "V1 a 0 PULSE(0 1 1m 1n 1n 50u 10m)", "1.3m", "1u", "intr",
         "meas tran vi FIND v(o) AT=1.05m\nmeas tran vh FIND v(o) AT=1.075m\n"
         "meas tran vz FIND v(o) AT=1.101m\nmeas tran tz WHEN v(o)=0.01 FALL=1")
check("interrupted ramp (4.5.8 Figure 4-7): 1.0 at the reversal (was 0.5), 0.5 half way "
      "down, back at 0 by 1.101 ms, y = 0.01 at 1.0995 ms",
      abs(v.get("vi", 9) - 1.0) < 1e-3 and abs(v.get("vh", 9) - 0.5) < 1e-3
      and abs(v.get("vz", 9)) < 1e-9 and abs(v.get("tz", 9) - 1.0995e-3) < 1e-6,
      " ".join(f"{k}={v[k]:.6g}" for k in ("vi", "vh", "vz", "tz") if k in v))

v = meas("tr=1u tf=1u sel=2", "V1 a 0 SIN(0.5 1 1k)", "2.5m", "1u", "sine",
         "meas tran vend FIND v(o) AT=2.5m\nmeas tran n FIND time AT=2.5m")
check("a sine through transition (a continuous input, LRM: 'may run slowly') completes and "
      "follows: 0.5 +- 0.1 at 2.5 ms (it bred a breakpoint per timepoint and never finished)",
      "vend" in v and abs(v["vend"] - 0.5) < 0.1, f"vend={v.get('vend')}")

# ---------------------------------------------------------------------------
# 6. Enhancement-720 (correctness campaign 2, F3 of 2026-09-25): a source's
#    edge fed straight into transition() -- a PULSE with a 1 ns rise, which
#    the integrator resolves with a dozen accepted points -- is a dozen
#    CHANGES of the input, and the reversal rule of LRM 4.5.8 (Figure 4-7)
#    took the interrupted ramp's destination, which by then was the input's
#    value at the last point on the near side of the output (0.683 of a 1 V
#    edge, wherever the timepoint fell): the readjusted slope was 0.68/tf,
#    set by the step and by the delay path, where the comparator form above
#    gives (v3 - v2)/tf = 1/tf. Every change after an edge's first readjusts
#    against the ramp the first change found, and the edge's ramp gets its
#    trailing corner breakpoint once the input holds still.
# ---------------------------------------------------------------------------
print("\n  Enhancement-720: a source edge fed straight in is one change, whatever its width")

INTR = "V1 a 0 PULSE(0 1 1m {e} {e} 50u 10m)"
LINES = ("meas tran vi FIND v(o) AT={ti}\nmeas tran vh FIND v(o) AT={th}\n"
         "meas tran vz FIND v(o) AT={tz}\nmeas tran tz WHEN v(o)=0.01 FALL=1")


def intr(card, tag, td=0.0, edge="1n", opts=""):
    return meas(card, INTR.format(e=edge), "1.3m", "1u", tag,
                LINES.format(ti=1.05e-3 + td, th=1.075e-3 + td, tz=1.1005e-3 + td), opts)


def intr_ok(v, td=0.0):
    return (abs(v.get("vi", 9) - 0.5) < 1e-3 and abs(v.get("vh", 9) - 0.25) < 1e-3
            and abs(v.get("vz", 9)) < 1e-9 and abs(v.get("tz", 9) - (1.099e-3 + td)) < 1e-6)


def intr_got(v):
    return " ".join(f"{k}={v[k]:.6g}" for k in ("vi", "vh", "vz", "tz") if k in v)


v = intr("tr=100u tf=100u sel=2", "e720")
check("the 1 ns edge of a source through transition(V(a), 0, 100u, 100u), reversed at 0.5: "
      "falls at (0 - 1)/tf as the comparator does -- 0.25 at +25 us, 0 by +50 us, y = 0.01 at "
      "1.099 ms (was 0.68/tf: 0.01 at 1.120 ms)", intr_ok(v), intr_got(v))

v = intr("tr=100u tf=100u td=10u sel=2", "e720d", td=10e-6)
check("the same behind a 10 us delay (the edge's points come due as a burst): 0.25 at "
      "1.085 ms, y = 0.01 at 1.109 ms (was 0.01 at 1.130 ms)", intr_ok(v, 10e-6), intr_got(v))

v = intr("tr=100u tf=100u sel=2", "e720r", edge="1p", opts=".options reltol=1e-6")
check("a 1 ps edge under reltol=1e-6 (other timepoints inside the edge): the same slope -- "
      "the reversal's reference is the edge's level, not where a timepoint fell",
      intr_ok(v), intr_got(v))

v = meas("tr=1u tf=1u sel=2", PULSE, "6m", "10u", "e720u",
         "meas tran vmid FIND v(o) AT=1.0005m\nmeas tran vtop FIND v(o) AT=1.0011m\n"
         "meas tran vfmid FIND v(o) AT=3.0005m\nmeas tran vlow FIND v(o) AT=3.0011m")
check("an uninterrupted source edge is as it was: half way at 0.5 us, done at 1 us, both edges",
      abs(v.get("vmid", 9) - 0.5) < 0.02 and abs(v.get("vtop", 9) - 1) < 1e-9
      and abs(v.get("vfmid", 9) - 0.5) < 0.02 and abs(v.get("vlow", 9)) < 1e-9,
      " ".join(f"{k}={v[k]:.6g}" for k in ("vmid", "vtop", "vfmid", "vlow") if k in v))

print(f"\n  {passed}/{checks} checks passed")
sys.exit(0 if passed == checks else 1)
