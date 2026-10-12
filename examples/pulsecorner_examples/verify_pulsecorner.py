#!/usr/bin/env python3
"""verify_pulsecorner.py -- Enhancement-875: a voltage source landed on a
period's start schedules that period's next corner.

Found while folding F2 of the transient stress campaign of 2026-10-12.

The PULSE source finds its next corner from the time within the period,
floor((t - TD)/PER). Landed on a period's first corner, (t - TD)/PER can be
3.999999999999843: the point reads as the end of the period before, the "next
pulse" it awaits is 3.6e-21 s away, under minbreak, and the rise's end goes
unscheduled until the next point. A step that goes past it skips it; trap's
truncation estimate usually rejects such a step, trbdf2 and sdirk's do not. A
repeating PWL had the same arithmetic, and also wrapped only past its last
knot, so a point landed a hair under it found no knot left.

  [1] the pulse of the campaign network whose 5th and 7th rises were skipped:
      every corner is a point under trap, trbdf2 and sdirk (E-872: 2 missed
      under sdirk)
  [2] 20 random pulses (seeded) under trap: every corner is a point
      (E-872: corners missed in 10 of them)
  [3] a repeating PWL with an edge at the start of each repeat: every knot is
      a point under trap (E-872: 6 missed)
  [4] 20 random repeating PWLs (seeded) under trbdf2: every knot is a point
      (E-872: knots missed in 15 of them)
  [5] (control) the pulse of [1] under trap at reltol=1e-5 is within 0.1 % of
      the exact RC response at every point

Exit code 0 = pass.
"""
import math
import os
import random
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from _setup import NG as NGSPICE  # noqa: E402
from _setup import check_both_solvers as _check_both_solvers; _check_both_solvers(__file__)  # noqa: E402

WORK = tempfile.mkdtemp(prefix="pulsecorner_")
checks = passed = 0


def check(label, ok, detail=""):
    global checks, passed
    checks += 1
    passed += bool(ok)
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  [{detail}]" if detail else ""))


def run(name, src, cap, opts, tstep, tstop):
    out_file = os.path.join(WORK, name + ".txt")
    path = os.path.join(WORK, name + ".cir")
    with open(path, "w") as f:
        f.write("* %s\n%s\nr1 a b 1k\nc1 b 0 %r\n.option %s\n.control\nset numdgt=17\nset wr_singlescale\n"
                "tran %r %r\nwrdata %s v(b)\n.endc\n.end\n" % (name, src, cap, opts, tstep, tstop, out_file))
    subprocess.run([NGSPICE, "-b", path], cwd=WORK, capture_output=True, text=True, timeout=120)
    rows = []
    with open(out_file) as f:
        for line in f:
            p = line.split()
            try:
                rows.append((float(p[0]), float(p[1])))
            except (ValueError, IndexError):
                pass
    return rows


def missed(rows, corners):
    ts = [t for t, _ in rows]
    tend = ts[-1]
    out = 0
    for e in corners:
        if 0 < e < tend and min(abs(t - e) for t in ts) > 1e-12 * e:
            out += 1
    return out


def pulse_corners(td, tr, tf, pw, per, tstop):
    c = []
    k = 0
    while td + k * per < tstop:
        b = td + k * per
        c += [b, b + tr, b + tr + pw, b + tr + pw + tf]
        k += 1
    return c


# [1] the pulse of the campaign's Family A seed 1134
TD, TR, TF, PW, PER = 6.244946846361535e-09, 2.579104723200254e-11, 5.97605033382372e-11, 3.6388604507917307e-09, 2.286992722209552e-08
P1 = "v0 a 0 pulse(-0.7303076863271227 0.16849033023438031 %r %r %r %r %r)" % (TD, TR, TF, PW, PER)
TSTEP1, TSTOP1 = 8.004474527733431e-10, 1.6008949055466862e-07
corners1 = pulse_corners(TD, TR, TF, PW, PER, TSTOP1)
m1 = {m: missed(run("p1_" + m, P1, 1e-12, "method=%s reltol=1e-7 abstol=1e-15 vntol=1e-10 chgtol=1e-20" % m,
                    TSTEP1, TSTOP1), corners1) for m in ("trap", "trbdf2", "sdirk")}
check("[1] every corner of the pulse is a point under trap, trbdf2 and sdirk", not any(m1.values()),
      "missed: %s of %d" % (m1, len(corners1)))

# [2] random pulses under trap
rng = random.Random(23)
bad2 = []
for i in range(20):
    per = 10 ** rng.uniform(-8, -5); td = per * rng.uniform(0, 0.5)
    tr = per * 10 ** rng.uniform(-5, -2); tf = per * 10 ** rng.uniform(-5, -2); pw = per * rng.uniform(0.2, 0.6)
    tstep = per / rng.choice([3, 7, 20])
    rows = run("p2_%d" % i, "v1 a 0 pulse(0 1 %r %r %r %r %r)" % (td, tr, tf, pw, per), per * 1e-4, "", tstep, 15 * per)
    n = missed(rows, pulse_corners(td, tr, tf, pw, per, 15 * per))
    if n:
        bad2.append((i, n))
check("[2] 20 random pulses under trap: every corner is a point", not bad2, "decks with misses: %s" % bad2)


def pwl_rep(name, per, w, h, tstep, opts):
    knots = [(0, 0), (w, 1), (h, 1), (h + w, 0), (per, 0)]
    src = "v1 a 0 pwl(%s) r=0" % " ".join("%r %r" % kv for kv in knots)
    rows = run(name, src, per * 1e-4, opts, tstep, 15 * per)
    return missed(rows, [k * per + c for k in range(15) for c, _ in knots[1:]])


# [3] a repeating PWL with an edge at each repeat's start, under trap
n3 = pwl_rep("p3", 9.157303339294473e-07, 6.433624570080442e-10, 3.179857362792193e-07, 3.052434446431491e-07, "")
check("[3] a repeating PWL: every knot is a point under trap", n3 == 0, "missed %d" % n3)

# [4] random repeating PWLs under trbdf2
rng = random.Random(11)
bad4 = []
for i in range(20):
    per = 10 ** rng.uniform(-8, -5)
    w = per * 10 ** rng.uniform(-5, -2); h = per * rng.uniform(0.3, 0.6)
    tstep = per / rng.choice([3, 7, 20])
    n = pwl_rep("p4_%d" % i, per, w, h, tstep, "method=trbdf2")
    if n:
        bad4.append((i, n))
check("[4] 20 random repeating PWLs under trbdf2: every knot is a point", not bad4, "decks with misses: %s" % bad4)

# [5] accuracy of [1] under trap against the exact first-order response
rows = run("p5", "v0 a 0 pulse(0 1 %r %r %r %r %r)" % (TD, TR, TF, PW, PER), 1e-12, "reltol=1e-5", TSTEP1, TSTOP1)
tau = 1e3 * 1e-12
knots = [(0.0, 0.0)]
for k in range(8):
    b = TD + k * PER
    for t, v in ((b, 0.0), (b + TR, 1.0), (b + TR + PW, 1.0), (b + TR + PW + TF, 0.0)):
        if t > knots[-1][0]:
            knots.append((t, v))


def exact(t):
    v = 0.0
    t0 = 0.0
    for (ta, ua), (tb, ub) in zip(knots, knots[1:]):
        if ta >= t:
            break
        s = (ub - ua) / (tb - ta)
        t1 = min(t, tb)
        u0 = ua + s * (t0 - ta)
        dt = t1 - t0
        v = u0 + s * dt - s * tau + (v - u0 + s * tau) * math.exp(-dt / tau)
        t0 = t1
    if t > t0:
        v = knots[-1][1] + (v - knots[-1][1]) * math.exp(-(t - t0) / tau)
    return v


err = max(abs(v - exact(t)) for t, v in rows)
check("[5] (control) the pulse under trap at reltol=1e-5 is within 0.1 % of the exact RC response", err < 1e-3,
      "max error %.2e" % err)

print(f"\n{passed}/{checks} checks passed")
sys.exit(0 if passed == checks else 1)
