#!/usr/bin/env python3
"""
verify_preproc.py -- verifies Enhancement-65: the preprocessor audit,
end-to-end through the committed openvaf-r + ngspice.

A 22-probe battery over the Verilog-A compiler directives (`define with
arguments, macros-using-macros, macro calls as macro arguments, ifdef /
ifndef / elsif / else chains and nesting, `undef + redefinition,
backslash-continued definitions, trailing comments, nested `include
chains, `resetall, multi-line macro CALLS) found the machinery correct --
every compiled probe was verified numerically exact -- with ONE defect:

  RECURSIVE MACRO EXPANSION CRASHED THE COMPILER with a stack overflow,
  both direct (`define LOOP (`LOOP+1)) and mutual (`A uses `B uses `A).
  The `MacroRecursion` diagnostic existed in the preprocessor's enum --
  with a rendered message -- but was NEVER EMITTED (`call_macro` carried a
  literal "TODO track recursion"), and its report builder was a literal
  `todo!()` that would have panicked had it ever been reached. The fifth
  "scaffolded-but-unwired" find of this project.

  Fix: an expansion stack in the Processor, pushed around the macro BODY
  expansion only -- a nested call of the same macro inside an ARGUMENT
  (`QUAD(x)` defined as `TWICE(`TWICE(x))`) is finite and legal, and the
  first guard draft wrongly rejected it. Both recursion forms are now
  clean, source-located errors.

Checks: [1] an 8-way self-checking macro tour compiles and lands at
EXACTLY 8 mS (simple define, 1/3-arg macros, macro-in-macro, macro-as-
argument, elsif selection, undef+redefine, backslash continuation, and a
not-taken ifdef that would add 100 S if it leaked); [2] a nested include
chain resolves; [3] direct recursion is a clean error naming the macro;
[4] mutual recursion likewise; [5] legitimate same-macro nesting in
arguments still compiles (the false-positive regression pin).

Every SPICE deck starts with a title line (SPICE treats line 1 as the title!).
"""
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from _setup import VAF as OPENVAF, NG as NGSPICE

passed = failed = 0


def check(name, ok, detail=""):
    global passed, failed
    if ok:
        passed += 1
        print(f"  PASS  {name} {detail}")
    else:
        failed += 1
        print(f"  FAIL  {name} {detail}")


def compile_va(src):
    osdi = os.path.splitext(src)[0] + ".osdi"
    out = os.path.join(HERE, osdi)
    if os.path.exists(out):
        os.remove(out)
    r = subprocess.run([OPENVAF, src, "-o", osdi],
                       capture_output=True, text=True, timeout=120, cwd=HERE)
    return r.stdout + r.stderr, os.path.exists(out)


def op_current(osdi, model):
    deck = (f"* preproc {model}\nV1 a 0 DC 1\nN1 a 0 mm\n.model mm {model}\n"
            f".save i(V1)\n.op\n.control\npre_osdi {osdi}\nrun\nset numdgt=12\n"
            f"print i(V1)\n.endc\n.end\n")
    with open(os.path.join(HERE, "_pp.cir"), "w") as fh:
        fh.write(deck)
    r = subprocess.run([NGSPICE, "-b", "_pp.cir"],
                       capture_output=True, text=True, timeout=120, cwd=HERE)
    m = re.search(r"v1#branch\s+(-?[0-9.eE+-]+)", r.stdout + r.stderr)
    return float(m.group(1)) if m else float("nan")


print("[1] macro feature tour, self-checking (8 paths -> exactly 8 mS)")
out, ok = compile_va("preproc_demo.va")
if not ok:
    check("tour compiles", False, out.splitlines()[0] if out else "")
else:
    i = op_current("preproc_demo.osdi", "preproc")
    check("all 8 macro paths exact (and the dead ifdef stayed dead)",
          abs(i + 8e-3) < 1e-12, f"(I={i:.6g})")

print("[2] nested `include chain")
out, ok = compile_va("incchain_demo.va")
if not ok:
    check("include chain compiles", False, out.splitlines()[0] if out else "")
else:
    i = op_current("incchain_demo.osdi", "pinc")
    check("macro defined two includes deep resolves", abs(i + 1e-3) < 1e-12)

print("[3] direct macro recursion is a clean error (was a stack overflow)")
out, made = compile_va("_rec_direct.va")
check("clean error naming `LOOP",
      not made and "called recursively" in out and "LOOP" in out
      and "stack overflow" not in out)

print("[4] mutual macro recursion likewise")
out, made = compile_va("_rec_mutual.va")
check("clean error (A <-> B cycle)",
      not made and "called recursively" in out and "stack overflow" not in out)

print("[5] legitimate same-macro nesting in arguments still works")
# the QUAD path inside the tour is the pin; re-assert it explicitly
with open(os.path.join(HERE, "_argnest.va"), "w") as fh:
    fh.write('`include "disciplines.vams"\n'
             '`define TWICE(x) ((x)*2.0)\n'
             '`define QUAD(x) (`TWICE(`TWICE(x)))\n'
             'module pn(a,c); inout a,c; electrical a,c;\n'
             'analog I(a,c) <+ V(a,c)*(`QUAD(0.25e-3));\n'
             'endmodule\n')
out, made = compile_va("_argnest.va")
if not made:
    check("QUAD(x) = TWICE(TWICE(x)) compiles", False, out.splitlines()[0] if out else "")
else:
    i = op_current("_argnest.osdi", "pn")
    check("QUAD(0.25m) == 1 mS exactly (no false recursion)", abs(i + 1e-3) < 1e-12)

print(f"\n{'ALL PASS' if failed == 0 else 'FAILURES'}: {passed} passed, {failed} failed")
raise SystemExit(1 if failed else 0)
