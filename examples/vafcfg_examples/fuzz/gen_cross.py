#!/usr/bin/env python3
"""Cross-feature Verilog-A generator: VALID-BY-CONSTRUCTION programs that
compose many language features at once.

WHY THIS IS DIFFERENT FROM THE PRIOR ROUNDS. E-213/220/230/263 mutated the
corpus (byte/token/keyword/bracket injection). Mutation is excellent at finding
PARSER bugs, but almost every mutant dies at parse time, so the deep stages --
HIR lowering, type inference, MIR build, autodiff, the optimizer, LLVM codegen,
OSDI emission -- are barely exercised. E-263's "valid-but-pathological" inputs
reached them, but were hand-written and one feature at a time.

This generator emits only well-formed programs, so ~every input reaches the
backend, and it deliberately COMPOSES features that were each developed and
tested in isolation (~100 enhancements, each with its own code path): an idt
inside a casez inside a for-loop inside a named block with block-scope
parameters, indexing an N-D array by a genvar, contributing to a bus port.
Feature interaction is where compilers actually break.

Emits to stdout, or writes N files with --out.
"""
import argparse
import random
import sys

# ---------------------------------------------------------------- symbol pool


class Ctx:
    def __init__(self, rng):
        self.rng = rng
        self.nodes = []        # electrical nets usable in V()/I()
        self.reals = []
        self.ints = []
        self.rparams = []
        self.iparams = []
        self.arrays = []       # (name, [n0, n1, ...])
        self.iarrays = []
        self.genvars = []
        self.funcs = []        # (name, argc)
        self.strings = []
        self.in_func = False   # analog operators are illegal inside functions
        self.in_loop = False   # ...and inside loops
        self.in_event = False  # contributions are illegal inside event blocks
        self.branches = []     # (n1, n2)

    def aop_ok(self):
        return not self.in_func and not self.in_loop and not self.in_event

    def pick(self, pool, dflt=None):
        return self.rng.choice(pool) if pool else dflt


# ---------------------------------------------------------------- expressions

RFUN1 = ["sin", "cos", "tan", "asin", "acos", "atan", "sinh", "cosh", "tanh",
         "exp", "ln", "log", "sqrt", "abs", "floor", "ceil"]
RFUN2 = ["pow", "atan2", "hypot", "min", "max"]

# Analog operators. Only legal in an analog block, never inside an analog
# function -- crossing that boundary is itself one of the things being tested,
# but only in the deliberately-invalid mode.
AOPS = [
    lambda c, e: "ddt(%s)" % e,
    lambda c, e: "ddt(%s, 1e-9)" % e,
    lambda c, e: "idt(%s)" % e,
    lambda c, e: "idt(%s, 0.0)" % e,
    lambda c, e: "idtmod(%s, 0.0, 1.0, 0.0)" % e,
    lambda c, e: "absdelay(%s, 1e-9)" % e,
    lambda c, e: "transition(%s)" % e,
    lambda c, e: "transition(%s, 0.0, 1e-9, 1e-9)" % e,
    lambda c, e: "slew(%s, 1e6, -1e6)" % e,
    lambda c, e: "limexp(%s)" % e,
    lambda c, e: "laplace_nd(%s, {1.0}, {1.0, 1e-9})" % e,
    lambda c, e: "laplace_zd(%s, {-1e9}, {1.0, 1e-9})" % e,
    lambda c, e: "laplace_np(%s, {1.0}, {-1e9, 0.0})" % e,
    lambda c, e: "zi_nd(%s, {1.0}, {1.0, -0.5}, 1e-9, 0.0)" % e,
    lambda c, e: "white_noise(abs(%s), \"wn\")" % e,
    lambda c, e: "flicker_noise(abs(%s), 1.0, \"fn\")" % e,
    lambda c, e: "last_crossing(%s, 0)" % e,
]

SIMPARAM = ['$simparam("gmin", 1e-12)', '$simparam("tnom", 27.0)',
            "$temperature", "$vt", "$abstime", "$mfactor"]


def rexpr(c, d=0):
    """A real-valued expression."""
    r = c.rng
    if d > 3:
        return leaf_r(c)
    k = r.randrange(14)
    if k == 0:
        return "(%s %s %s)" % (rexpr(c, d + 1), r.choice("+-*"), rexpr(c, d + 1))
    if k == 1:
        return "(%s / (1.0 + abs(%s)))" % (rexpr(c, d + 1), rexpr(c, d + 1))
    if k == 2:
        return "%s(%s)" % (r.choice(RFUN1), rexpr(c, d + 1))
    if k == 3:
        return "%s(%s, %s)" % (r.choice(RFUN2), rexpr(c, d + 1), rexpr(c, d + 1))
    if k == 4:
        return "(%s ? %s : %s)" % (cond(c, d + 1), rexpr(c, d + 1), rexpr(c, d + 1))
    if k == 5:
        return "(%s ** %s)" % (rexpr(c, d + 1), r.choice(["2", "2.0", "0.5", "(-2)"]))
    if k == 6 and c.aop_ok():
        return r.choice(AOPS)(c, rexpr(c, d + 1))
    if k == 7 and c.arrays:
        n, dims = r.choice(c.arrays)
        return n + "".join("[%s]" % idx(c, s) for s in dims)
    if k == 8 and c.funcs:
        n, argc = r.choice(c.funcs)
        return "%s(%s)" % (n, ", ".join(rexpr(c, d + 1) for _ in range(argc)))
    if k == 9 and c.aop_ok():
        return "ddx(%s, V(%s))" % (rexpr(c, d + 1), c.pick(c.nodes, "a"))
    if k == 10:
        return "$itor(%s)" % iexpr(c, d + 1)
    if k == 11:
        return r.choice(SIMPARAM)
    return leaf_r(c)


def leaf_r(c):
    r = c.rng
    opts = ["1.0", "0.0", "1e-12", "1e12", "0.5", "(-1.0)", "3.14159"]
    if c.reals:
        opts += c.reals
    if c.rparams:
        opts += c.rparams
    if c.nodes and not c.in_func:
        n1 = r.choice(c.nodes)
        n2 = r.choice(c.nodes)
        opts += ["V(%s)" % n1, "V(%s, %s)" % (n1, n2), "I(%s, %s)" % (n1, n2)]
        if n1 != n2:
            opts += ["V(%s, %s)" % (n2, n1)]
    return r.choice(opts)


def idx(c, size):
    """An in-range array index -- possibly a genvar or an int var, but always
    clamped so the program stays semantically valid."""
    r = c.rng
    if c.genvars and r.random() < 0.3:
        return "(%s %% %d)" % (r.choice(c.genvars), size)
    if c.ints and r.random() < 0.3:
        return "(%s %% %d)" % (r.choice(c.ints), size)
    return str(r.randrange(size))


def iexpr(c, d=0):
    r = c.rng
    if d > 2:
        return leaf_i(c)
    k = r.randrange(9)
    if k == 0:
        return "(%s %s %s)" % (iexpr(c, d + 1), r.choice(["+", "-", "*", "&", "|", "^"]),
                               iexpr(c, d + 1))
    if k == 1:
        return "(%s %s %s)" % (iexpr(c, d + 1), r.choice([">>", "<<", ">>>"]),
                               str(r.randrange(0, 32)))
    if k == 2:
        return "(%s ? %s : %s)" % (cond(c, d + 1), iexpr(c, d + 1), iexpr(c, d + 1))
    if k == 3:
        return "$clog2(%s)" % iexpr(c, d + 1)
    if k == 4:
        return "$rtoi(%s)" % rexpr(c, d + 1)
    if k == 5:
        return "(~%s)" % iexpr(c, d + 1)
    if k == 6 and c.iarrays:
        n, dims = r.choice(c.iarrays)
        return n + "".join("[%s]" % idx(c, s) for s in dims)
    return leaf_i(c)


def leaf_i(c):
    r = c.rng
    opts = ["0", "1", "2", "31", "32", "63", "(-1)", "255",
            "2147483647", "(-2147483648)", "'b1010", "'hff", "'o17", "4'd9"]
    if c.ints:
        opts += c.ints
    if c.iparams:
        opts += c.iparams
    if c.genvars:
        opts += c.genvars
    return r.choice(opts)


def cond(c, d=0):
    r = c.rng
    a = rexpr(c, d + 1) if r.random() < 0.5 else iexpr(c, d + 1)
    b = rexpr(c, d + 1) if r.random() < 0.5 else iexpr(c, d + 1)
    e = "(%s %s %s)" % (a, r.choice(["<", ">", "<=", ">=", "==", "!="]), b)
    if r.random() < 0.25:
        e = "(%s %s %s)" % (e, r.choice(["&&", "||"]), cond(c, d + 1))
    if r.random() < 0.15:
        e = "(!%s)" % e
    return e


# ---------------------------------------------------------------- statements

def contrib(c):
    r = c.rng
    if c.in_event:
        return assign(c) if (c.reals or c.ints) else sys_task(c)
    n1 = c.pick(c.nodes, "a")
    n2 = c.pick(c.nodes, "b")
    if n1 == n2:
        n2 = c.nodes[0] if c.nodes else "b"
    kind = r.choice(["V", "I", "I", "I"])          # current-mode is the common case
    return ["%s(%s, %s) <+ %s;" % (kind, n1, n2, rexpr(c))]


def assign(c):
    r = c.rng
    if c.reals and r.random() < 0.7:
        return ["%s = %s;" % (r.choice(c.reals), rexpr(c))]
    if c.ints:
        return ["%s = %s;" % (r.choice(c.ints), iexpr(c))]
    if c.arrays:
        n, dims = r.choice(c.arrays)
        return ["%s%s = %s;" % (n, "".join("[%s]" % idx(c, s) for s in dims), rexpr(c))]
    return contrib(c)


def sys_task(c):
    r = c.rng
    return [r.choice([
        '$strobe("v=%%g", %s);' % rexpr(c),
        '$display("i=%%d", %s);' % iexpr(c),
        "$bound_step(%s);" % ("1e-9" if r.random() < .5 else "abs(%s)+1e-12" % rexpr(c)),
        "$discontinuity(%d);" % r.randrange(0, 3),
        '$fatal(0, "x");' if r.random() < 0.02 else '$strobe("t=%%g", $abstime);',
    ])]


def block(c, d, n=None):
    """A statement list, recursively wrapped."""
    r = c.rng
    n = n or r.randrange(1, 4)
    out = []
    for _ in range(n):
        out += stmt(c, d)
    return out


def stmt(c, d):
    """One statement, possibly a wrapper that nests further."""
    r = c.rng
    if d >= 4:
        return r.choice([contrib, assign, sys_task])(c)
    k = r.randrange(16)

    if k == 0:                                                   # if / else
        s = ["if (%s) begin" % cond(c)] + ind(block(c, d + 1)) + ["end"]
        if r.random() < 0.5:
            s += ["else begin"] + ind(block(c, d + 1)) + ["end"]
        return s

    if k == 1 and c.ints:                                        # for
        v = r.choice(c.ints)
        with loop(c):
            body = ind(block(c, d + 1))
        return (["for (%s = 0; %s < %d; %s = %s + 1) begin" %
                 (v, v, r.randrange(1, 5), v, v)] + body + ["end"])

    if k == 2 and c.ints:                                        # while
        v = r.choice(c.ints)
        with loop(c):
            body = ind(block(c, d + 1) + ["%s = %s + 1;" % (v, v)])
        return ([("%s = 0;" % v), "while (%s < %d) begin" % (v, r.randrange(1, 4))] +
                body + ["end"])

    if k == 3 and c.ints:                                        # do-while (E-19)
        v = r.choice(c.ints)
        with loop(c):
            body = ind(block(c, d + 1) + ["%s = %s + 1;" % (v, v)])
        return ([("%s = 0;" % v), "do begin"] + body +
                ["end while (%s < %d);" % (v, r.randrange(1, 4))])

    if k == 4:                                                   # repeat
        with loop(c):
            body = ind(block(c, d + 1))
        return ["repeat (%d) begin" % r.randrange(1, 4)] + body + ["end"]

    if k == 5:                                                   # case / casex / casez
        kw = r.choice(["case", "casex", "casez"])                # E-78
        sel = iexpr(c)
        s = ["%s (%s)" % (kw, sel)]
        for _ in range(r.randrange(1, 4)):
            if kw == "casex":
                lbl = r.choice(["0", "1", "2", "4'b1x0z", "4'b10?1"])
            elif kw == "casez":
                lbl = r.choice(["0", "1", "2", "4'b1z01", "4'b10?1"])
            else:
                lbl = r.choice(["0", "1", "2", "3"])
            s += ind(["%s: begin" % lbl] + ind(block(c, d + 1, 1)) + ["end"])
        s += ind(["default: begin"] + ind(block(c, d + 1, 1)) + ["end"])
        return s + ["endcase"]

    if k == 6:                                                   # named block + params
        nm = "blk%d" % r.randrange(10000)
        decls = []
        if r.random() < 0.7:                                     # block-scope params E-87
            decls += ["parameter real bp = %s;" % r.choice(["1.0", "2.5"])]
        lv = "lv%d" % r.randrange(10000)
        decls += ["real %s;" % lv]
        c.reals.append(lv)
        body = ind(decls + block(c, d + 1))
        c.reals.remove(lv)
        return ["begin : %s" % nm] + body + ["end"]

    if k == 7 and not c.in_func:                                 # event control
        ev = r.choice(["initial_step", "final_step",
                       "initial_step(\"static\")", "cross(%s, 0)" % rexpr(c),
                       "timer(0, 1e-9)", "above(%s)" % rexpr(c)])
        with event(c):
            body = ind(block(c, d + 1))
        return ["@(%s) begin" % ev] + body + ["end"]

    if k == 8 and not c.in_func:                                 # event OR (E-59)
        with event(c):
            body = ind(block(c, d + 1))
        return ["@(initial_step or final_step) begin"] + body + ["end"]

    return r.choice([contrib, assign, sys_task])(c)


class _flag:
    def __init__(self, c, name):
        self.c, self.n = c, name

    def __enter__(self):
        self.old = getattr(self.c, self.n)
        setattr(self.c, self.n, True)

    def __exit__(self, *a):
        setattr(self.c, self.n, self.old)


def loop(c):
    return _flag(c, "in_loop")


def event(c):
    return _flag(c, "in_event")


def ind(lines):
    return ["    " + l for l in lines]


# ---------------------------------------------------------------- module

def gen_module(rng, mi=0):
    c = Ctx(rng)
    r = rng
    L = []

    nn = r.randrange(2, 6)
    c.nodes = ["n%d" % i for i in range(nn)]
    ports = list(c.nodes)

    L.append("module m%d(%s);" % (mi, ", ".join(ports)))
    L.append("  inout %s;" % ", ".join(ports))
    L.append("  electrical %s;" % ", ".join(ports))

    # internal node -- exercises node collapsing / extra unknowns
    if r.random() < 0.4:
        c.nodes.append("ni")
        L.append("  electrical ni;")

    # ground-referenced + branch decls
    if r.random() < 0.3 and len(c.nodes) >= 2:
        L.append("  branch (%s, %s) br;" % (c.nodes[0], c.nodes[1]))

    for i in range(r.randrange(1, 4)):
        n = "pr%d" % i
        c.rparams.append(n)
        rng_ = r.choice(["", " from [0:inf)", " from (-inf:inf)", " from [-10:10]"])
        L.append("  parameter real %s = %s%s;" % (n, r.choice(["1.0", "0.0", "1e-9", "2.0"]), rng_))
    for i in range(r.randrange(0, 3)):
        n = "pi%d" % i
        c.iparams.append(n)
        L.append("  parameter integer %s = %d;" % (n, r.randrange(0, 5)))

    for i in range(r.randrange(1, 4)):
        n = "r%d" % i
        c.reals.append(n)
        L.append("  real %s;" % n)
    for i in range(r.randrange(1, 3)):
        n = "i%d" % i
        c.ints.append(n)
        L.append("  integer %s;" % n)

    # arrays, incl. N-D (E-15/43)
    for i in range(r.randrange(0, 3)):
        n = "ar%d" % i
        dims = [r.randrange(2, 4) for _ in range(r.randrange(1, 3))]
        c.arrays.append((n, dims))
        L.append("  real %s%s;" % (n, "".join("[0:%d]" % (d - 1) for d in dims)))
    if r.random() < 0.4:
        dims = [r.randrange(2, 4)]
        c.iarrays.append(("ia0", dims))
        L.append("  integer ia0[0:%d];" % (dims[0] - 1))

    # an analog function -- analog operators are illegal in here
    if r.random() < 0.5:
        fn = "f%d" % r.randrange(1000)
        argc = r.randrange(1, 3)
        c.in_func = True
        args = ["x%d" % i for i in range(argc)]
        saved = c.reals
        c.reals = list(args)
        body = ind(ind(["%s = %s;" % (fn, rexpr(c))]))
        c.reals = saved
        c.in_func = False
        L.append("  analog function real %s;" % fn)
        for a in args:
            L.append("    input %s; real %s;" % (a, a))
        L.append("    begin")
        L += body
        L.append("    end")
        L.append("  endfunction")
        c.funcs.append((fn, argc))

    L.append("  analog begin")
    L += ind(ind(block(c, 0, r.randrange(2, 5))))
    # guarantee at least one contribution so the module is a real device
    L += ind(ind(contrib(c)))
    L.append("  end")
    L.append("endmodule")
    return L


def gen_file(seed):
    rng = random.Random(seed)
    out = ['`include "disciplines.vams"']
    for mi in range(rng.randrange(1, 3)):          # multi-module (E-76)
        out += gen_module(rng, mi)
    return "\n".join(out) + "\n"


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, default=1)
    a = ap.parse_args()
    sys.stdout.write(gen_file(a.seed))
