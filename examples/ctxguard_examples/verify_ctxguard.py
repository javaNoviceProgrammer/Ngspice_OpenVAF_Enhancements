#!/usr/bin/env python3
"""Enhancement-460: five defects from a one-hour hunt at openvaf-r.

One is a compiler crash, one is a silent wrong answer, two are code the
compiler accepted and then silently discarded, and one is a command line that
was accepted and ignored.

  [1] `a.potential.access` CRASHED THE COMPILER (exit 101, crash report, no
      diagnostic).

      LRM Syntax 5-4 names this exact case: "This syntax shall not be used for
      the `access`, `ddt_nature`, or `idt_nature` attributes of a nature, nor
      any other attribute whose value is not a constant expression." Those
      attributes hold an IDENTIFIER -- an access-function name, a nature name --
      so `nature_attr_ty` found no value type and returned `None`. That pushed
      no diagnostic, left the expression typed `Err`, and the lowering panicked
      on it: "invalid HIR: path a.potential.access was not resolved".

      Four spellings crashed: `a.potential.access`, `a.potential.idt_nature`,
      `a.flow.access` and the branch form `br.potential.access`. Which ones
      depended on whether the nature happened to DEFINE the attribute --
      `electrical`'s Voltage has an `idt_nature` (Flux) so that crashed, while
      `ddt_nature` was undefined and got a clean "not found". The same shape as
      Enhancement-455's scalar-index panic: a type that fails to resolve without
      anyone saying so.

  [2] A MULTI-DIMENSIONAL TABLE FILE WHOSE AXIS WAS NOT ASCENDING WAS
      INTERPOLATED TO GARBAGE, SILENTLY.

      `interp_1d_values` states its precondition one function below the reader:
      "`grid` is ascending". Every 1-D form establishes it -- the inline
      `'{x0,y0,...}` pairs and the two-column data file both `sort_by` and
      `dedup_by` their breakpoints -- and the multi-dimensional reader was the
      one path that did not.

      With f(x,y) = x^2 + y sampled on x = [0,1,2], writing that axis as `2 1 0`
      returned **0.5, 4.5, 4.5** across x = 0, 0.5, 1. That is not the function
      the file describes under ANY reading: taking the file at its word (row k
      belongs to axis[k]) the answer is 4.5, 3.0, 1.5, and taking the ascending
      function it is 0.5, 1.0, 1.5. The interpolation simply clamped.

      Each axis is now sorted and de-duplicated with the value tensor permuted
      to match, so a grid means exactly what the file says whatever order it is
      written in. The NaN/Inf, size and value-count checks were already there;
      only ORDER went unchecked.

  [3] AND [4] EVENT CONTROL STATEMENTS WHERE THE LRM FORBIDS THEM -- ACCEPTED,
      AND THE GUARDED STATEMENT SILENTLY DROPPED.

      LRM 5.2.1 lists three things an `analog initial` block "shall not
      contain": statements with access functions or analog operators,
      contribution statements, and event control statements. LRM 4.7.1 forbids
      the same three in an analog function. The first two were enforced in both
      places; the third was accepted in both, with no diagnostic even under
      `-E all`, and the statement it guarded never ran:

          analog initial begin @(timer(1e-6)) q = 5.0; end   // q stays 0.0
          analog function real f; ... @(timer(1e-6)) f = 5.0; // f returns x

      That is Enhancement-456's defect one level down -- an initialisation that
      looks careful and quietly does nothing.

  [5] `-D =1` NAMED NO MACRO and was accepted, then silently dropped, so the
      build failed later against the SOURCE ("macro `GAIN` has not been
      declared") rather than against the command line that was wrong.

WRITTEN AND THEN WITHDRAWN, from the same hunt: LRM 3.6.1.2 requires `abstol`
and `access` of every BASE nature and calls it illegal for a DERIVED nature to
change `access`. Both checks were implemented and both were removed when the
regression sweep failed two suites in one run -- Enhancement-39 supports a
derived nature declaring its own access ON PURPOSE (`derivednature_demo.va`
derives `Current2` that way) and Enhancement-422 pins "a nature with NO abstol
attribute at all stays legal". E-422's stated reason ("the LRM makes it
optional") does not survive reading 3.6.1.2, but the DECISION does, neither
omission produces a wrong answer, and a bug hunt does not get to overturn a
documented project decision as a side effect. The corpus passed with both rules
in place -- it was the project's own suites that caught them.

DELIBERATELY NOT CHANGED, and pinned below so the decision is recorded:

  -- `5.` as a real literal. LRM A.8.7 requires digits on both sides of the dot
     in every `real_number` alternative, so it is malformed -- but its value is
     always correct (5.0), no corpus model writes one, and making a LEXER rule
     stricter is exactly what broke eight shipping models earlier the same day
     (Enhancement-458 reserved `expm1`, which HiSIM-SOI and HiSIM-SOTB declare
     as their own function). A syntax break with no wrong-answer to prevent is
     not worth that risk.

  -- Named blocks inside an analog function. LRM 4.7.1 forbids them; openvaf
     supports them and they work correctly, so rejecting them would break
     working models to gain nothing.
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
N = [0]
OK = [0]


def check(label, ok, detail=""):
    N[0] += 1
    if ok:
        OK[0] += 1
    print(f"  {'PASS' if ok else 'FAIL'}  {label:56s} {detail[:34]}")


def build(src, tag, extra=None):
    d = os.path.join(HERE, "_w_%s" % tag)
    shutil.rmtree(d, ignore_errors=True)
    os.makedirs(d)
    open(os.path.join(d, "m.va"), "w").write(src)
    for n, c in (extra or {}).items():
        open(os.path.join(d, n), "w").write(c)
    env = dict(os.environ, RAYON_NUM_THREADS="1", TMPDIR=d)
    r = subprocess.run([OPENVAF, os.path.join(d, "m.va"), "-o", os.path.join(d, "m.osdi")],
                       capture_output=True, text=True, env=env, cwd=d, timeout=900,
                       stdin=subprocess.DEVNULL)
    return d, r.returncode, (r.stdout or "") + (r.stderr or "")


def crashed(rc):
    return rc == 101 or rc < 0 or rc == 139 or rc == 134


def sweep(d, deck_txt):
    open(os.path.join(d, "q.cir"), "w").write(deck_txt)
    r = subprocess.run(["perl", "-e", "alarm 60; exec @ARGV", NGSPICE, "-b", "q.cir"],
                       cwd=d, capture_output=True, text=True, errors="replace",
                       stdin=subprocess.DEVNULL)
    return (r.stdout or "") + (r.stderr or "")


print("\n[1] a non-constant nature attribute is refused, not a crash")
M = "module m(a,b); inout a,b; electrical a,b;\n (*desc=\"y\"*) real y;\n"
for label, expr, decl in [("a.potential.access", "a.potential.access", ""),
                          ("a.potential.idt_nature", "a.potential.idt_nature", ""),
                          ("a.flow.access", "a.flow.access", ""),
                          ("br.potential.access", "br.potential.access", " branch (a,b) br;\n")]:
    _d, rc, out = build(HDR + M + decl + f" analog begin y = {expr}; I(a,b) <+ 1e-3; end\nendmodule\n",
                        "n%d" % (abs(hash(expr)) % 97))
    check(f"{label} is refused and does NOT crash",
          rc != 0 and not crashed(rc) and "cannot be read" in out,
          (out.strip().splitlines() or [""])[0][:32])
for label, expr in [("a.potential.abstol", "a.potential.abstol"),
                    ("a.flow.abstol", "a.flow.abstol")]:
    _d, rc, out = build(HDR + M + f" analog begin y = {expr}; I(a,b) <+ 1e-3; end\nendmodule\n",
                        "g%d" % (abs(hash(expr)) % 97))
    check(f"{label} (a constant attribute) still works", rc == 0, "rc=%d" % rc)
_d, rc, out = build(HDR + "nature nv; units=\"V\"; access=Vv; abstol=1e-7; maxval=12.3; endnature\n"
                    "discipline dv; potential nv; enddiscipline\n"
                    "module m(a,b); inout a,b; dv a,b;\n (*desc=\"y\"*) real y;\n"
                    " analog begin y = a.potential.maxval; Vv(a,b) <+ 1.0; end\nendmodule\n", "umax")
check("a user-defined attribute still works", rc == 0, "rc=%d" % rc)

print("\n[2] a multi-dimensional grid means what the file says, in any axis order")
# f(x,y) = x^2 + y on x=[0,1,2], y=[0,1]; probed at y=0.5 over x = 0, 0.5, 1.
ASC = "2\n3 2\n0 1 2\n0 1\n0 1\n1 2\n4 5\n"
# the same TABLE written with x descending: rows follow the axis, so this file
# describes the mirrored function and must interpolate to 4.5 3.0 1.5
DESC = "2\n3 2\n2 1 0\n0 1\n0 1\n1 2\n4 5\n"
# x written out of order; rows still follow the axis
UNSORT = "2\n3 2\n1 0 2\n0 1\n0 1\n1 2\n4 5\n"


def table_curve(tbl, tag, expr='$table_model(V(a,b), 0.5, "t.tbl")'):
    d, rc, out = build(HDR + "module m(a,b); inout a,b; electrical a,b;\n"
                       f" analog I(a,b) <+ {expr}*1e-3;\nendmodule\n", tag, {"t.tbl": tbl})
    if rc != 0:
        return None
    txt = sweep(d, "p\n.control\npre_osdi m.osdi\n.endc\nV1 a 0 dc 0\nN1 a 0 mm\n.model mm m()\n"
                ".control\noption noacct\nset numdgt=8\ndc V1 0 1 0.5\nprint -i(v1)*1000\n.endc\n.end\n")
    vals = re.findall(r"^\d+\s+\S+\s+(\S+)", txt, re.M)
    return [float(v) for v in vals] if vals else None


def close(got, want):
    return got is not None and len(got) == len(want) and all(abs(g - w) < 1e-6 for g, w in zip(got, want))


asc = table_curve(ASC, "tasc")
check("ascending axis interpolates 0.5 1.0 1.5", close(asc, [0.5, 1.0, 1.5]), str(asc))
desc = table_curve(DESC, "tdesc")
check("descending axis gives the file's own function", close(desc, [4.5, 3.0, 1.5]), str(desc))
uns = table_curve(UNSORT, "tuns")
check("out-of-order axis gives the file's own function", close(uns, [1.5, 1.0, 0.5]), str(uns))
# a repeated coordinate keeps the FIRST, exactly as the 1-D dedup does
dup = table_curve("2\n3 2\n0 0 2\n0 1\n0 1\n1 2\n4 5\n", "tdup")
check("a repeated coordinate keeps the first row", close(dup, [0.5, 1.5, 2.5]), str(dup))
# 3-D: a descending first axis must agree with the equivalent ascending file
d3a = table_curve("3\n2 2 2\n0 1\n0 1\n0 1\n0 1 1 2 1 2 2 3\n", "t3a",
                  '$table_model(V(a,b), 0.5, 0.5, "t.tbl")')
d3d = table_curve("3\n2 2 2\n1 0\n0 1\n0 1\n1 2 2 3 0 1 1 2\n", "t3d",
                  '$table_model(V(a,b), 0.5, 0.5, "t.tbl")')
check("3-D descending equals the same grid ascending", d3a is not None and d3a == d3d,
      f"{d3a} vs {d3d}")
# the 1-D forms were always right and must stay so
one = table_curve("0 0\n1 1\n2 4\n", "t1a", '$table_model(V(a,b), "t.tbl")')
onedesc = table_curve("2 4\n1 1\n0 0\n", "t1d", '$table_model(V(a,b), "t.tbl")')
check("1-D file, either order, unchanged", close(one, [0.0, 0.5, 1.0]) and one == onedesc, str(one))

print("\n[3] event control statements where the LRM forbids them")
MB = "module m(a,b); inout a,b; electrical a,b; real q;\n"
for label, src in [
        ("@(timer) in analog initial",
         MB + " analog initial begin @(timer(1e-6)) q = 5.0; end\n analog I(a,b) <+ q*1e-3;\nendmodule\n"),
        ("@(initial_step) in analog initial",
         MB + " analog initial begin @(initial_step) q = 5.0; end\n analog I(a,b) <+ q*1e-3;\nendmodule\n"),
        ("@(cross) in analog initial",
         MB + " analog initial begin @(cross(1.0)) q = 5.0; end\n analog I(a,b) <+ q*1e-3;\nendmodule\n"),
        ("@(timer) in an analog function",
         MB + " analog function real f; input x; real x; begin f = x; @(timer(1e-6)) f = 5.0; end endfunction\n"
         " analog I(a,b) <+ f(1.0)*1e-3;\nendmodule\n")]:
    _d, rc, out = build(HDR + src, "e%d" % (abs(hash(label)) % 97))
    check(f"{label} is refused",
          rc != 0 and not crashed(rc) and "event control" in out,
          (out.strip().splitlines() or [""])[0][:32])
for label, src in [
        ("a plain analog initial",
         MB + " analog initial begin q = 5.0; end\n analog I(a,b) <+ q*1e-3;\nendmodule\n"),
        ("a plain analog function",
         MB + " analog function real f; input x; real x; begin f = x*2.0; end endfunction\n"
         " analog I(a,b) <+ f(1.0)*1e-3;\nendmodule\n"),
        ("@(timer) in the ANALOG block",
         MB + " analog begin @(timer(1e-6)) q = 5.0; I(a,b) <+ q*1e-3; end\nendmodule\n"),
        ("@(initial_step) in the ANALOG block",
         MB + " analog begin @(initial_step) q = 5.0; I(a,b) <+ q*1e-3; end\nendmodule\n"),
        ("a named block in a function (kept working)",
         MB + " analog function real f; input x; real x; begin : nb real l; l = x; f = l; end endfunction\n"
         " analog I(a,b) <+ f(1.0)*1e-3;\nendmodule\n")]:
    _d, rc, out = build(HDR + src, "k%d" % (abs(hash(label)) % 97))
    check(f"{label} still compiles", rc == 0, (out.strip().splitlines() or [""])[0][:32])

print("\n[4] the nature-attribute rules that were WITHDRAWN")
# Both were implemented during this change and then removed: LRM 3.6.1.2 requires
# `abstol`/`access` of every base nature and forbids a derived nature changing
# `access`, but Enhancement-422 pinned the first as legal on purpose and
# Enhancement-39 supports the second on purpose (`derivednature_demo.va` derives
# `Current2` with its own access function). Their suites caught both rules inside one
# regression sweep. Pinned here as ACCEPTED so the decision is recorded, not
# rediscovered -- and so that reversing it later is a deliberate act.
DISC = "discipline dx; potential nx; enddiscipline\n"
MOD = "module m(a,b); inout a,b; dx a,b;\n analog Vx(a,b) <+ 1.0;\nendmodule\n"
for label, src in [
        ("a base nature with no abstol (E-422's decision)",
         "nature nx; units=\"V\"; access=Vx; endnature\n" + DISC + MOD),
        ("a base nature with no units",
         "nature nx; access=Vx; abstol=1e-6; endnature\n" + DISC + MOD),
        ("a derived nature with its own access (E-39's feature)",
         "nature base; units=\"V\"; access=Vx; abstol=1e-6; endnature\n"
         "nature nx : base; access=Vy; endnature\n" + DISC + MOD),
        ("a complete base nature", "nature nx; units=\"V\"; access=Vx; abstol=1e-6; endnature\n"
         + DISC + MOD)]:
    _d, rc, out = build(HDR + src, "t%d" % (abs(hash(label)) % 97))
    check(f"{label} still compiles", rc == 0, (out.strip().splitlines() or [""])[0][:32])
# a BAD abstol is still rejected -- Enhancement-422's own guard, untouched
_d, rc, out = build(HDR + "nature nx; units=\"V\"; access=Vx; abstol=0; endnature\n" + DISC + MOD, "ab0")
check("abstol = 0 is still rejected (E-422)", rc != 0 and not crashed(rc),
      (out.strip().splitlines() or [""])[0][:32])
_d, rc, out = build(HDR + "module m(a,b); inout a,b; electrical a,b;\n analog I(a,b) <+ V(a,b)*1e-3;\nendmodule\n",
                    "std")
check("the standard disciplines.vams still compiles", rc == 0, "rc=%d" % rc)

print("\n[5] -D must name a macro")
open(os.path.join(HERE, "_d.va"), "w").write(
    HDR + "module m(a,b); inout a,b; electrical a,b;\n analog I(a,b) <+ V(a,b)*`GAIN;\nendmodule\n")
for label, arg, want_ok in [("-D GAIN=1e-3", "GAIN=1e-3", True), ("-D GAIN", "GAIN", True),
                            ("-D =1", "=1", False), ("-D ' =1'", " =1", False)]:
    r = subprocess.run([OPENVAF, "-D", arg, os.path.join(HERE, "_d.va"),
                        "-o", os.path.join(HERE, "_d.osdi")],
                       capture_output=True, text=True, cwd=HERE, stdin=subprocess.DEVNULL)
    out = (r.stdout or "") + (r.stderr or "")
    check(f"{label} is {'accepted' if want_ok else 'refused'}",
          (r.returncode == 0) == want_ok and (want_ok or "macro name is empty" in out),
          out.strip().splitlines()[0][:32] if out.strip() else "")
for j in ("_d.va", "_d.osdi"):
    p = os.path.join(HERE, j)
    if os.path.exists(p):
        os.remove(p)

print("\n[6] deliberately unchanged (see the header)")
_d, rc, _o = build(HDR + "module m(a,b); inout a,b; electrical a,b; (*desc=\"y\"*) real y;\n"
                   " analog begin y = 5.; I(a,b) <+ V(a,b)*1e-3; end\nendmodule\n", "dot")
check("`5.` is still accepted (value is correct)", rc == 0, "rc=%d" % rc)

for j in os.listdir(HERE):
    if j.startswith("_w_"):
        shutil.rmtree(os.path.join(HERE, j), ignore_errors=True)
ok = OK[0] == N[0]
print(f"\n{'ALL PASS' if ok else 'FAILURES'}: {OK[0]}/{N[0]} passed")
sys.exit(0 if ok else 1)
