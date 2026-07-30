#!/usr/bin/env python3
"""Metamorphic equivalence check for openvaf-r -- a WRONG-CODE oracle.

openvaf-r's CRASH surface is well covered: the assertion-replay audit closed at
496 assertions clean, round 7 fixed all nine of its findings, and four
crash-hardening rounds preceded it. What none of those can see is
MISCOMPILATION -- code that compiles, runs, and returns the wrong number.

THE ORACLE NEEDS NO REFERENCE IMPLEMENTATION. For a pair of Verilog-A bodies that
are semantically identical but written differently, the two compiled models must
produce the same numbers in the same circuit. A difference is a compiler bug on
one side, with no judgement about which value is "right" -- they must agree.

This file is the fast subset kept in the regression. The full 15 curated pairs
plus a GENERATIVE pair-builder (random expression, then a semantics-preserving
rewrite to make its partner) live in `fuzz/metamorph.py`, which is not part of
the sweep:

    python3 fuzz/metamorph.py --gen 40 --seed 7

Each pair below is chosen to force a different lowering:
  * a 3-TERMINAL KVL identity                   -- off-diagonal Jacobian entries
  * `$limit` present vs absent                   -- see below
  * `for`-loop accumulation vs its closed form  -- unrolling / loop lowering
  * named-block temp var vs an inline expression -- variable lowering
  * `pow(x,3)` vs a multiply chain               -- strength reduction
  * ddt linearity                                -- the reactive path

THE `$limit` PAIR IS THE SUBTLE ONE. A limiting function exists to change the
NEWTON PATH; it must not change the fixed point the iteration converges to. So a
model using `$limit` and the same model with no limiting at all must agree on the
converged solution -- if they did not, the limiter would be altering the answer,
which is a bug by definition. Measured agreement: 1.07e-12.

THE AC SWEEP MATTERS AS MUCH AS THE DC ONE: each body is differentiated to build
the Jacobian, so a derivative-only bug shows up in AC even when the residual
agrees.

TWO HARNESS TRAPS, recorded because both produced misleading results first time:
  * A purely RELATIVE tolerance is meaningless where the answer is zero. The DC
    sweep crosses V = 0; two sides differing by 1.96e-17 there were reported as a
    1.96e-08 "mismatch" because the metric divided by 9.3e-11 of noise. The
    criterion is |dx| <= atol + rtol*max(|x|,|y|).
  * A PURE square law has zero conductance at zero bias, so a DC sweep through
    zero cannot converge -- it looked like a compile failure. Every body keeps a
    linear `k2*V(p,n)` term, which leaves the equivalence untouched.
"""
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from _setup import NG as NGSPICE, VAF as OPENVAF  # noqa: E402

checks = passed = 0

# (label, body_A, body_B) -- mathematically identical, deliberately different
PAIRS = [
    ("for-loop vs closed form",
     "begin : b1 integer i; real s; s = 0.0; for (i=0;i<4;i=i+1) s = s + k1*V(p,n); "
     "I(p,n) <+ k2*V(p,n) + s; end",
     "I(p,n) <+ k2*V(p,n) + 4.0*k1*V(p,n);"),
    ("named-block temp var vs inline",
     "begin : b2 real t; t = k1*V(p,n); I(p,n) <+ k2*V(p,n) + t + k1*t; end",
     "I(p,n) <+ k2*V(p,n) + k1*V(p,n)*(1.0+k1);"),
    ("pow(x,3) vs multiply chain",
     "I(p,n) <+ k2*V(p,n) + k1*pow(V(p,n),3.0);",
     "I(p,n) <+ k2*V(p,n) + k1*V(p,n)*V(p,n)*V(p,n);"),
    ("ddt linearity",
     "I(p,n) <+ k2*V(p,n) + ddt(1e-9*V(p,n)) + ddt(2e-9*V(p,n));",
     "I(p,n) <+ k2*V(p,n) + ddt(3e-9*V(p,n));"),
]

PAIRS3 = [
    ("3t KVL: V(d,sx) == V(d,g)+V(g,sx)",
     "I(d,sx) <+ k1*V(d,sx); I(g,sx) <+ k2*V(g,sx);",
     "I(d,sx) <+ k1*(V(d,g)+V(g,sx)); I(g,sx) <+ k2*V(g,sx);"),
    ("$limit does not move the solution",
     "begin : lm real vd; vd = $limit(V(d,sx), \"pnjlim\", 0.025, 0.6); "
     "I(d,sx) <+ 1e-14*(exp(vd/0.025)-1.0); I(g,sx) <+ k2*V(g,sx); end",
     "I(d,sx) <+ 1e-14*(exp(V(d,sx)/0.025)-1.0); I(g,sx) <+ k2*V(g,sx);"),
]

TMPL3 = """`include "disciplines.vams"
module dut(d, g, sx);
  inout d, g, sx;
  electrical d, g, sx;
  parameter real k1 = 1e-3 from (0:inf);
  parameter real k2 = 1e-3 from (0:inf);
  analog begin
    %s
  end
endmodule
"""

TMPL = """`include "disciplines.vams"
module dut(p, n);
  inout p, n;
  electrical p, n;
  parameter real k1 = 1e-3 from (0:inf);
  parameter real k2 = 1e-3 from (0:inf);
  analog begin
    %s
  end
endmodule
"""


def check(label, ok, detail=""):
    global checks, passed
    checks += 1
    passed += bool(ok)
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  [{detail}]" if detail else ""))


def build(body, tag, three=False):
    d = os.path.join(HERE, "_vm_%s" % tag)
    os.makedirs(d, exist_ok=True)
    open(os.path.join(d, "dut.va"), "w").write((TMPL3 if three else TMPL) % body)
    # RAYON_NUM_THREADS=1 keeps panic sites deterministic; a per-job TMPDIR stops
    # parallel compiles colliding. Both learned from earlier openvaf campaigns.
    env = dict(os.environ, RAYON_NUM_THREADS="1", TMPDIR=d)
    r = subprocess.run([OPENVAF, "dut.va", "-o", "dut.osdi"], cwd=d, env=env,
                       capture_output=True, text=True, timeout=900, errors="replace")
    return (os.path.join(d, "dut.osdi") if r.returncode == 0 else None)


def sim3(osdi, tag):
    """3-terminal deck: sweep the d-side with a held gate bias, so the Jacobian
    gains off-diagonal entries an autodiff bug could cancel on a one-port."""
    p = os.path.join(HERE, "_vm_%s.cir" % tag)
    open(p, "w").write(
        "meta3\nV1 in 0 dc 0.5 ac 1\nVg gg 0 dc 0.3\nRs in a 1k\nRg gg g 1k\n"
        "N1 a g 0 dut\n.model dut dut()\n"
        ".control\noption noacct\nset numdgt=17\npre_osdi %s\n"
        "dc V1 -0.5 0.5 0.25\nprint v(a)\nac lin 3 1e3 1e6\nprint vdb(a)\n"
        ".endc\n.end\n" % osdi)
    r = subprocess.run([NGSPICE, "-b", os.path.basename(p)], cwd=HERE,
                       capture_output=True, text=True, timeout=600, errors="replace")
    return [float(m.group(1)) for m in re.finditer(
        r"^\s*\d+\s+[-+0-9.eE]+\s+([-+0-9.eE]+)\s*$", r.stdout + r.stderr, re.M)]


def sim(osdi, tag):
    p = os.path.join(HERE, "_vm_%s.cir" % tag)
    open(p, "w").write(
        "meta\nV1 in 0 dc 0.5 ac 1\nRs in a 1k\nN1 a 0 dut\n.model dut dut()\n"
        ".control\noption noacct\nset numdgt=17\npre_osdi %s\n"
        "dc V1 -1 1 0.5\nprint v(a)\nac lin 3 1e3 1e6\nprint vdb(a)\n"
        ".endc\n.end\n" % osdi)
    r = subprocess.run([NGSPICE, "-b", os.path.basename(p)], cwd=HERE,
                       capture_output=True, text=True, timeout=600, errors="replace")
    return [float(m.group(1)) for m in re.finditer(
        r"^\s*\d+\s+[-+0-9.eE]+\s+([-+0-9.eE]+)\s*$", r.stdout + r.stderr, re.M)]


def main():
    ATOL, RTOL = 1e-12, 1e-9
    allp = [(l, x, y, False) for (l, x, y) in PAIRS] + \
           [(l, x, y, True) for (l, x, y) in PAIRS3]
    for i, (label, a, b, three) in enumerate(allp):
        oa, ob = build(a, "a%d" % i, three), build(b, "b%d" % i, three)
        if not (oa and ob):
            check(label, False, "a model failed to compile")
            continue
        sf = sim3 if three else sim
        va, vb = sf(oa, "a%d" % i), sf(ob, "b%d" % i)
        if not va or len(va) != len(vb):
            check(label, False, "no data (%d vs %d points)" % (len(va), len(vb)))
            continue
        worst = max(abs(x - y) for x, y in zip(va, vb))
        ok = all(abs(x - y) <= ATOL + RTOL * max(abs(x), abs(y))
                 for x, y in zip(va, vb))
        check(label, ok, "max abs dev %.2e over %d points (dc+ac)" % (worst, len(va)))

    import shutil
    for j in os.listdir(HERE):
        q = os.path.join(HERE, j)
        if j.startswith("_vm_"):
            shutil.rmtree(q, ignore_errors=True) if os.path.isdir(q) else os.remove(q)
    print(f"\n{'ALL PASS' if passed == checks else 'FAILURES'}: {passed}/{checks} passed")
    sys.exit(0 if passed == checks else 1)


main()
