#!/usr/bin/env python3
"""
verify_ptcont.py -- Enhancement-127: pseudo-transient continuation (`.option
ptcont`), a Ẋ-embedded homotopy for the DC operating point. End-to-end through the
committed ngspice.

The DC problem f(x)=0 is embedded in a fictitious backward-Euler pseudo-transient
    f(x) + Gps*(x - x_prev) = 0,   Gps = Cps/dtau,
and the pseudo-timestep dtau is marched from small (Gps large, strongly damped and
well-conditioned) to large (Gps -> 0, the true DC point). The Gps diagonal is added
at factor time (like gmin stepping); the Gps*x_prev coupling is added to the RHS
inside NIiter, which is what makes each step a stable trajectory step rather than a
static gmin step. OFF by default.

Two properties, checked under BOTH linear solvers (KLU default + legacy Sparse1.3):

  [1] `.option ptcont` is accepted (not an unknown option).
  [2] RESULT-NEUTRALITY: on a battery of normal nonlinear DC circuits the converged
      node voltages with ptcont ON are identical to a normal run -- a convergence
      aid must never change the answer.
  [3] CONVERGENCE POWER: a deliberately stiff circuit -- a behavioral exponential
      with no junction limiting -- where plain Newton (gmin/source stepping
      disabled) overshoots to a spurious root, but pseudo-transient continuation
      reaches the physically correct operating point V(1) = 0.837922 V (the root of
      1e-14*(exp(V/0.026)-1) = (100-V)/100), verified against the analytic value and
      shown to differ from the non-ptcont result.
"""
import math
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from _setup import NG as NGSPICE

checks = passed = 0
def check(label, ok, detail=""):
    global checks, passed
    checks += 1; passed += bool(ok)
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  [{detail}]" if detail and not ok else ""))

# normal circuits (converge with plain Newton) -> result-neutrality
CIRCUITS = {
    "diode":     ("d1 1 0 dm\nr1 2 1 1k\nv1 2 0 5\n.model dm d(is=1e-14)", ["1"]),
    "bjt":       ("vcc cc 0 5\nrc cc c 2k\nvbb bb 0 2\nrb bb b 100k\n"
                  "q1 c b 0 qm\n.model qm npn(is=1e-15 bf=100)", ["c", "b"]),
    "two_diode": ("v1 a 0 3\nr1 a b 470\nd1 b m dm\nrm m 0 220\nd2 m 0 dm\n"
                  ".model dm d(is=1e-15)", ["b", "m"]),
    "res_net":   ("r1 1 0 1k\nr2 2 1 2k\nr3 2 0 3k\ni1 0 2 1m", ["1", "2"]),
}

# the deliberately stiff hard case (no junction limiting)
HARD = "b1 1 0 I = 1e-14 * (exp(V(1)/0.026) - 1)\nr1 2 1 100\nv1 2 0 100"
def hard_analytic():
    lo, hi = 0.0, 10.0
    f = lambda V: 1e-14 * (math.exp(min(V/0.026, 700)) - 1) - (100 - V) / 100
    for _ in range(200):
        m = (lo + hi) / 2
        if f(lo) * f(m) <= 0: hi = m
        else: lo = m
    return (lo + hi) / 2
HARD_V = hard_analytic()   # 0.837922...

def run(body, nodes, opts):
    deck = f"ptcont test\n{opts}\n{body}\n.op\n.control\nrun\nprint {' '.join('v('+n+')' for n in nodes)}\n.endc\n.end\n"
    p = os.path.join(HERE, "_tmp.cir")
    with open(p, "w") as f:
        f.write(deck)
    r = subprocess.run([NGSPICE, "-b", p], capture_output=True, text=True, timeout=90)
    os.remove(p)
    out = r.stdout + r.stderr
    vals = {n: (float(m.group(1)) if (m := re.search(rf"v\({n}\)\s*=\s*([\-0-9.eE+]+)", out)) else None)
            for n in nodes}
    unknown = "unknown option" in out.lower() or "unrecognized" in out.lower()
    return vals, unknown, out

def close(a, b):
    return a is not None and b is not None and abs(a - b) <= 1e-6 * (abs(a) + abs(b)) + 1e-12

print("Enhancement-127: pseudo-transient continuation")

# [1] option accepted
_, unknown, _ = run(CIRCUITS["diode"][0], ["1"], ".option ptcont")
check("`.option ptcont` accepted (not an unknown option)", not unknown)

for solver, sopt in (("KLU", ""), ("SPARSE", ".option sparse\n")):
    # [2] result-neutrality across the battery
    for name, (body, nodes) in CIRCUITS.items():
        off, _, _ = run(body, nodes, sopt.strip())
        on, _, _ = run(body, nodes, sopt + ".option ptcont gminsteps=0 srcsteps=0")
        conv = all(on[n] is not None for n in nodes)
        neutral = all(close(off[n], on[n]) for n in nodes)
        check(f"[{solver}] {name}: converges with ptcont ON", conv)
        check(f"[{solver}] {name}: result-neutral (ON == OFF)", neutral,
              ", ".join(f"{n}:{off[n]}!={on[n]}" for n in nodes))

    # [3] convergence power on the stiff circuit
    ptc, _, _ = run(HARD, ["1"], sopt + ".option ptcont gminsteps=0 srcsteps=0")
    nop, _, _ = run(HARD, ["1"], sopt + ".option gminsteps=0 srcsteps=0")
    check(f"[{solver}] stiff circuit: ptcont reaches the correct DC V(1)={HARD_V:.6f} "
          f"(got {ptc['1']})", ptc['1'] is not None and abs(ptc['1'] - HARD_V) < 1e-3,
          str(ptc['1']))
    check(f"[{solver}] stiff circuit: ptcont changes the outcome vs plain Newton "
          f"(ptcont {ptc['1']} vs no-ptcont {nop['1']})",
          ptc['1'] is not None and (nop['1'] is None or abs(ptc['1'] - nop['1']) > 1e-2))

print(f"\n{'ALL PASS' if passed == checks else 'FAILURES'}: {passed}/{checks} passed")
sys.exit(0 if passed == checks else 1)
