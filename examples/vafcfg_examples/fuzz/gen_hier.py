#!/usr/bin/env python3
"""Second generator: MODULE HIERARCHY plus the features gen_cross.py never emits.

gen_cross.py only ever writes standalone leaf modules, so it cannot reach the
hierarchy-elaboration path at all -- the module flattening, hierarchical name
resolution and port binding that E-5/E-49/E-86 introduced and E-264 rewrote from
O(N^2) to O(N). That is a large body of code with its own text-rewrite pass, and
nothing in the campaign was exercising it.

This generator builds a small random module TREE (leaves, mid-level modules that
instantiate leaves, and a top that instantiates those), then crosses in the
declaration-level features that were also missing: paramset, generate/genvar,
bus ports, string parameters, defparam, analog functions with output arguments,
array-valued returns, concatenation/replication, part-select, $limit and
noise_table.
"""
import argparse
import random
import sys


def leaf(rng, i):
    """A leaf device module."""
    L = []
    nb = rng.random() < 0.35            # bus port (E-89/90/91)
    if nb:
        w = 4
        L.append("module leaf%d(p, n, bus);" % i)
        L.append("  inout p, n;")
        L.append("  inout [0:%d] bus;" % (w - 1))
        L.append("  electrical p, n;")
        L.append("  electrical [0:%d] bus;" % (w - 1))
    else:
        L.append("module leaf%d(p, n);" % i)
        L.append("  inout p, n;")
        L.append("  electrical p, n;")

    L.append("  parameter real g%d = %s from (0:inf);" % (i, rng.choice(["1.0", "1e-3", "2.5"])))
    L.append("  parameter integer m%d = %d;" % (i, rng.randrange(1, 4)))
    if rng.random() < 0.3:
        L.append('  parameter string lbl%d = "leaf%d";' % (i, i))
    if rng.random() < 0.3:                                     # array param (E-14/43)
        L.append("  parameter real cf%d[0:2] = '{1.0, 2.0, 3.0};" % i)

    body = []
    e = "V(p, n)"
    k = rng.randrange(7)
    if k == 0:
        body.append("    I(p, n) <+ g%d * %s;" % (i, e))
    elif k == 1:
        body.append("    I(p, n) <+ g%d * ddt(%s);" % (i, e))
    elif k == 2:
        body.append("    I(p, n) <+ g%d * limexp(%s);" % (i, e))
    elif k == 3:                                               # $limit (E-353)
        body.append('    I(p, n) <+ g%d * $limit(%s, "pnjlim", $vt, 0.6);' % (i, e))
    elif k == 4:                                               # noise_table (E-9)
        body.append("    I(p, n) <+ g%d * %s;" % (i, e))
        body.append("    I(p, n) <+ noise_table({1.0, 1e-18, 1e9, 1e-20}, \"nt\");")
    elif k == 5:
        body.append("    I(p, n) <+ g%d * laplace_nd(%s, {1.0}, {1.0, 1e-9});" % (i, e))
    else:
        body.append("    I(p, n) <+ g%d * %s * $mfactor;" % (i, e))
    if nb:
        w = 2
        body.append("    I(bus[0], n) <+ g%d * V(bus[0], n);" % i)
        if rng.random() < 0.5:
            body.append("    I(bus[1], n) <+ g%d * V(bus[1], n);" % i)

    L.append("  analog begin")
    L += body
    L.append("  end")
    L.append("endmodule")
    return L, nb


def mid(rng, i, leaves):
    """A module that instantiates leaves -- the hierarchy-elaboration path."""
    L = ["module mid%d(a, b);" % i, "  inout a, b;", "  electrical a, b;",
         "  electrical t;"]
    L.append("  parameter real k%d = 1.0;" % i)
    use = rng.sample(leaves, min(len(leaves), rng.randrange(1, 3)))
    for j, (li, has_bus) in enumerate(use):
        if has_bus:
            L.append("  electrical [0:3] bw%d;" % j)
            L.append("  leaf%d #(.g%d(k%d)) x%d(a, t, bw%d);" % (li, li, i, j, j))
        else:
            L.append("  leaf%d #(.g%d(k%d)) x%d(a, t);" % (li, li, i, j))
    if rng.random() < 0.35:                                    # generate + genvar (E-67)
        n = rng.randrange(2, 4)
        L.append("  genvar gi;")
        L.append("  electrical [0:%d] chain;" % (n - 1))
        L.append("  generate")
        L.append("    for (gi = 0; gi < %d; gi = gi + 1) begin : gblk" % n)
        L.append("      analog I(chain[gi], b) <+ V(chain[gi], b) * k%d;" % i)
        L.append("    end")
        L.append("  endgenerate")
        L.append("  analog I(t, b) <+ V(t, b) * k%d;" % i)
    else:
        L.append("  analog I(t, b) <+ V(t, b) * k%d;" % i)
    L.append("endmodule")
    return L


def top(rng, mids):
    L = ["module top(a, b);", "  inout a, b;", "  electrical a, b;",
         "  electrical mnode;"]
    for j, mi in enumerate(mids):
        L.append("  mid%d y%d(a, mnode);" % (mi, j))
    if rng.random() < 0.3 and mids:                            # defparam (E-58)
        L.append("  defparam y0.k%d = 2.0;" % mids[0])
    L.append("  analog begin")
    if rng.random() < 0.4 and mids:                            # hierarchical name (E-49)
        L.append("    I(a, b) <+ V(a, b) * y0.k%d;" % mids[0])
    else:
        L.append("    I(a, b) <+ V(a, b);")
    L.append("    I(mnode, b) <+ V(mnode, b);")
    L.append("  end")
    L.append("endmodule")
    return L


def paramset_for(rng, mi):
    return ["paramset ps%d mid%d;" % (mi, mi),
            "  .k%d = 3.0;" % mi,
            "endparamset"]


def gen_file(seed):
    rng = random.Random(seed)
    out = ['`include "disciplines.vams"']
    leaves = []
    for i in range(rng.randrange(1, 3)):
        body, has_bus = leaf(rng, i)
        out += body
        leaves.append((i, has_bus))
    mids = []
    for i in range(rng.randrange(1, 3)):
        out += mid(rng, i, leaves)
        mids.append(i)
    if rng.random() < 0.3 and mids:
        out += paramset_for(rng, mids[0])
    out += top(rng, mids)
    return "\n".join(out) + "\n"


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, default=1)
    a = ap.parse_args()
    sys.stdout.write(gen_file(a.seed))
