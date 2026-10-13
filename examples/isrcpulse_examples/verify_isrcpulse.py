#!/usr/bin/env python3
"""verify_isrcpulse.py -- Enhancement-877: a PULSE current source schedules its
corners as a voltage source does.

F4 of the transient stress campaign of 2026-10-12.

ISRCaccept set a pulse's next corner only when an accepted point landed on the
current one, to 1e-7 of the pulse width. A rise shorter than minbreak cannot be
landed on, so the chain stopped and every later edge was stepped over: the same
pulse into the same RC was 3.0e-2 off from a current source and 2.8e-4 from a
voltage source. The current source now schedules its next corner from the
time within the period and a per-run break time, as VSRCaccept does
(Enhancement-875 included), with the defaults its own load uses.

  [1] a 0.1 ps-edge pulse into an RC: the current source is within 1.2x of the
      voltage source's error against the exact response, in as many points
      (E-875: 3.0e-2 against 2.8e-4, 219 points against 381)
  [2] 15 random pulses (seeded) with edges from 1e-8 to 1e-2 of the period:
      the current and the voltage source put their points at the same times
  [3] (control) a pulse with a count (8th parameter = 2): the same grid as the
      voltage source
  [4] (control) a second `tran` in the same session repeats the first, point
      for point (the break time is re-armed per run)
  [5] (control) with 1 ns edges both sources land on every corner

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

WORK = tempfile.mkdtemp(prefix="isrcpulse_")
checks = passed = 0


def check(label, ok, detail=""):
    global checks, passed
    checks += 1
    passed += bool(ok)
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  [{detail}]" if detail else ""))


def read(path):
    rows = []
    with open(path) as f:
        for line in f:
            p = line.split()
            try:
                rows.append([float(x) for x in p])
            except ValueError:
                pass
    return rows


def run(name, kind, args, cap, tstep, tstop, opts="", twice=False):
    """the pulse as a current source into R||C, or as a voltage source through R into C"""
    if kind == "i":
        src = "i1 0 b pulse(0 1m %s)\nr1 b 0 1k" % args
    else:
        src = "v1 a 0 pulse(0 1 %s)\nr1 a b 1k" % args
    out = os.path.join(WORK, name + ".txt")
    ctl = "tran %r %r\n" % (tstep, tstop)
    if twice:
        out2 = os.path.join(WORK, name + "_2.txt")
        ctl += "wrdata %s v(b)\ntran %r %r\nwrdata %s v(b)\n" % (out, tstep, tstop, out2)
    else:
        ctl += "wrdata %s v(b)\n" % out
    path = os.path.join(WORK, name + ".cir")
    with open(path, "w") as f:
        f.write("* %s\n%s\nc1 b 0 %r\n.option %s\n.control\nset numdgt=17\nset wr_singlescale\n%s.endc\n.end\n"
                % (name, src, cap, opts, ctl))
    subprocess.run([NGSPICE, "-b", path], cwd=WORK, capture_output=True, text=True, timeout=120)
    if twice:
        return read(out), read(out2)
    return read(out)


def same_grid(a, b):
    if len(a) != len(b) or not a:
        return False
    return all(abs(x[0] - y[0]) <= 1e-12 * max(abs(y[0]), 1e-30) for x, y in zip(a, b))


# [1] the campaign's 0.1 ps-edge pulse against the exact response
td, per, pw, tau = 0.7e-6, 3e-6, 1.4e-6, 1e-6


def exact(t):
    v, tp, lv, ev, k = 0.0, 0.0, 0.0, [], 0
    while td + k * per < 14e-6:
        ev += [(td + k * per, 1.0), (td + k * per + pw, 0.0)]
        k += 1
    for te, level in ev:
        if te > t:
            break
        v = lv + (v - lv) * math.exp(-(te - tp) / tau)
        tp, lv = te, level
    return lv + (v - lv) * math.exp(-(t - tp) / tau)


args1 = "0.7u 0.1p 0.1p 1.4u 3u"
ri = run("p1i", "i", args1, 1e-9, 0.1e-6, 13e-6)
rv = run("p1v", "v", args1, 1e-9, 0.1e-6, 13e-6)
ei = max(abs(r[1] - exact(r[0])) for r in ri)
ev = max(abs(r[1] - exact(r[0])) for r in rv)
check("[1] 0.1 ps edges: the current source is within 1.2x of the voltage source's error, in as many points",
      ei <= 1.2 * ev and len(ri) == len(rv), "current %.2e in %d points, voltage %.2e in %d" % (ei, len(ri), ev, len(rv)))

# [2] random pulses: the same grids
rng = random.Random(5)
bad = []
for i in range(15):
    P = 10 ** rng.uniform(-8, -5)
    tdi = P * rng.uniform(0, 0.5)
    tr = P * 10 ** rng.uniform(-8, -2)
    tf = P * 10 ** rng.uniform(-8, -2)
    pwi = P * rng.uniform(0.2, 0.6)
    tstep = P / rng.choice([3, 7, 20])
    a = "%r %r %r %r %r" % (tdi, tr, tf, pwi, P)
    gi = run("p2i_%d" % i, "i", a, 1e-12, tstep, 15 * P)
    gv = run("p2v_%d" % i, "v", a, 1e-12, tstep, 15 * P)
    if not same_grid(gi, gv):
        bad.append((i, len(gi), len(gv)))
check("[2] 15 random pulses: the current and the voltage source put their points at the same times",
      not bad, "differing: %s" % bad)

# [3] a pulse with a count
a3 = "0.2u 10n 10n 0.5u 1u 2"
gi = run("p3i", "i", a3, 1e-9, 0.05e-6, 6e-6)
gv = run("p3v", "v", a3, 1e-9, 0.05e-6, 6e-6)
check("[3] (control) a pulse with a count of 2: the same grid as the voltage source",
      same_grid(gi, gv), "%d vs %d points" % (len(gi), len(gv)))

# [4] a second tran in the same session
g1, g2 = run("p4", "i", args1, 1e-9, 0.1e-6, 13e-6, twice=True)
check("[4] (control) a second tran in the same session repeats the first, point for point",
      same_grid(g1, g2) and all(abs(x[1] - y[1]) == 0.0 for x, y in zip(g1, g2)),
      "%d and %d points" % (len(g1), len(g2)))

# [5] control: 1 ns edges
a5 = "0.7u 1n 1n 1.4u 3u"
gi = run("p5i", "i", a5, 1e-9, 0.1e-6, 13e-6)
gv = run("p5v", "v", a5, 1e-9, 0.1e-6, 13e-6)
corners = [td + k * per + c for k in range(5) for c in (0, 1e-9, 1e-9 + pw, 2e-9 + pw)]


def landed(g):
    ts = [r[0] for r in g]
    return sum(1 for c in corners if c < ts[-1] and min(abs(t - c) for t in ts) <= 1e-15)


check("[5] (control) with 1 ns edges both sources land on every corner",
      landed(gi) == landed(gv) == sum(1 for c in corners if c < 13e-6), "current %d, voltage %d of %d"
      % (landed(gi), landed(gv), sum(1 for c in corners if c < 13e-6)))

print(f"\n{passed}/{checks} checks passed")
sys.exit(0 if passed == checks else 1)
