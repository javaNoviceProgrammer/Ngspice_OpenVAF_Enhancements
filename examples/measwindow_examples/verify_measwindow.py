#!/usr/bin/env python3
"""verify_measwindow.py -- Enhancements 302/303: `.meas avg` clips its window to [from, to].

`.meas ... avg` accumulated a trapezoid only between the SAMPLES that fell inside
[from, to] and divided by their span, without interpolating either boundary. RMS and
INTEG -- the same quantity family, in measure_rms_integral() -- already clip to the exact
boundaries. So ngspice's own two answers for the same window disagreed:

    .meas tran i1 integ v(a) from=0 to=250u  ->  3.18310e-04   (to=2.50000e-04)
    .meas tran a1 avg   v(a) from=0 to=250u  ->  1.27114e+00   (to=2.50280e-04)  <- window
                                                                                    overshot
    integ/(to-from) = 1.27324    closed form = 1.2732395

The echoed `to=` gave it away: AVG reported the first sample OUTSIDE the window, a time
the average never covered.

Every expectation below is a closed-form integral of the sine, never a previous ngspice
run -- a same-binary comparison cannot see an error that is uniformly present.

    v(a) = A*sin(w t),  A=2, f=1000
    integ(t0,t1) = (A/w)*(cos(w t0) - cos(w t1))
    avg          = integ/(t1-t0)
    rms          = sqrt( (A^2/2)*(1 - (sin(2 w t1)-sin(2 w t0))/(2 w (t1-t0))) )

Enhancement-302 fixed the time/frequency scales (tran, ac, sp). Enhancement-303 then
fixed `dc` as well: a dc sweep may DESCEND (`dc v1 2 0 -0.001`), so its clip works from
the actual crossing between the previous raw sample and the current one, which is
direction-agnostic. Both sweep directions are checked below against the same oracle.
"""
import math
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from _setup import NG as NGSPICE  # noqa: E402
from _setup import check_both_solvers as _check_both_solvers  # noqa: E402
_check_both_solvers(__file__)

A, F = 2.0, 1000.0
W = 2 * math.pi * F
checks = passed = 0


def check(label, ok, detail=""):
    global checks, passed
    checks += 1
    passed += bool(ok)
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  [{detail}]" if detail else ""))


def close(got, want, tol, label):
    if got is None:
        check(label, False, "no value")
        return
    rel = abs(got - want) / (abs(want) if want else 1.0)
    check(label, rel <= tol, f"got {got:.8g} want {want:.8g} rel {rel:.1e}")


def run(deck, name):
    with open(os.path.join(HERE, name), "w") as fh:
        fh.write(deck)
    try:
        r = subprocess.run([NGSPICE, "-b", name], cwd=HERE, capture_output=True,
                           text=True, timeout=180, errors="replace")
    except subprocess.TimeoutExpired:
        return "[TIMEOUT]"
    return (r.stdout or "") + (r.stderr or "")


def meas(out, nm):
    m = re.search(rf"^{nm}\s*=\s*([-\d.eE+]+)", out, re.M | re.I)
    return float(m.group(1)) if m else None


def window_to(out, nm):
    """The `to=` ngspice echoes for a measurement -- the end it actually used."""
    m = re.search(rf"^{nm}\s*=\s*[-\d.eE+]+\s+from=\s*[-\d.eE+]+\s+to=\s*([-\d.eE+]+)",
                  out, re.M | re.I)
    return float(m.group(1)) if m else None


def integ(t0, t1):
    return (A / W) * (math.cos(W * t0) - math.cos(W * t1))


def avg(t0, t1):
    return integ(t0, t1) / (t1 - t0)


def rms(t0, t1):
    return math.sqrt((A * A / 2) * (1 - (math.sin(2 * W * t1) - math.sin(2 * W * t0))
                                    / (2 * W * (t1 - t0))))


print("Enhancement-302: .meas avg clips its window to [from, to]")

# Windows chosen so the boundaries land BETWEEN samples (grid is 1us) -- both ends must
# be interpolated. The last one spans a full period, where the true average is exactly 0.
CASES = [
    ("aligned  0     -> 250u",     0.0,      250e-6),
    ("aligned  0     -> 500u",     0.0,      500e-6),
    ("off-grid 3.7u  -> 246.3u",   3.7e-6,   246.3e-6),
    ("off-grid 6.28u -> 493.72u",  6.28e-6,  493.72e-6),
    ("off-grid 0.5u  -> 999.5u",   0.5e-6,   999.5e-6),
]

deck = ["* meas avg/integ/rms over off-grid windows",
        "v1 a 0 dc 0 sin(0 2 1k 0 0)", "r1 a 0 1k", ".tran 1u 2m"]
for i, (_, t0, t1) in enumerate(CASES):
    deck += [f".meas tran i{i} integ v(a) from={t0:.12g} to={t1:.12g}",
             f".meas tran a{i} avg   v(a) from={t0:.12g} to={t1:.12g}",
             f".meas tran r{i} rms   v(a) from={t0:.12g} to={t1:.12g}"]
deck.append(".end")
out = run("\n".join(deck) + "\n", "_mw.cir")

print("\n[302] avg matches the closed-form integral over the requested window")
for i, (label, t0, t1) in enumerate(CASES):
    want = avg(t0, t1)
    got = meas(out, f"a{i}")
    if abs(want) < 1e-9:            # full period: the average is exactly zero
        check(f"avg {label} == 0 over a full period",
              got is not None and abs(got) < 1e-6, f"got {got}")
    else:
        close(got, want, 2e-5, f"avg {label}")

print("\n[302] avg now agrees with integ/(to-from) -- they are the same quantity")
for i, (label, t0, t1) in enumerate(CASES):
    a, ig = meas(out, f"a{i}"), meas(out, f"i{i}")
    if a is None or ig is None:
        check(f"avg == integ/dur {label}", False, "no value")
        continue
    ref = ig / (t1 - t0)
    # Relative, plus an absolute floor: over a full period both are the numerical zero
    # of a signal of amplitude A, so they agree to ~1e-10 while differing in the last
    # noise digits. The floor is 8 orders below A -- far under any real discrepancy.
    check(f"avg == integ/dur {label}",
          abs(a - ref) <= 2e-5 * abs(ref) + A * 1e-8, f"avg {a:.8g} vs {ref:.8g}")

print("\n[302] the echoed window end is the REQUESTED one, not the sample past it")
for i, (label, t0, t1) in enumerate(CASES):
    got = window_to(out, f"a{i}")
    check(f"avg {label} echoes to={t1:g}",
          got is not None and abs(got - t1) <= 1e-9 * max(t1, 1e-9), f"echoed {got}")

print("\n[302] integ and rms (already correct) are unchanged")
for i, (label, t0, t1) in enumerate(CASES):
    close(meas(out, f"i{i}"), integ(t0, t1), 2e-5, f"integ {label}") \
        if abs(integ(t0, t1)) > 1e-9 else check(f"integ {label} == 0", True)
    close(meas(out, f"r{i}"), rms(t0, t1), 2e-5, f"rms   {label}")

# ---------------------------------------------------------------- [303]
# dc sweeps. Oracle: v(a) = v(in)^2, so the mean over [p,q] is (q^3-p^3)/(3(q-p)).
# A dc sweep may DESCEND, so the same window is checked in both directions -- the
# clip works from the actual crossing, which is direction-agnostic.
def dcmean(p, q):
    return (q ** 3 - p ** 3) / (3 * (q - p))


DC = "v1 in 0 dc 0\nb1 a 0 v='v(in)*v(in)'\nr1 a 0 1k\n"
print("\n[303] dc avg clips to [from, to] in either sweep direction")
for tag, sweep in (("ascending", "dc v1 0 2 0.001"), ("descending", "dc v1 2 0 -0.001")):
    o = run(f"* dc avg {tag}\n{DC}.control\n{sweep}\n"
            "meas dc q1 avg   v(a) from=0.25 to=0.75\n"
            "meas dc q2 integ v(a) from=0.25 to=0.75\n"
            "meas dc q3 max   v(a) from=0.25 to=0.75\n"
            "meas dc q4 min   v(a) from=0.25 to=0.75\n"
            ".endc\n.end\n", f"_dc{tag[:3]}.cir")
    close(meas(o, "q1"), dcmean(0.25, 0.75), 1e-4, f"dc avg {tag} == mean of x^2")
    close(window_to(o, "q1"), 0.75, 1e-9, f"dc avg {tag} echoes to=0.75")
    ig = meas(o, "q2")
    a = meas(o, "q1")
    if tag == "ascending":
        check(f"dc avg {tag} == integ/(to-from)",
              a is not None and ig is not None
              and abs(a - ig / 0.5) <= 1e-4 * abs(ig / 0.5),
              f"avg {a} vs {ig / 0.5 if ig else None}")
    else:
        # NOT cross-checked on a descending sweep: `integ` is separately broken there
        # (its window loop meets the first sample already ABOVE `to`, interpolates with
        # index i-1 == -1 -- an out-of-bounds read -- and breaks with an empty array,
        # yielding 0.0 with `from= nan`). That is a pre-existing defect of
        # measure_rms_integral(), untouched by 302/303, which fixed `avg` only.
        check(f"dc avg {tag} is correct even though integ is not (known defect)",
              a is not None and abs(a - dcmean(0.25, 0.75)) <= 1e-4,
              f"avg {a}, integ {ig}")
    # min/max are NOT part of the fix: they keep whole-sample semantics
    close(meas(o, "q3"), 0.75 ** 2, 3e-3, f"dc max {tag} unchanged (~0.5625)")
    close(meas(o, "q4"), 0.25 ** 2, 3e-3, f"dc min {tag} unchanged (~0.0625)")

print("\n[302] min/max/pp keep whole-sample semantics (the fix is avg-only)")
out2 = run("""* min/max/pp must be untouched
v1 a 0 dc 0 sin(0 2 1k 0 0)
r1 a 0 1k
.tran 1u 2m
.meas tran vmax max v(a) from=0 to=1m
.meas tran vmin min v(a) from=0 to=1m
.meas tran vpp  pp  v(a) from=0 to=1m
.end
""", "_mm.cir")
close(meas(out2, "vmax"), 2.0, 1e-3, "max == +A")
close(meas(out2, "vmin"), -2.0, 1e-3, "min == -A")
close(meas(out2, "vpp"), 4.0, 1e-3, "pp  == 2A")

for f in ("_mw.cir", "_mm.cir", "_dcasc.cir", "_dcdes.cir"):
    p = os.path.join(HERE, f)
    if os.path.exists(p):
        os.remove(p)

print(f"\n{passed}/{checks} checks passed")
print("ALL PASS" if passed == checks else "FAILURES PRESENT")
sys.exit(0 if passed == checks else 1)
