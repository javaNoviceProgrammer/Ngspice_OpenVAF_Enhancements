#!/usr/bin/env python3
"""`hbosc` (autonomous harmonic balance) against a closed-form LC oracle.

Added by the command-set correctness campaign, which found `hbosc` to be the one
command with no numeric oracle anywhere in the suite: it ran and converged, but
nothing pinned its output against an independent reference.

THE CIRCUIT is a van der Pol LC oscillator -- a lossy tank plus a cubic
negative-resistance element:

    L1 a 0 1u                        f_osc = 1/(2*pi*sqrt(L*C))
    C1 a 0 1n                              = 5.0329212 MHz
    R1 a 0 100k                      (Q = R*sqrt(C/L) ~ 3162, so the damped
    B1 a 0 i = -(g*v(a)) + k*v(a)^3   resonance is shifted by 1/(4Q^2) ~ 2.5e-8
                                      -- negligible, hence the tight tolerance)

TWO INDEPENDENT ORACLES, because either alone can be satisfied by a wrong answer:

  [1] FREQUENCY vs the closed form 1/(2*pi*sqrt(L*C)).
  [2] AMPLITUDE vs a settled TRANSIENT of the same circuit. That is a different
      code path entirely, and it is what makes the frequency check meaningful.

WHY [2] IS NOT OPTIONAL -- the trap this example exists to guard.

Autonomous harmonic balance ALWAYS admits the zero solution, so a tiny residual
proves nothing about whether an oscillator was found. With a weak negative
resistance (2e-5 S against 1e-5 S of loss) `hbosc` reported:

    oscillation frequency f0 = 5022468.58 Hz  (converged, |F| = 1.178e-15)
    a    1    5.022469e+06    1.667923e-15

A confident "converged", an excellent residual, and a frequency only 0.21% off --
entirely plausible in isolation. But |V| = 1.7e-15 V: it had converged to the
TRIVIAL DEAD SOLUTION, and the reported frequency was just the linear tank
resonance, not a limit cycle. A frequency-only check at 1% tolerance would have
recorded a pass.

And it is worse than "the circuit did not oscillate". Re-running these checks with
that weak negative resistance shows the TRANSIENT reaching a real 0.164 V limit
cycle while hbosc still returns |V1| = 6.7e-14 -- so hbosc can miss a limit cycle
that demonstrably exists. That is why check [3] is asserted separately from [2]
rather than folded into it.

So the negative resistance here is deliberately strong (5e-4 S, 50x the loss),
and the amplitude is asserted to be a real volt-scale limit cycle.

ARGUMENT ORDER: `hbosc <oscnode> <K> [fguess] [tstab]` -- the NODE comes first.
"""
import math
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from _setup import NG as NGSPICE  # noqa: E402

L, C = 1e-6, 1e-9
F0 = 1.0 / (2 * math.pi * math.sqrt(L * C))      # 5.0329212 MHz

checks = passed = 0


def check(label, ok, detail=""):
    global checks, passed
    checks += 1
    passed += bool(ok)
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  [{detail}]" if detail else ""))


NET = ("lc oscillator\n"
       "L1 a 0 %g\nC1 a 0 %g\nR1 a 0 100k\n"
       "B1 a 0 i = -(5e-4*v(a)) + 5e-4*v(a)*v(a)*v(a)\n"
       ".ic v(a)=0.1\n" % (L, C))


def run(body, tag, timeout=600):
    p = os.path.join(HERE, "_hb_%s.cir" % tag)
    with open(p, "w") as f:
        f.write(NET + ".control\noption noacct\nset numdgt=17\n" + body + "\n.endc\n.end\n")
    r = subprocess.run([NGSPICE, "-b", os.path.basename(p)], cwd=HERE,
                       capture_output=True, text=True, timeout=timeout, errors="replace")
    return r.stdout + r.stderr


def main():
    # ---- reference: a settled transient gives the true limit-cycle amplitude --
    out = run("tran 1n 100u uic\n"
              "let amp = (maximum(v(a))-minimum(v(a)))/2\nprint amp\n", "tr")
    m = re.search(r"^amp\s*=\s*([-+0-9.eE]+)", out, re.M)
    tr_amp = float(m.group(1)) if m else None
    check("transient reference: the oscillator actually starts",
          tr_amp is not None and tr_amp > 0.1,
          "limit-cycle amplitude %.6f V" % tr_amp if tr_amp else "no amplitude")

    # ---- hbosc ---------------------------------------------------------------
    out = run("hbosc a 5 5e6 100u\n", "hb")
    mf = re.search(r"oscillation frequency f0\s*=\s*([-+0-9.eE]+)", out)
    f_hb = float(mf.group(1)) if mf else None
    # the fundamental row: "a    1    <freq>    <|V|>    <phase>"
    ma = re.search(r"^\s*a\s+1\s+[-+0-9.eE]+\s+([-+0-9.eE]+)", out, re.M)
    a_hb = float(ma.group(1)) if ma else None

    check("hbosc converges and reports an oscillation frequency",
          f_hb is not None, "f0 = %s Hz" % (("%.2f" % f_hb) if f_hb else "none"))

    # [1] frequency vs the closed form
    if f_hb is None:
        check("hbosc f0 == 1/(2*pi*sqrt(L*C))", False, "no frequency")
    else:
        dev = abs(f_hb - F0) / F0
        check("hbosc f0 == 1/(2*pi*sqrt(L*C))", dev < 1e-3,
              "%.2f vs %.2f Hz, dev %.2e" % (f_hb, F0, dev))

    # [2] amplitude vs the transient -- THE check that rules out the dead solution
    if a_hb is None or tr_amp is None:
        check("hbosc fundamental amplitude == transient limit cycle", False,
              "hbosc=%s transient=%s" % (a_hb, tr_amp))
    else:
        dev = abs(a_hb - tr_amp) / tr_amp
        check("hbosc fundamental amplitude == transient limit cycle", dev < 5e-2,
              "%.6f vs %.6f V, dev %.2e" % (a_hb, tr_amp, dev))

    # [3] and explicitly: NOT the trivial solution. Stated separately from [2]
    #     because this is the failure mode a frequency-only test cannot see.
    check("hbosc did not converge to the trivial zero solution",
          a_hb is not None and a_hb > 0.1,
          "|V1| = %.4g V (a dead solution reports ~1e-15)" % a_hb if a_hb else "none")

    for j in os.listdir(HERE):
        if j.startswith("_hb_"):
            os.remove(os.path.join(HERE, j))
    print(f"\n{'ALL PASS' if passed == checks else 'FAILURES'}: {passed}/{checks} passed")
    sys.exit(0 if passed == checks else 1)


main()
