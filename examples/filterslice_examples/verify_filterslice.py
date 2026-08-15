#!/usr/bin/env python3
"""Enhancement-459: a part select as an analog-filter coefficient vector.

Enhancement-85's `partselect_examples` covers part selects in instance PORT
CONNECTIONS, which is where they were already legal; this suite covers the one
behavioural position LRM Syntax 4-3 adds.

LRM Syntax 4-3 gives an analog filter's coefficient argument three forms:

    analog_filter_function_arg ::=
          parameter_identifier
        | parameter_identifier [ msb_constant_expression : lsb_constant_expression ]
        | constant_assignment_pattern_or_null

Enhancement-458 implemented the first and third. The middle one -- a PART SELECT
of an array, so a model can keep one coefficient table and hand a filter the
slice it needs -- was rejected with `wrong number of array indices`, because
`de[0:1]` and Enhancement-15's multi-dimensional `m[i][j]` both reach inference
as a `BitSelect` carrying two index expressions.

They are distinguishable after all, and no new syntax was needed: the parser has
kept the `:` token in the tree since Enhancement-85, and body lowering already
records every part select it sees in `stray_part_selects`. Inference now resolves
such an argument into its element slice and records it in the same whole-array
maps a bare array identifier uses, so lowering carries it unchanged.

ORDER IS NOT COSMETIC. The slice is built in the order written -- `de[0:1]` is
`{de[0], de[1]}` and `de[1:0]` is `{de[1], de[0]}` -- because a Laplace
coefficient k multiplies s^k, so a reversed slice is a DIFFERENT FILTER. That is
pinned below by value, not by acceptance: the forward slice must equal the
equivalent literal to the digit and the reversed one must not.

CONSUMING THE EXPRESSION IS ALSO WHAT MAKES IT LEGAL. Enhancement-85 reports
every part select left in a body -- they are otherwise valid only in instance
port connections, which elaboration consumes textually -- and body validation now
skips exactly those inference resolved into a whole-array argument. Everywhere
else the restriction stands, which the last block here pins: `y = de[0:1];` and
`de[0:1] * 2.0` are still refused.

A trap worth recording: `zi_*` needed one more fix than `laplace_*`. The Laplace
filters resolve their array arguments and never look at them again, but `zi_*`
pre-resolves and then falls through to the generic signature match, which
re-inferred the slice and counted its two range bounds as two indices into a 1-D
array -- the very error being fixed, reappearing one layer up.
"""
import os
import re
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from _setup import VAF as OPENVAF, NG as NGSPICE  # noqa: E402
from _setup import check_both_solvers as _check_both_solvers; _check_both_solvers(__file__)  # verify under BOTH KLU and Sparse solvers

HDR = '`include "disciplines.vams"\n'
CHECKS = [0]
PASSED = [0]

# de = {1.0, 1e-6, 9.0, 9.0}; the slice [0:1] is the denominator of
# H(s) = 1/(1 + 1e-6 s), whose response at t = 5 us on a 1 V/us ramp is 4.00674.
DE = (" parameter real de[0:3] = '{1.0, 1e-6, 9.0, 9.0};\n"
      " parameter real nu[0:1] = '{1.0, 0.0};\n")
DV = " real dv[0:3]; real nv[0:1];\n"
INIT = "dv[0]=1.0; dv[1]=1e-6; dv[2]=9.0; dv[3]=9.0; nv[0]=1.0; nv[1]=0.0;"


def check(label, ok, detail=""):
    CHECKS[0] += 1
    if ok:
        PASSED[0] += 1
    print(f"  {'PASS' if ok else 'FAIL'}  {label:52s} {detail[:38]}")


def build(src, tag):
    d = os.path.join(HERE, "_w_%s" % tag)
    shutil.rmtree(d, ignore_errors=True)
    os.makedirs(d)
    open(os.path.join(d, "m.va"), "w").write(src)
    env = dict(os.environ, RAYON_NUM_THREADS="1", TMPDIR=d)
    r = subprocess.run([OPENVAF, os.path.join(d, "m.va"), "-o", os.path.join(d, "m.osdi")],
                       capture_output=True, text=True, env=env, cwd=d, timeout=900,
                       stdin=subprocess.DEVNULL)
    return d, r.returncode, (r.stdout or "") + (r.stderr or "")


def crashed(rc):
    return rc == 101 or rc < 0 or rc == 139 or rc == 134


def mod(body, decl="", pre=""):
    return (HDR + "module dut(p,n);\n inout p,n; electrical p,n;\n" + decl
            + f" analog begin {pre} {body} end\nendmodule\n")


def response(ex, decl="", tag="t", pre=""):
    """Filter output at t = 5 us on a 0->10 V ramp, read as -i(v1)."""
    d, rc, out = build(mod(f"I(p,n) <+ {ex};", decl, pre), tag)
    if rc != 0:
        return None
    deck = ("p\n.control\npre_osdi m.osdi\n.endc\nV1 a 0 PWL(0 0 10u 10)\nN1 a 0 mm\n"
            ".model mm dut()\n.control\noption noacct\nset numdgt=15\ntran 0.02u 10u\n"
            "meas tran y FIND i(v1) AT=5u\n.endc\n.end\n")
    open(os.path.join(d, "q.cir"), "w").write(deck)
    r = subprocess.run(["perl", "-e", "alarm 60; exec @ARGV", NGSPICE, "-b", "q.cir"],
                       cwd=d, capture_output=True, text=True, errors="replace",
                       stdin=subprocess.DEVNULL)
    m = re.search(r"^\s*y\s*=\s*(\S+)", (r.stdout or "") + (r.stderr or ""), re.M)
    return -float(m.group(1)) if m else None


print("\n[1] a slice must give exactly the filter its elements spell out")
ref = response("laplace_nd(V(p,n), '{1.0}, '{1.0, 1e-6})", "", "ref")
check("the literal reference H(s) = 1/(1 + 1e-6 s)",
      ref is not None and abs(ref - 4.00674) < 1e-3, f"{ref}")
for label, ex, decl, pre in [
        ("a parameter-array slice  nu[0:0], de[0:1]",
         "laplace_nd(V(p,n), nu[0:0], de[0:1])", DE, ""),
        ("a variable-array slice   nv[0:0], dv[0:1]",
         "laplace_nd(V(p,n), nv[0:0], dv[0:1])", DV, INIT)]:
    got = response(ex, decl, "s%d" % (abs(hash(label)) % 97), pre)
    check(label + " == the literal",
          got is not None and ref is not None and abs(got - ref) <= 1e-9 * abs(ref),
          f"{got}")

print("\n[2] the slice ORDER is the written order -- a reversed slice is another filter")
rev = response("laplace_nd(V(p,n), nu[0:0], de[1:0])", DE, "rev")
check("de[1:0] does NOT equal de[0:1]",
      rev is not None and ref is not None and abs(rev - ref) > 1e-3 * abs(ref), f"{rev}")

print("\n[3] a whole-range slice is the bare identifier")
full = response("laplace_nd(V(p,n), nu, de)", DE, "full")
whole = response("laplace_nd(V(p,n), nu[0:1], de[0:3])", DE, "whole")
check("de[0:3] gives exactly what de gives",
      full is not None and whole is not None and full == whole, f"{full} vs {whole}")

print("\n[4] every filter that takes a coefficient vector accepts one")
for label, ex in [("laplace_nd", "laplace_nd(V(p,n), nu[0:0], de[0:1])"),
                  ("laplace_zd", "laplace_zd(V(p,n), nu[0:0], de[0:1])"),
                  ("laplace_np", "laplace_np(V(p,n), nu[0:0], de[0:1])"),
                  ("laplace_zp", "laplace_zp(V(p,n), nu[0:0], de[0:1])"),
                  ("zi_nd", "zi_nd(V(p,n), nu[0:0], de[0:1], 1e-7)"),
                  ("zi_zd", "zi_zd(V(p,n), nu[0:0], de[0:1], 1e-7)"),
                  ("zi_np", "zi_np(V(p,n), nu[0:0], de[0:1], 1e-7)"),
                  ("zi_zp", "zi_zp(V(p,n), nu[0:0], de[0:1], 1e-7)")]:
    _d, rc, out = build(mod(f"I(p,n) <+ {ex};", DE), "f_" + label)
    check(f"{label} accepts a part select", rc == 0,
          (out.strip().splitlines() or [""])[0][:36])

print("\n[5] a bad range is refused, and never crashes")
for label, ex in [("de[0:9] runs past the end", "laplace_nd(V(p,n), nu[0:0], de[0:9])"),
                  ("de[-1:1] starts below zero", "laplace_nd(V(p,n), nu[0:0], de[-1:1])"),
                  ("de[4:4] is one past the last", "laplace_nd(V(p,n), nu[0:0], de[4:4])")]:
    _d, rc, out = build(mod(f"I(p,n) <+ {ex};", DE), "b%d" % (abs(hash(label)) % 97))
    check(label + " is refused", rc != 0 and not crashed(rc),
          (out.strip().splitlines() or [""])[0][:36])

print("\n[6] Enhancement-85 still holds everywhere else")
for label, body in [("as a plain value", "y = de[0:1];"),
                    ("in arithmetic", "y = de[0:1] * 2.0;"),
                    ("as a contribution", "I(p,n) <+ de[0:1];")]:
    decl = DE + (' (*desc="y"*) real y;\n' if "y =" in body else "")
    _d, rc, out = build(mod(body + " I(p,n) <+ V(p,n)*1e-3;", decl),
                        "e%d" % (abs(hash(label)) % 97))
    check(f"a part select {label} is still refused", rc != 0 and not crashed(rc),
          (out.strip().splitlines() or [""])[0][:36])
# an ordinary single-element bit select is untouched
_d, rc, out = build(mod('y = de[1]; I(p,n) <+ V(p,n)*1e-3;',
                        DE + ' (*desc="y"*) real y;\n'), "bit")
check("an ordinary bit select de[1] still compiles", rc == 0,
      (out.strip().splitlines() or [""])[0][:36])

for j in os.listdir(HERE):
    if j.startswith("_w_"):
        shutil.rmtree(os.path.join(HERE, j), ignore_errors=True)
ok = PASSED[0] == CHECKS[0]
print(f"\n{'ALL PASS' if ok else 'FAILURES'}: {PASSED[0]}/{CHECKS[0]} passed")
sys.exit(0 if ok else 1)
