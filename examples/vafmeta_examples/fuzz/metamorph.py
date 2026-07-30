#!/usr/bin/env python3
"""Metamorphic (equivalence) fuzzing of openvaf-r -- a WRONG-CODE oracle.

Why this axis. openvaf-r's crash surface is well covered: the assertion-replay
audit closed at 496 assertions clean, round 7 fixed all 9 of its findings, and
four crash-hardening rounds preceded it. What a crash fuzzer cannot see is
MISCOMPILATION -- code that compiles, runs, and returns the wrong number.

The oracle here needs no reference implementation. For each pair of Verilog-A
bodies that are SEMANTICALLY IDENTICAL but written differently, the compiled
models must produce bit-comparable results in the same circuit. Any difference is
a compiler bug on one side of the pair, with no judgement call about which value
is "right" -- they must simply agree.

Pairs exercise the places a compiler is most likely to diverge: algebraic
rearrangement, strength reduction (`x**2` vs `x*x`), control-flow lowering
(if/else vs ternary vs a loop), $limit/ddt/idt placement, and the autodiff path
(each body is differentiated for the Jacobian, so a derivative bug shows up as a
DC/AC mismatch even when the residual agrees).

TRAPS respected, from earlier campaigns:
  * RAYON_NUM_THREADS=1 -- otherwise panic sites are nondeterministic.
  * a per-job TMPDIR -- parallel compiles otherwise collide.
  * compare the SIMULATED result, not the MIR: MIR-level equality is not the
    property that matters and has misled before.
"""
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
NG = os.environ.get("NGSPICE_BIN", os.path.join(REPO, "ngspice-46/build/src/ngspice"))


def find_vaf():
    for sub in ("macos/apple-silicon", "macos/intel", "linux/intel", "linux/arm"):
        p = os.path.join(REPO, "bin", sub, "openvaf-r")
        if os.path.exists(p):
            return p
    return None


VAF = os.environ.get("OPENVAF_BIN") or find_vaf()

# (label, body_A, body_B) -- A and B must be mathematically identical.
# `p` and `n` are the terminals; `k1`,`k2` are model parameters.
PAIRS = [
    ("distributivity",
     "I(p,n) <+ k1*V(p,n) + k2*V(p,n);",
     "I(p,n) <+ (k1+k2)*V(p,n);"),
    ("pow vs repeated mul",
     # the linear k2 term is in BOTH sides: a pure square law has zero
     # conductance at V=0 and the DC sweep through zero cannot converge, which
     # showed up as "len 0 vs 0" rather than as a compiler problem
     "I(p,n) <+ k2*V(p,n) + k1*pow(V(p,n),2.0);",
     "I(p,n) <+ k2*V(p,n) + k1*V(p,n)*V(p,n);"),
    ("pow 3 vs mul chain",
     "I(p,n) <+ k1*pow(V(p,n),3.0);",
     "I(p,n) <+ k1*V(p,n)*V(p,n)*V(p,n);"),
    ("ternary vs if/else",
     "I(p,n) <+ (V(p,n) > 0) ? k1*V(p,n) : k2*V(p,n);",
     "if (V(p,n) > 0) I(p,n) <+ k1*V(p,n); else I(p,n) <+ k2*V(p,n);"),
    ("temp var vs inline",
     "begin : b1 real t; t = k1*V(p,n); I(p,n) <+ t + k2*t; end",
     "I(p,n) <+ k1*V(p,n)*(1.0+k2);"),
    ("exp identity exp(a+b)",
     "I(p,n) <+ k1*(exp(V(p,n)/0.05 + k2) - 1.0);",
     "I(p,n) <+ k1*(exp(V(p,n)/0.05)*exp(k2) - 1.0);"),
    ("sqrt vs pow 0.5",
     "I(p,n) <+ k1*sqrt(abs(V(p,n)) + 1.0);",
     "I(p,n) <+ k1*pow(abs(V(p,n)) + 1.0, 0.5);"),
    ("loop-accumulated vs closed form",
     "begin : b2 integer i; real s; s = 0.0; for (i=0;i<4;i=i+1) s = s + k1*V(p,n); "
     "I(p,n) <+ s; end",
     "I(p,n) <+ 4.0*k1*V(p,n);"),
    ("while vs closed form",
     "begin : b3 integer i; real s; s = 0.0; i = 0; while (i < 3) begin "
     "s = s + k1*V(p,n); i = i + 1; end I(p,n) <+ s; end",
     "I(p,n) <+ 3.0*k1*V(p,n);"),
    ("ddt linearity",
     "I(p,n) <+ ddt(k1*V(p,n)) + ddt(k2*V(p,n));",
     "I(p,n) <+ ddt((k1+k2)*V(p,n));"),
    ("tanh vs exp form",
     "I(p,n) <+ k1*tanh(V(p,n));",
     "I(p,n) <+ k1*(exp(2.0*V(p,n))-1.0)/(exp(2.0*V(p,n))+1.0);"),
    ("negate twice",
     "I(p,n) <+ -(-(k1*V(p,n)));",
     "I(p,n) <+ k1*V(p,n);"),
    ("hypot vs sqrt of squares",
     "I(p,n) <+ k1*hypot(V(p,n), k2);",
     "I(p,n) <+ k1*sqrt(V(p,n)*V(p,n) + k2*k2);"),
    ("nested conditional flattened",
     "I(p,n) <+ (V(p,n) > 0) ? ((V(p,n) > 1) ? k1 : k2) : k2;",
     "I(p,n) <+ (V(p,n) > 1) ? k1 : k2;"),
    ("division vs reciprocal mul",
     "I(p,n) <+ V(p,n)/(1.0/k1);",
     "I(p,n) <+ k1*V(p,n);"),
]

# ---------------------------------------------------------------------------
# GENERATIVE pair-builder. The 15 curated pairs above cover the transformations
# a compiler is most likely to get wrong; this builds arbitrarily many more by
# generating a random expression and then applying a SEMANTICS-PRESERVING
# rewrite to produce its partner. Any numeric difference is a miscompilation on
# one side, with no need to know which value is "correct".
#
# Every generated model keeps a linear `k2*V(p,n)` term so the DC sweep through
# V = 0 stays solvable -- a pure square law has zero conductance at zero bias and
# simply fails to converge, which reads as a harness failure rather than a
# compiler one.
import random

ATOMS = ["V(p,n)", "k1", "k2", "1.5", "V(p,n)*k1"]
UNARY = ["abs(%s)", "sqrt(abs(%s)+1.0)", "exp(%s/10.0)", "tanh(%s)", "(-(%s))"]


def gen_expr(rng, depth=0):
    if depth >= 2 or rng.random() < 0.35:
        return rng.choice(ATOMS)
    r = rng.random()
    if r < 0.30:
        return "(%s %s %s)" % (gen_expr(rng, depth + 1), rng.choice("+-*"),
                               gen_expr(rng, depth + 1))
    if r < 0.55:
        return rng.choice(UNARY) % gen_expr(rng, depth + 1)
    if r < 0.75:
        return "pow(abs(%s)+1.0,2.0)" % gen_expr(rng, depth + 1)
    return "((%s > 0) ? %s : %s)" % (gen_expr(rng, depth + 1),
                                     gen_expr(rng, depth + 1),
                                     gen_expr(rng, depth + 1))


# each rewrite maps an expression to a mathematically identical one
REWRITES = [
    ("double negation",      lambda e: "(-(-(%s)))" % e),
    ("multiply by one",      lambda e: "((%s)*1.0)" % e),
    ("add then subtract",    lambda e: "(((%s)+3.25)-3.25)" % e),
    ("divide by reciprocal", lambda e: "((%s)/(1.0/4.0)/4.0)" % e),
    ("pow(x,1)",             lambda e: "pow((%s),1.0)" % e),
    ("temp var in a block",  None),          # handled structurally below
    ("ternary on a truth",   lambda e: "((1 > 0) ? (%s) : 0.0)" % e),
]


def gen_pair(rng, i):
    e = gen_expr(rng)
    name, fn = rng.choice(REWRITES)
    body_a = "I(p,n) <+ k2*V(p,n) + (%s);" % e
    if fn is None:
        body_b = ("begin : g%d real t; t = %s; I(p,n) <+ k2*V(p,n) + t; end" % (i, e))
    else:
        body_b = "I(p,n) <+ k2*V(p,n) + (%s);" % fn(e)
    return ("gen[%s]" % name, body_a, body_b)


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

# 3-TERMINAL pairs. A multi-terminal model exercises things a one-port cannot:
# KVL between branch probes, contributions to several branches, and the Jacobian
# gaining off-diagonal entries (so an autodiff bug that cancels on a one-port
# shows up here).
PAIRS3 = [
    ("3t KVL: V(d,sx) == V(d,g)+V(g,sx)",
     "I(d,sx) <+ k1*V(d,sx); I(g,sx) <+ k2*V(g,sx);",
     "I(d,sx) <+ k1*(V(d,g)+V(g,sx)); I(g,sx) <+ k2*V(g,sx);"),
    ("3t two contributions vs one",
     "I(d,sx) <+ k1*V(d,sx); I(d,sx) <+ k2*V(d,sx); I(g,sx) <+ k2*V(g,sx);",
     "I(d,sx) <+ (k1+k2)*V(d,sx); I(g,sx) <+ k2*V(g,sx);"),
    ("3t transconductance via g node",
     "I(d,sx) <+ k1*V(g,sx) + k2*V(d,sx); I(g,sx) <+ k2*V(g,sx);",
     "I(d,sx) <+ k2*V(d,sx) + k1*V(g,sx); I(g,sx) <+ k2*V(g,sx);"),
    ("3t antisymmetry I(sx,d) == -I(d,sx)",
     "I(d,sx) <+ k1*V(d,sx); I(g,sx) <+ k2*V(g,sx);",
     "I(sx,d) <+ -(k1*V(d,sx)); I(g,sx) <+ k2*V(g,sx);"),
    # $limit only changes the NEWTON PATH; the converged fixed point must be
    # identical. That is the metamorphic property, and it is the whole point of a
    # limiting function -- if it moved the solution it would be a bug by
    # definition. Compared against the same model with no limiting at all.
    ("3t $limit must not move the solution",
     "begin : lm real vd; vd = $limit(V(d,sx), \"pnjlim\", 0.025, 0.6); "
     "I(d,sx) <+ 1e-14*(exp(vd/0.025)-1.0); I(g,sx) <+ k2*V(g,sx); end",
     "I(d,sx) <+ 1e-14*(exp(V(d,sx)/0.025)-1.0); I(g,sx) <+ k2*V(g,sx);"),
]

TMPL = """`include "disciplines.vams"
module dut(p, n);
  inout p, n;
  electrical p, n;
  parameter real k1 = 1e-3 from (0:inf);
  parameter real k2 = 2e-3 from (0:inf);
  analog begin
    %s
  end
endmodule
"""


def compile_va(body, tag, three=False):
    d = os.path.join(HERE, "j_%s" % tag)
    os.makedirs(d, exist_ok=True)
    src = os.path.join(d, "dut.va")
    open(src, "w").write((TMPL3 if three else TMPL) % body)
    env = dict(os.environ, RAYON_NUM_THREADS="1", TMPDIR=d)
    r = subprocess.run([VAF, "dut.va", "-o", "dut.osdi"], cwd=d, env=env,
                       capture_output=True, text=True, timeout=900, errors="replace")
    if r.returncode != 0:
        return None, (r.stdout + r.stderr)[:200]
    return os.path.join(d, "dut.osdi"), ""


def simulate3(osdi, tag):
    """3-terminal deck: sweep the d-side and hold a gate bias, so both the
    diagonal and the off-diagonal Jacobian entries are exercised."""
    p = os.path.join(HERE, "s_%s.cir" % tag)
    open(p, "w").write(
        "meta3\nV1 in 0 dc 0.5 ac 1\nVg gg 0 dc 0.3\nRs in a 1k\nRg gg g 1k\n"
        "N1 a g 0 dut\n.model dut dut()\n"
        ".control\noption noacct\nset numdgt=17\npre_osdi %s\n"
        "dc V1 -0.5 0.5 0.25\nprint v(a)\nac lin 3 1e3 1e6\nprint vdb(a)\n"
        ".endc\n.end\n" % osdi)
    r = subprocess.run([NG, "-b", os.path.basename(p)], cwd=HERE, capture_output=True,
                       text=True, timeout=600, errors="replace")
    return [float(m.group(1)) for m in re.finditer(
        r"^\s*\d+\s+[-+0-9.eE]+\s+([-+0-9.eE]+)\s*$", r.stdout + r.stderr, re.M)]


def simulate(osdi, tag):
    """Same circuit for both sides: a DC sweep plus an AC point (AC exercises the
    autodiff-produced Jacobian, so a derivative-only bug still shows up)."""
    p = os.path.join(HERE, "s_%s.cir" % tag)
    open(p, "w").write(
        "meta\nV1 in 0 dc 0.5 ac 1\nRs in a 1k\nN1 a 0 dut\n.model dut dut()\n"
        ".control\noption noacct\nset numdgt=17\n"
        "pre_osdi %s\n"
        "dc V1 -1 1 0.25\nprint v(a)\n"
        "ac lin 3 1e3 1e6\nprint vdb(a)\n"
        ".endc\n.end\n" % osdi)
    r = subprocess.run([NG, "-b", os.path.basename(p)], cwd=HERE, capture_output=True,
                       text=True, timeout=600, errors="replace")
    out = r.stdout + r.stderr
    vals = [float(m.group(1)) for m in
            re.finditer(r"^\s*\d+\s+[-+0-9.eE]+\s+([-+0-9.eE]+)\s*$", out, re.M)]
    return vals


def main():
    if not VAF or not os.path.exists(VAF):
        print("set OPENVAF_BIN"); return 2
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--gen", type=int, default=0, help="generated pairs to add")
    ap.add_argument("--seed", type=int, default=1)
    a = ap.parse_args()
    pairs = [(l, x, y, False) for (l, x, y) in PAIRS] + \
            [(l, x, y, True) for (l, x, y) in PAIRS3]
    if a.gen:
        rng = random.Random(a.seed)
        pairs += [gen_pair(rng, i) + (False,) for i in range(a.gen)]
    print("  %-34s %-8s %s" % ("metamorphic pair", "verdict", "detail"))
    print("  " + "-" * 92)
    bad = compiled = 0
    for i, (label, a, b, three) in enumerate(pairs):
        oa, ea = compile_va(a, "a%d" % i, three)
        ob, eb = compile_va(b, "b%d" % i, three)
        if not oa or not ob:
            print("  %-34s %-8s A:%s B:%s" % (label, "NOCOMP", ea[:28], eb[:28]))
            continue
        sf = simulate3 if three else simulate
        va, vb = sf(oa, "a%d" % i), sf(ob, "b%d" % i)
        if not va or not vb or len(va) != len(vb):
            print("  %-34s %-8s len %d vs %d" % (label, "NODATA", len(va), len(vb)))
            continue
        compiled += 1
        # rel error with an ABSOLUTE floor: the sweep crosses V1 = 0, where the
        # answer is zero and a purely relative metric divides noise by noise.
        # That produced a fake 2.12e-07 "mismatch" on the tanh pair, whose two
        # sides in fact agreed to 2e-16 ABSOLUTE (-9.28385590e-11 vs -9.28385394e-11).
        ATOL, RTOL = 1e-12, 1e-9
        worst = max(abs(x - y) for x, y in zip(va, vb))
        okk = all(abs(x - y) <= ATOL + RTOL * max(abs(x), abs(y))
                  for x, y in zip(va, vb))
        bad += not okk
        print("  %-34s %-8s max rel dev %.2e over %d points"
              % (label, "PASS" if okk else "MISMATCH", worst, len(va)))

    print("\n  %d pairs compared, %d MISMATCH" % (compiled, bad))
    if compiled < len(pairs) // 2:
        print("  *** SUSPECT: fewer than half the pairs compiled+ran; the harness, "
              "not the compiler, is probably at fault ***")
        return 2
    return 1 if bad else 0


sys.exit(main())
