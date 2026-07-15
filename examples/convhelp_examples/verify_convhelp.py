#!/usr/bin/env python3
"""
verify_convhelp.py -- Enhancement-204: auto-triggering DC convergence aids
(`.option convhelp`). End-to-end through the committed ngspice.

ngspice's operating-point solver already escalates automatically through gmin
stepping and source stepping, but the two strongest aids -- the globalized
damped-Newton line search (E-111) and pseudo-transient continuation (E-127) --
only fired if the user hand-set `.option linesearch` / `.option ptcont`, and
nothing reported which aid rescued a run.

`.option convhelp` makes the whole cascade an automatic ladder,

    Newton (+ line search) -> gmin step -> source step -> pseudo-transient -> optran

and prints a one-line note naming the aid that produced the operating point. It
is OFF by default (fully backward compatible) and is turned on by
`.option errpreset=conservative`.

Checked under BOTH linear solvers (KLU default + legacy Sparse 1.3):

  [1] `.option convhelp` is accepted (not an unknown option).
  [2] RESULT-NEUTRALITY: on a battery of normal nonlinear DC circuits the
      converged node voltages with convhelp ON are identical to a normal run --
      a convergence aid must never change the answer -- and no aid note is
      emitted (the plain Newton solve already converges).
  [3] AUTO-ESCALATION: on a deliberately stiff circuit (behavioral exponential,
      no junction limiting) where plain Newton overshoots to a spurious root,
      convhelp reaches the physically correct V(1) = 0.837922 V *without* the
      user setting `.option ptcont`, and reports "via pseudo-transient
      continuation". A plain run (no convhelp) lands somewhere else.
  [4] PRESET INTEGRATION: `.option errpreset=conservative` enables the same
      auto-escalation; an explicit `.option convhelp=0` still wins over it.
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

# normal circuits (converge with plain Newton) -> result-neutrality + silence
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
    deck = f"convhelp test\n{opts}\n{body}\n.op\n.control\nrun\nprint {' '.join('v('+n+')' for n in nodes)}\n.endc\n.end\n"
    p = os.path.join(HERE, "_tmp.cir")
    with open(p, "w") as f:
        f.write(deck)
    r = subprocess.run([NGSPICE, "-b", p], capture_output=True, text=True, timeout=90)
    os.remove(p)
    out = r.stdout + r.stderr
    vals = {n: (float(m.group(1)) if (m := re.search(rf"v\({n}\)\s*=\s*([\-0-9.eE+]+)", out)) else None)
            for n in nodes}
    unknown = "unknown option" in out.lower() or "unrecognized" in out.lower()
    aid = (m.group(1).strip() if (m := re.search(r"operating point reached via ([^\n.]+)", out)) else None)
    return vals, unknown, aid, out

def close(a, b):
    return a is not None and b is not None and abs(a - b) <= 1e-6 * (abs(a) + abs(b)) + 1e-12

print("Enhancement-204: auto-triggering DC convergence aids (.option convhelp)")

# [1] option accepted
_, unknown, _, _ = run(CIRCUITS["diode"][0], ["1"], ".option convhelp")
check("`.option convhelp` accepted (not an unknown option)", not unknown)

for solver, sopt in (("KLU", ""), ("SPARSE", ".option sparse\n")):
    # [2] result-neutrality + silence across the battery
    for name, (body, nodes) in CIRCUITS.items():
        off, _, _, _ = run(body, nodes, sopt.strip())
        on, _, aid, _ = run(body, nodes, sopt + ".option convhelp")
        conv = all(on[n] is not None for n in nodes)
        neutral = all(close(off[n], on[n]) for n in nodes)
        check(f"[{solver}] {name}: converges with convhelp ON", conv)
        check(f"[{solver}] {name}: result-neutral (ON == OFF)", neutral,
              ", ".join(f"{n}:{off[n]}!={on[n]}" for n in nodes))
        check(f"[{solver}] {name}: silent -- no aid note when plain Newton converges",
              aid is None, f"unexpected aid '{aid}'")

    # [3] auto-escalation on the stiff circuit -- ptcont fires WITHOUT .option ptcont
    ch, _, aid, _ = run(HARD, ["1"], sopt + ".option convhelp gminsteps=0 srcsteps=0")
    plain, _, _, _ = run(HARD, ["1"], sopt + ".option gminsteps=0 srcsteps=0")
    check(f"[{solver}] stiff: convhelp reaches the correct DC V(1)={HARD_V:.6f} "
          f"(got {ch['1']})", ch['1'] is not None and abs(ch['1'] - HARD_V) < 1e-3,
          str(ch['1']))
    check(f"[{solver}] stiff: convhelp auto-fired pseudo-transient continuation "
          f"(reported '{aid}'), no explicit .option ptcont",
          aid is not None and "pseudo-transient" in aid, f"aid='{aid}'")
    check(f"[{solver}] stiff: convhelp changes the outcome vs plain Newton "
          f"(convhelp {ch['1']} vs plain {plain['1']})",
          ch['1'] is not None and (plain['1'] is None or abs(ch['1'] - plain['1']) > 1e-2))

    # [4] preset integration + explicit override
    cons, _, aid_c, _ = run(HARD, ["1"], sopt + ".option errpreset=conservative gminsteps=0 srcsteps=0")
    check(f"[{solver}] errpreset=conservative enables the auto-ladder "
          f"(V(1)={cons['1']}, via '{aid_c}')",
          cons['1'] is not None and abs(cons['1'] - HARD_V) < 1e-2 and aid_c is not None,
          f"V={cons['1']} aid={aid_c}")
    ovr, _, aid_o, _ = run(HARD, ["1"], sopt + ".option errpreset=conservative convhelp=0 gminsteps=0 srcsteps=0")
    check(f"[{solver}] explicit `.option convhelp=0` overrides errpreset=conservative "
          f"(no auto-ladder note)", aid_o is None, f"unexpected aid '{aid_o}'")

print(f"\n{'ALL PASS' if passed == checks else 'FAILURES'}: {passed}/{checks} passed")
sys.exit(0 if passed == checks else 1)
