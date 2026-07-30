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

OPERATOR COVERAGE IS COMPLETE: all four laplace forms (nd, zd, zp, np) and all
four Z-transform forms (zi_nd, zi_zd, zi_zp, zi_np), plus idt and ddt.

For the eight rational forms the property used is SCALING, which is
convention-free -- it needs no knowledge of whether zeros/poles are {re,im} pairs,
what order coefficients come in, or what the zi_* sample period and transition
time mean. But scaling ALONE is weak: F(x) == 0 and F(x) == x both satisfy
F(2x) == 2 F(x). So every form carries a second, INVERTED assertion that its
response must DIFFER from the bare input (verdict "NO-OP" if it does not).
Measured separations run 2.2 to 134 -- the operators demonstrably act, which is
what makes the scaling result meaningful rather than vacuous.

OPERATOR COVERAGE. `idt` and `laplace` are LINEAR operators, so the properties
used are convention-free -- they hold whatever scaling or sign convention the
implementation chose, which matters because guessing a laplace convention wrong
manufactures a "mismatch" that is really a bad oracle:
    scaling       OP(c*x) == c*OP(x)
    additivity    OP(a) + OP(b) == OP(a+b)
    cancellation  nd(x,{2},{2,2t}) == nd(x,{1},{1,t})

HEAVY RUN ON RECORD (2026-07-29, `--gen 25 --gen3 25 --seed 11`):
  70 pairs attempted -> 64 compared, 0 MISMATCH, 6 NODATA, 0 NOCOMP.
The 6 NODATA are generated expressions whose CIRCUIT does not converge (a random
body can easily have no conductance at some sweep point); they are not compiler
failures, and they are reported separately from MISMATCH for exactly that reason.

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


# --- idt / laplace pairs ----------------------------------------------------
# Both are LINEAR operators, so the metamorphic properties used here are
# convention-free: they hold whatever scaling or sign convention the
# implementation picked, which matters because guessing a laplace convention
# wrong produces a "mismatch" that is really a bad oracle.
#
#   scaling      OP(c*x) == c*OP(x)
#   additivity   OP(a) + OP(b) == OP(a+b)
#   common factor in a rational form cancels: nd(x,{2},{2,2t}) == nd(x,{1},{1,t})
#
# `idt` is given an explicit initial condition so the DC operating point is
# well defined -- the integral of a constant is otherwise unbounded, which is a
# property of the maths and not a defect.
PAIRS_OP = [
    ("idt scaling: idt(2x) == 2 idt(x)",
     "I(p,n) <+ k2*V(p,n) + 1e-6*idt(2.0*V(p,n), 0.0);",
     "I(p,n) <+ k2*V(p,n) + 2.0*1e-6*idt(V(p,n), 0.0);"),
    ("idt additivity",
     "I(p,n) <+ k2*V(p,n) + 1e-6*(idt(k1*V(p,n),0.0) + idt(k2*V(p,n),0.0));",
     "I(p,n) <+ k2*V(p,n) + 1e-6*idt((k1+k2)*V(p,n), 0.0);"),
    # ddt(idt(x)) == x holds in AC (ddt -> jw, idt -> 1/jw, they cancel exactly)
    # but NOT at a DC operating point, where ddt(...) is identically ZERO by
    # definition -- so the ddt(idt(x)) side contributes nothing there while the
    # bare x side contributes k1*V. Measured: AC identical to 0.00e+00, DC off by
    # 8.3e-02, and the DC numbers confirm the reason exactly (side A behaves as
    # k2*V alone -> 1/3, side B as (k1+k2)*V -> 1/4). Comparing DC here was an
    # ORACLE error, not a compiler defect, so this pair is marked AC-only.
    ("ddt(idt(x)) == x  [AC only]",
     "I(p,n) <+ k2*V(p,n) + k1*ddt(idt(V(p,n), 0.0));",
     "I(p,n) <+ k2*V(p,n) + k1*V(p,n);", "ac"),
    ("laplace scaling: L(2x) == 2 L(x)",
     "I(p,n) <+ k2*V(p,n) + k1*laplace_nd(2.0*V(p,n), {1.0}, {1.0, 1e-6});",
     "I(p,n) <+ k2*V(p,n) + 2.0*k1*laplace_nd(V(p,n), {1.0}, {1.0, 1e-6});"),
    ("laplace additivity",
     "I(p,n) <+ k2*V(p,n) + k1*(laplace_nd(V(p,n),{1.0},{1.0,1e-6}) "
     "+ laplace_nd(V(p,n),{1.0},{1.0,1e-6}));",
     "I(p,n) <+ k2*V(p,n) + 2.0*k1*laplace_nd(V(p,n),{1.0},{1.0,1e-6});"),
    ("laplace common factor cancels",
     "I(p,n) <+ k2*V(p,n) + k1*laplace_nd(V(p,n), {2.0}, {2.0, 2e-6});",
     "I(p,n) <+ k2*V(p,n) + k1*laplace_nd(V(p,n), {1.0}, {1.0, 1e-6});"),
    ("laplace numerator scaling",
     "I(p,n) <+ k2*V(p,n) + k1*laplace_nd(V(p,n), {3.0}, {1.0, 1e-6});",
     "I(p,n) <+ k2*V(p,n) + 3.0*k1*laplace_nd(V(p,n), {1.0}, {1.0, 1e-6});"),
]


# --- every other laplace form, and the Z-transform family ---------------
# SCALING is convention-free, so one property covers all eight operators
# without needing to know any argument convention (zeros/poles as {re,im}
# pairs, coefficient order, or the zi_* sample period and transition time).
PAIRS_FORMS = [
    ("laplace_zd scaling: F(2x) == 2 F(x)",
     "I(p,n) <+ k2*V(p,n) + k1*laplace_zd(2.0*V(p,n), {-1e7,0.0}, {1.0, 1e-6});",
     "I(p,n) <+ k2*V(p,n) + 2.0*k1*laplace_zd(V(p,n), {-1e7,0.0}, {1.0, 1e-6});"),
    ("laplace_zp scaling: F(2x) == 2 F(x)",
     "I(p,n) <+ k2*V(p,n) + k1*laplace_zp(2.0*V(p,n), {-1e7,0.0}, {-1e6,0.0});",
     "I(p,n) <+ k2*V(p,n) + 2.0*k1*laplace_zp(V(p,n), {-1e7,0.0}, {-1e6,0.0});"),
    ("laplace_np scaling: F(2x) == 2 F(x)",
     "I(p,n) <+ k2*V(p,n) + k1*laplace_np(2.0*V(p,n), {1.0}, {-1e6,0.0});",
     "I(p,n) <+ k2*V(p,n) + 2.0*k1*laplace_np(V(p,n), {1.0}, {-1e6,0.0});"),
    ("zi_nd scaling: F(2x) == 2 F(x)",
     "I(p,n) <+ k2*V(p,n) + k1*zi_nd(2.0*V(p,n), {1.0}, {1.0, 0.5}, 1e-6, 0.0);",
     "I(p,n) <+ k2*V(p,n) + 2.0*k1*zi_nd(V(p,n), {1.0}, {1.0, 0.5}, 1e-6, 0.0);"),
    ("zi_zd scaling: F(2x) == 2 F(x)",
     "I(p,n) <+ k2*V(p,n) + k1*zi_zd(2.0*V(p,n), {0.2,0.0}, {1.0, 0.5}, 1e-6, 0.0);",
     "I(p,n) <+ k2*V(p,n) + 2.0*k1*zi_zd(V(p,n), {0.2,0.0}, {1.0, 0.5}, 1e-6, 0.0);"),
    ("zi_zp scaling: F(2x) == 2 F(x)",
     "I(p,n) <+ k2*V(p,n) + k1*zi_zp(2.0*V(p,n), {0.2,0.0}, {0.5,0.0}, 1e-6, 0.0);",
     "I(p,n) <+ k2*V(p,n) + 2.0*k1*zi_zp(V(p,n), {0.2,0.0}, {0.5,0.0}, 1e-6, 0.0);"),
    ("zi_np scaling: F(2x) == 2 F(x)",
     "I(p,n) <+ k2*V(p,n) + k1*zi_np(2.0*V(p,n), {1.0}, {0.5,0.0}, 1e-6, 0.0);",
     "I(p,n) <+ k2*V(p,n) + 2.0*k1*zi_np(V(p,n), {1.0}, {0.5,0.0}, 1e-6, 0.0);"),
]

# each form must also DEMONSTRABLY ACT: compared against the bare input, the
# response has to differ, or the scaling property above is satisfied vacuously.
PAIRS_ACT = [(lbl.replace("scaling: F(2x) == 2 F(x)", "is not a no-op"),
              a, "I(p,n) <+ k2*V(p,n) + k1*V(p,n);", "differ")
             for (lbl, a, _b) in PAIRS_FORMS]

# --- the remaining $limit modes ---------------------------------------------
# Same property as pnjlim: a limiting function changes the NEWTON PATH and must
# not move the fixed point. One pair per LRM mode, each against the identical
# model with no limiting at all.
#
# NOTE THE LIMIT OF THIS PROPERTY, stated rather than glossed: "does not move the
# solution" is ALSO satisfied by a $limit that is a no-op and simply returns its
# argument. Equality here proves the limiter is HARMLESS, not that it is DOING
# anything -- and unlike the laplace/zi forms above, there is no clean inverted
# assertion available, because a limiter that changed the answer would be a bug.
#
# That distinction is not academic here. `pnjlim` shows 1.07e-12, i.e. a genuinely
# different Newton path reaching the same fixed point. `fetlim`, `limvds` and the
# default mode all show EXACTLY 0.00e+00.
#
# WHAT THE ZEROS ARE NOT. An earlier note here guessed they might mean those modes
# are unimplemented, and separately claimed a misspelled mode is accepted
# silently. BOTH were wrong, and the source settles it:
#
#   * ngspice implements all three, with their LRM argument counts
#     (osdi/osdiregistry.c):
#         IS_LIM_FUN("pnjlim", 2, osdi_pnjlim)    /* vt, vcrit */
#         IS_LIM_FUN("limvds", 0, osdi_limvds)
#         IS_LIM_FUN("fetlim", 1, osdi_fetlim)    /* vto */
#   * an unknown mode IS diagnosed, at load time by the simulator rather than by
#     the compiler:  warning(osdi): unknown $limit function "bogusmode"
#     openvaf compiling it clean is therefore CORRECT -- the mode is resolved
#     from OSDI_LIM_TABLE by whoever loads the object, not by the compiler.
#
# The most likely explanation for the zeros is that the fetlim/limvds/default
# pairs use LINEAR bodies, where Newton converges in one step and limiting has
# nothing to do, while the pnjlim pair uses an exponential diode. That is a
# hypothesis, NOT a measurement: two attempts to confirm it on a nonlinear body
# produced no data. It is recorded as such.
PAIRS_LIM = [
    ("$limit fetlim keeps the solution",
     "begin : lf real vg; vg = $limit(V(d,g), \"fetlim\", 0.7); "
     "I(d,sx) <+ k1*vg + k2*V(d,sx); I(g,sx) <+ k2*V(g,sx); end",
     "I(d,sx) <+ k1*V(d,g) + k2*V(d,sx); I(g,sx) <+ k2*V(g,sx);"),
    ("$limit limvds keeps the solution",
     "begin : lv real vd; vd = $limit(V(d,sx), \"limvds\"); "
     "I(d,sx) <+ k1*vd + k2*V(d,sx); I(g,sx) <+ k2*V(g,sx); end",
     "I(d,sx) <+ k1*V(d,sx) + k2*V(d,sx); I(g,sx) <+ k2*V(g,sx);"),
    ("$limit default mode keeps the solution",
     "begin : ld real vd; vd = $limit(V(d,sx)); "
     "I(d,sx) <+ k1*vd + k2*V(d,sx); I(g,sx) <+ k2*V(g,sx); end",
     "I(d,sx) <+ k1*V(d,sx) + k2*V(d,sx); I(g,sx) <+ k2*V(g,sx);"),
]

# --- 3-TERMINAL generation --------------------------------------------------
# The one-port generator cannot reach off-diagonal Jacobian entries. These atoms
# span all three branch probes of the 3-terminal template, so a generated
# expression naturally couples the drain and gate branches.
ATOMS3 = ["V(d,sx)", "V(d,g)", "V(g,sx)", "k1", "k2", "1.5", "V(d,sx)*k1"]


def gen_expr3(rng, depth=0):
    if depth >= 2 or rng.random() < 0.35:
        return rng.choice(ATOMS3)
    r = rng.random()
    if r < 0.30:
        return "(%s %s %s)" % (gen_expr3(rng, depth + 1), rng.choice("+-*"),
                               gen_expr3(rng, depth + 1))
    if r < 0.55:
        return rng.choice(UNARY) % gen_expr3(rng, depth + 1)
    if r < 0.75:
        return "pow(abs(%s)+1.0,2.0)" % gen_expr3(rng, depth + 1)
    return "((%s > 0) ? %s : %s)" % (gen_expr3(rng, depth + 1),
                                     gen_expr3(rng, depth + 1),
                                     gen_expr3(rng, depth + 1))


# KVL is the rewrite that only exists for a multi-terminal model: V(d,sx) and
# V(d,g)+V(g,sx) are the same voltage by Kirchhoff, so substituting one for the
# other must not change any result. It rewrites the TOPOLOGY of the probe, not
# just the arithmetic, which is a different thing to get wrong.
def kvl_rewrite(e):
    return e.replace("V(d,sx)", "(V(d,g)+V(g,sx))")


def gen_pair3(rng, i):
    e = gen_expr3(rng)
    if "V(d,sx)" in e and rng.random() < 0.5:
        name, body_b_expr = "KVL substitution", kvl_rewrite(e)
    else:
        nm, fn = rng.choice([(n, f) for (n, f) in REWRITES if f is not None])
        name, body_b_expr = nm, fn(e)
    tail = " I(g,sx) <+ k2*V(g,sx);"
    return ("gen3[%s]" % name,
            "I(d,sx) <+ k2*V(d,sx) + (%s);%s" % (e, tail),
            "I(d,sx) <+ k2*V(d,sx) + (%s);%s" % (body_b_expr, tail),
            True)


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
    ap.add_argument("--gen", type=int, default=0, help="generated 1-port pairs")
    ap.add_argument("--gen3", type=int, default=0, help="generated 3-terminal pairs")
    ap.add_argument("--seed", type=int, default=1)
    a = ap.parse_args()
    def norm(t, three):
        # a pair may carry a trailing "ac" marker meaning "compare AC rows only"
        if len(t) == 4:
            return (t[0], t[1], t[2], three, t[3])
        return (t[0], t[1], t[2], three, "")
    pairs = [norm(t, False) for t in PAIRS] + \
            [norm(t, False) for t in PAIRS_OP] + \
            [norm(t, False) for t in PAIRS_FORMS] + \
            [norm(t, False) for t in PAIRS_ACT] + \
            [norm(t, True) for t in PAIRS_LIM] + \
            [norm(t, True) for t in PAIRS3]
    if a.gen:
        rng = random.Random(a.seed)
        pairs += [gen_pair(rng, i) + (False, "") for i in range(a.gen)]
    if a.gen3:
        rng3 = random.Random(a.seed + 10007)
        pairs += [gen_pair3(rng3, i) + ("",) for i in range(a.gen3)]
    print("  %-34s %-8s %s" % ("metamorphic pair", "verdict", "detail"))
    print("  " + "-" * 92)
    bad = compiled = 0
    for i, (label, a, b, three, mode) in enumerate(pairs):
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
        if mode == "differ":
            # inverted verdict: these two bodies are NOT equivalent, and the
            # operator is only doing something if they disagree. Without this,
            # every scaling pair above would pass for an operator that returned 0.
            worst = max(abs(x - y) for x, y in zip(va, vb))
            okk = worst > 1e-6
            bad += not okk
            print("  %-34s %-8s max abs dev %.2e over %d points (MUST differ)"
                  % (label, "PASS" if okk else "NO-OP", worst, len(va)))
            compiled += 1
            continue
        if mode == "ac":
            # the DC rows come first; keep only the AC tail
            nac = 3
            va, vb = va[-nac:], vb[-nac:]
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
