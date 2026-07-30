#!/usr/bin/env python3
"""A real generative grammar for metamorphic (wrong-code) fuzzing of openvaf-r.

`metamorph.py`'s built-in generator is a depth-2 expression tree over seven atoms
with a single rewrite applied -- a smoke test with a random number generator
attached, not a search. This is the actual generator:

  * STATEMENTS, not just expressions: nested if/else, for and while loops with
    bounded trip counts, named blocks with local declarations, and accumulator
    patterns. Control-flow lowering is where a compiler is most likely to diverge
    and the old generator never reached it.
  * DEPTH to order 4-5 rather than 2, with operators nested inside conditionals
    and loop bodies.
  * COMPOSED rewrites: 1-3 semantics-preserving transformations applied in
    sequence, so the two sides can differ structurally by a lot while remaining
    mathematically identical.
  * ANALOG OPERATORS in the generated bodies (ddt, idt, laplace_nd, $limit), in the
    only place the LRM permits them -- see below.
  * ONE-PORT AND THREE-TERMINAL bodies from the same grammar.

The oracle is unchanged and needs no reference implementation: the two sides must
agree numerically. What changes is how hard the generator pushes.

WHERE ANALOG OPERATORS MAY GO. An early version emitted `ddt`/`idt`/`laplace_nd`/
`$limit` anywhere in the tree, on the assumption that a conditional operator was a
hoisting problem for the compiler. That is wrong, and openvaf-r said so:

    error: analog operator 'idt' is not allowed in loops
    error: analog operator 'ddt' is not allowed in conditions

An analog operator carries state across time steps, so it must be evaluated on
EVERY evaluation of the module -- the LRM therefore bars it from loop bodies and
from conditional expressions (both the condition and the arms, since the arms are
conditionally evaluated). There is no hoisting; it is a hard rule and openvaf-r
enforces it correctly. So the generator tracks whether it is in unconditional
statement position and only emits operators there. Before that gate, a fifth of
every run's budget was spent on correct diagnostics rather than on comparisons.

Every body keeps a linear conductance term so the DC sweep stays solvable -- a
generated body with no conductance at some bias simply fails to converge, which is
a property of the circuit and is reported separately from a mismatch.

    python3 gengrammar.py --n 60 --seed 1 [--depth 4] [--three]
"""
import argparse
import os
import random
import re
import shutil
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

# ---------------------------------------------------------------- expressions
UNARY = ["abs(%s)", "sqrt(abs(%s)+1.0)", "exp((%s)/12.0)", "tanh(%s)",
         "(-(%s))", "ln(abs(%s)+1.0)", "pow(abs(%s)+1.0,2.0)"]
# analog operators. `idt` is given an IC so the DC point is defined; laplace uses a
# single real pole. These appear INSIDE conditionals too, which forces the compiler
# to evaluate operator state unconditionally.
OPERS = ["ddt(1e-9*(%s))", "idt(1e-3*(%s), 0.0)",
         "laplace_nd(%s, {1.0}, {1.0, 1e-6})"]
# `$limit` is NOT in OPERS: its first argument must be a BRANCH PROBE, not an
# arbitrary expression -- openvaf-r diagnoses that correctly ("expected a branch
# probe as the first argument"), and feeding it nested expressions wasted a third
# of an early run's budget on compile failures rather than comparisons. It is
# emitted separately, always applied to a bare probe.
LIMITED = "$limit(%s, \"pnjlim\", 0.025, 0.6)"


def atoms(three):
    return (["V(d,sx)", "V(d,g)", "V(g,sx)", "k1", "k2", "0.75", "V(d,sx)*k1"]
            if three else ["V(p,n)", "k1", "k2", "0.75", "V(p,n)*k1"])


def expr(rng, three, depth, uncond=False):
    if depth <= 0 or rng.random() < 0.22:
        return rng.choice(atoms(three))
    r = rng.random()
    if r < 0.30:
        return "(%s %s %s)" % (expr(rng, three, depth - 1), rng.choice("+-*"),
                               expr(rng, three, depth - 1))
    if r < 0.50:
        return rng.choice(UNARY) % expr(rng, three, depth - 1)
    if r < 0.62 and uncond:
        # operators are legal ONLY here: unconditional statement position, no loop.
        # $limit additionally takes a bare probe, never a nested expression.
        probe = "V(d,sx)" if three else "V(p,n)"
        return (LIMITED % probe if r >= 0.58
                else rng.choice(OPERS) % expr(rng, three, depth - 1))
    if r < 0.80:
        return "((%s > %s) ? %s : %s)" % (expr(rng, three, depth - 1),
                                          expr(rng, three, depth - 1),
                                          expr(rng, three, depth - 1),
                                          expr(rng, three, depth - 1))
    return "min(%s, %s)" % (expr(rng, three, depth - 1), expr(rng, three, depth - 1))


# ---------------------------------------------------------------- statements
def stmt(rng, three, depth, acc, nid, uncond=True):
    """A statement that accumulates into `acc`. Returns (code, next_id)."""
    if depth <= 0 or rng.random() < 0.30:
        return "%s = %s + (%s);" % (acc, acc, expr(rng, three, 2, uncond)), nid
    r = rng.random()
    if r < 0.28:                                    # if / else
        a, nid = stmt(rng, three, depth - 1, acc, nid, False)
        b, nid = stmt(rng, three, depth - 1, acc, nid, False)
        return ("if (%s > %s) begin %s end else begin %s end"
                % (expr(rng, three, 1), expr(rng, three, 1), a, b)), nid
    if r < 0.52:                                    # bounded for loop
        n, v = rng.randrange(2, 5), "i%d" % nid
        body, nid2 = stmt(rng, three, depth - 1, acc, nid + 1, False)
        return ("begin : g%d integer %s; for (%s=0; %s<%d; %s=%s+1) begin %s end end"
                % (nid, v, v, v, n, v, v, body)), nid2
    if r < 0.72:                                    # bounded while loop
        n, v = rng.randrange(2, 5), "j%d" % nid
        body, nid2 = stmt(rng, three, depth - 1, acc, nid + 1, False)
        return ("begin : w%d integer %s; %s = 0; while (%s < %d) begin %s %s = %s+1; end end"
                % (nid, v, v, v, n, body, v, v)), nid2
    # named block with a local temp
    t = "t%d" % nid
    body, nid2 = stmt(rng, three, depth - 1, t, nid + 1, uncond)
    return ("begin : b%d real %s; %s = 0.0; %s %s = %s + %s; end"
            % (nid, t, t, body, acc, acc, t)), nid2


# ---------------------------------------------------------------- rewrites
REWRITES = [
    ("neg2", lambda e: "(-(-(%s)))" % e),
    ("mul1", lambda e: "((%s)*1.0)" % e),
    ("addsub", lambda e: "(((%s)+7.5)-7.5)" % e),
    ("divrecip", lambda e: "((%s)/(1.0/8.0)/8.0)" % e),
    ("pow1", lambda e: "pow((%s),1.0)" % e),
    ("truthternary", lambda e: "((1 > 0) ? (%s) : 0.0)" % e),
    ("minself", lambda e: "min((%s),(%s))" % (e, e)),
    ("halfsum", lambda e: "(0.5*(%s) + 0.5*(%s))" % (e, e)),
]


def compose(rng, e, k):
    """Apply k rewrites in sequence, so the two sides differ structurally a lot."""
    names = []
    for _ in range(k):
        n, f = rng.choice(REWRITES)
        e = f(e)
        names.append(n)
    return e, "+".join(names)


TMPL1 = """`include "disciplines.vams"
module dut(p, n);
  inout p, n;
  electrical p, n;
  parameter real k1 = 1e-3 from (0:inf);
  parameter real k2 = 1e-3 from (0:inf);
  analog begin : TOP
    real acc;
    acc = 0.0;
    %s
    I(p,n) <+ k2*V(p,n) + 1e-4*(%s);
  end
endmodule
"""

TMPL3 = """`include "disciplines.vams"
module dut(d, g, sx);
  inout d, g, sx;
  electrical d, g, sx;
  parameter real k1 = 1e-3 from (0:inf);
  parameter real k2 = 1e-3 from (0:inf);
  analog begin : TOP
    real acc;
    acc = 0.0;
    %s
    I(d,sx) <+ k2*V(d,sx) + 1e-4*(%s);
    I(g,sx) <+ k2*V(g,sx);
  end
endmodule
"""


def build(body_stmt, tail_expr, tag, three):
    d = os.path.join(HERE, "g_%s" % tag)
    shutil.rmtree(d, ignore_errors=True)
    os.makedirs(d, exist_ok=True)
    src = (TMPL3 if three else TMPL1) % (body_stmt, tail_expr)
    open(os.path.join(d, "dut.va"), "w").write(src)
    env = dict(os.environ, RAYON_NUM_THREADS="1", TMPDIR=d)
    r = subprocess.run([VAF, "dut.va", "-o", "dut.osdi"], cwd=d, env=env,
                       capture_output=True, text=True, timeout=900, errors="replace")
    return (os.path.join(d, "dut.osdi") if r.returncode == 0 else None,
            (r.stdout + r.stderr)[:90])


def sim(osdi, tag, three):
    p = os.path.join(HERE, "g_%s.cir" % tag)
    net = ("gg\nV1 in 0 dc 0.4 ac 1\nVg gg 0 dc 0.3\nRs in a 1k\nRg gg g 1k\n"
           "N1 a g 0 dut\n.model dut dut()\n" if three else
           "gg\nV1 in 0 dc 0.4 ac 1\nRs in a 1k\nN1 a 0 dut\n.model dut dut()\n")
    open(p, "w").write(net + ".control\noption noacct\nset numdgt=17\npre_osdi %s\n"
                       "dc V1 -0.4 0.4 0.2\nprint v(a)\n"
                       "ac lin 2 1e3 1e6\nprint vdb(a)\n.endc\n.end\n" % osdi)
    r = subprocess.run([NG, "-b", os.path.basename(p)], cwd=HERE, capture_output=True,
                       text=True, timeout=600, errors="replace")
    return [float(m.group(1)) for m in re.finditer(
        r"^\s*\d+\s+[-+0-9.eE]+\s+([-+0-9.eE]+)\s*$", r.stdout + r.stderr, re.M)]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=40)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--depth", type=int, default=4)
    ap.add_argument("--three", action="store_true", help="3-terminal bodies")
    a = ap.parse_args()
    if not VAF or not os.path.exists(VAF):
        print("set OPENVAF_BIN"); return 2

    rng = random.Random(a.seed)
    ATOL, RTOL = 1e-12, 1e-9
    tally = {"PASS": 0, "MISMATCH": 0, "NOCOMP": 0, "NODATA": 0}
    seen = []
    for i in range(a.n):
        three = a.three
        body, _ = stmt(rng, three, a.depth, "acc", 0)
        base = expr(rng, three, 2, True)
        alt, how = compose(rng, base, rng.randrange(1, 4))
        oa, ea = build(body, base, "a%d" % i, three)
        ob, eb = build(body, alt, "b%d" % i, three)
        if not (oa and ob):
            tally["NOCOMP"] += 1
            seen.append(("NOCOMP", how, (ea or eb)))
            continue
        va, vb = sim(oa, "a%d" % i, three), sim(ob, "b%d" % i, three)
        if not va or len(va) != len(vb):
            tally["NODATA"] += 1
            continue
        worst = max(abs(x - y) for x, y in zip(va, vb))
        if all(abs(x - y) <= ATOL + RTOL * max(abs(x), abs(y)) for x, y in zip(va, vb)):
            tally["PASS"] += 1
        else:
            tally["MISMATCH"] += 1
            seen.append(("MISMATCH", how, "max abs dev %.3e" % worst))
            print("  MISMATCH  rewrites=%-28s %s" % (how, "dev %.3e" % worst), flush=True)
            open(os.path.join(HERE, "mismatch_%d.va" % i), "w").write(
                ((TMPL3 if three else TMPL1) % (body, base)) +
                "\n/* ---- partner side ---- */\n" +
                ((TMPL3 if three else TMPL1) % (body, alt)))
        if (i + 1) % 10 == 0:
            print("  ... %d/%d  %s" % (i + 1, a.n,
                  " ".join("%s=%d" % kv for kv in tally.items() if kv[1])), flush=True)

    for j in os.listdir(HERE):
        q = os.path.join(HERE, j)
        if j.startswith("g_"):
            shutil.rmtree(q, ignore_errors=True) if os.path.isdir(q) else os.remove(q)
    print("\n  %d generated pairs: %s" % (a.n, " ".join("%s=%d" % kv for kv in tally.items())))
    if tally["PASS"] < a.n // 3:
        print("  *** SUSPECT RUN: most pairs never reached a comparison; the "
              "generator or the deck is at fault, not the compiler ***")
        return 2
    return 1 if tally["MISMATCH"] else 0


sys.exit(main())
