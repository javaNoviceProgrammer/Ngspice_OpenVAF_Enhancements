#!/usr/bin/env python3
"""
verify_fmtdiag.py -- three compiler findings from the 2026-09-07 bug hunt
(docs/bug_hunts/2026-09-07_openvaf-r-language-semantics.md, F5/F6/F7), fixed by
Enhancement-578.

  [1] `%x`/`%X` (IEEE 1364-2005 17.1.1.2's synonyms of `%h`/`%H`) and `%t`/`%T`
      (the time conversion) were refused as "unexpected character". They compile
      now, take flags/width/precision like every other conversion, and print through
      ngspice exactly as C's `%x`/`%X` and, for `%t`, `%g` of the real argument.
  [2] a missing format argument was reported as "$display system task is missing
      an argument" whatever task was called; the report names the task now.
  [3] lint L026 ("this format string is not a literal") fired on
      `$strobe("name=%s k=%g", nm, k)` -- a literal format whose `%s` consumes a
      string operand -- whenever another argument followed. The check now walks the
      arguments the way the lowering does, stepping over the operands a literal's
      conversions consume, so only a genuine run-time format with operands warns.
  [4] `1.0 % 0.0` with a constant zero divisor folded to NaN and said nothing,
      while the integer form has been a compile error since Enhancement-333 and a
      deck-supplied zero is a run-time `$fatal`. The real form with a constant
      zero (a literal, `-0.0`, or a folded localparam) is a compile error now; an
      overridable parameter is still left to the run-time guard.
"""
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))          # the examples/ dir (holds _setup.py)
from _setup import VAF as OPENVAF
from _setup import NG as NGSPICE

HDR = '`include "disciplines.vams"\n'
ok_all = True
n_pass = 0
n_total = 0


def check(label, cond, detail=""):
    global ok_all, n_pass, n_total
    n_total += 1
    n_pass += bool(cond)
    ok_all = ok_all and bool(cond)
    print(f"  {'PASS' if cond else 'FAIL'}  {label}   {detail}")


def compile_va(name, text):
    """write name.va, compile it; return (rc, log)"""
    with open(os.path.join(HERE, name + ".va"), "w") as fh:
        fh.write(text)
    env = dict(os.environ, RAYON_NUM_THREADS="1", TERM="dumb")
    r = subprocess.run([OPENVAF, name + ".va", "-o", name + ".osdi"], cwd=HERE,
                       capture_output=True, text=True, timeout=300, env=env)
    return r.returncode, r.stdout + r.stderr


def ngspice_op(name, model):
    deck = (f"* {name}\n.model m {model}\nVs p 0 1\nN1 p 0 m\n.control\n"
            f"pre_osdi {name}.osdi\nop\nquit\n.endc\n.end\n")
    with open(os.path.join(HERE, "_o.cir"), "w") as fh:
        fh.write(deck)
    r = subprocess.run([NGSPICE, "-b", "_o.cir"], cwd=HERE, capture_output=True,
                       text=True, timeout=120)
    return r.stdout + r.stderr


def module(name, decls, body):
    return (HDR + f"module {name}(p,n); inout p,n; electrical p,n;\n{decls}\n"
            f"analog begin\n{body}\n  I(p,n) <+ V(p,n)*1e-3;\nend\nendmodule\n")


def first_error(log):
    for line in log.splitlines():
        if line.startswith("error"):
            return line.strip()
    return ""


# ---------------------------------------------------------------------------
print("[1] %x, %X, %t and %T are conversions")
rc, log = compile_va("hexfmt", module("hexfmt", "integer i; real x; string s;", """
  @(initial_step) begin
    i = 255; x = 2.5e-6;
    $strobe("A: %x %X %h %H", i, i, i, i);
    $strobe("B: %5x|%-6X|%08x", i, i, i);
    $strobe("C: t=%t T=%T %8.3t", x, x, x);
    $strobe("D: %t of an integer", i);
    $sformat(s, "E: %x-%t", i, x);
    $strobe("%s", s);
    $write("F: %X\\n", 48879);
  end"""))
check("a module using %x %X %t %T compiles", rc == 0, first_error(log))
check("... with no warning either", "warning" not in log, "")
out = ngspice_op("hexfmt", "hexfmt") if rc == 0 else ""
lines = [l.split(": ", 1)[1] for l in out.splitlines() if l.startswith("OSDI n1: ")]
check("%x and %X print lower/upper hex like %h/%H", "A: ff FF ff FF" in lines, lines[:1])
check("width, left-justify and zero-pad apply to %x/%X", "B:    ff|FF    |000000ff" in lines, lines[1:2])
check("%t prints the real time like %g, with width and precision", "C: t=2.5e-06 T=2.5e-06  2.5e-06" in lines, lines[2:3])
check("%t of an integer converts the integer", "D: 255 of an integer" in lines, lines[3:4])
check("$sformat takes the new conversions too", "E: ff-2.5e-06" in lines, lines[4:5])
check("$write %X", "F: BEEF" in lines, lines[5:6])
rc, log = compile_va("badv", module("badv", "real x;", '  @(initial_step) $strobe("%v", x);'))
check("%v (a net strength, digital only) is still refused", rc != 0 and "unexpected character v" in log, first_error(log))
check("... and the candidate list now names x, X, t and T", "'x', 'X', 't' or 'T'" in log, "")

# ---------------------------------------------------------------------------
print("[2] a missing format argument names the task that was called")
for task in ('$strobe("no %d")', '$write("no %d")', '$fatal(0, "no %d")',
             '$sformat(s, "no %d")', '$display("no %d")', '$strobe("%*d", 3)'):
    rc, log = compile_va("miss", module("miss", "string s;", f"  @(initial_step) {task};"))
    name = task.split("(")[0]
    check(f"{task} -> `{name} system task is missing an argument`",
          rc != 0 and f"{name} system task is missing an argument" in log, first_error(log))

# ---------------------------------------------------------------------------
print("[3] L026 only for a run-time format with operands")
DECL = 'parameter string nm = "abc"; parameter real k = 2.0; string s; string f;'
quiet = [
    ('$strobe("name=%s k=%g", nm, k);', "a literal with a %s operand then a %g operand"),
    ('$strobe("k=%g name=%s", k, nm);', "the %s operand last"),
    ('$strobe("%s %s", nm, nm);', "two %s operands"),
    ('$strobe("a=%s b=%g", s, k);', "a string VARIABLE as the %s operand"),
    ('$strobe("%s", nm, k);', "an extra argument after the format's operands is printed by type"),
    ('$strobe("a=%s %g", "lit", k);', "a literal as the %s operand"),
    ('$strobe("name=%s", nm);', "one operand, nothing after it"),
    ('$strobe("%*d|%-*.*f %s", 5, 3, 8, 2, k, nm);', "star widths consume their integers"),
    ('$strobe(f);', "a run-time string alone is printed, not a format"),
    ('$sformat(s, "%s=%g", nm, k);', "$sformat's destination is not a format"),
]
for stmt, why in quiet:
    rc, log = compile_va("l026", module("l026", DECL, f'  @(initial_step) begin s = "z"; f = "MARK %g"; {stmt} end'))
    check(f"quiet: {why}", rc == 0 and "L026" not in log,
          [l.strip() for l in log.splitlines() if "L026" in l][:1] or first_error(log))
loud = [
    ('$strobe(f, k);', "a run-time format with an operand"),
    ('$strobe("x=%g", k, f, k);', "a run-time string after a literal's operands, with an operand following"),
]
for stmt, why in loud:
    rc, log = compile_va("l026", module("l026", DECL, f'  @(initial_step) begin s = "z"; f = "MARK %g"; {stmt} end'))
    check(f"warns once: {why}", rc == 0 and log.count("L026") == 1 and "not a literal" in log,
          f"{log.count('L026')} occurrence(s)")

# ---------------------------------------------------------------------------
print("[4] a constant zero modulus divisor on the real path is a compile error")
MSG = "%: the second operand (the modulus divisor) is 0, which LRM 4.2.4 makes an error; the result would be NaN"
errs = [
    ("", "1.0 % 0.0", "a literal zero"),
    ("parameter real c14 = 1.0 % 0.0;", "c14", "inside a parameter default"),
    ("localparam real z = 0.0;", "1.0 % z", "a localparam zero (folded)"),
    ("localparam real z = 3.0 - 3.0;", "1.0 % z", "a localparam that folds to zero"),
    ("", "V(p,n) % 0.0", "a node voltage modulo a literal zero"),
    ("", "1.0 % -0.0", "negative zero"),
]
for decl, expr, why in errs:
    rc, log = compile_va("rem", module("rem", decl + "\nreal q;", f"  q = {expr};"))
    check(f"error: {why}", rc != 0 and MSG in log, first_error(log))
clean = [
    ("parameter real z = 0.0;", "1.0 % z", "an overridable parameter is a run-time value"),
    ("", "7.0 % 2.0", "a non-zero real divisor"),
    ("", "7 % 2", "a non-zero integer divisor"),
    ("", "V(p,n) % 1.0", "a node voltage modulo one"),
]
for decl, expr, why in clean:
    rc, log = compile_va("rem", module("rem", decl + "\nreal q;", f"  q = {expr};"))
    check(f"clean: {why}", rc == 0 and "error" not in log, first_error(log))
rc, log = compile_va("rem", module("rem", "real q;", "  q = 7 % 0;"))
check("the integer form keeps Enhancement-333's own message", rc != 0 and "integer remainder by zero" in log, first_error(log))
rc, log = compile_va("remrt", module("remrt", "parameter real z = 0.0;\nreal q;", "  q = 1.0 % z;"))
out = ngspice_op("remrt", "remrt") if rc == 0 else ""
check("... and the parameter zero is still the run-time $fatal naming LRM 4.2.4",
      "modulus divisor" in out and "LRM 4.2.4" in out and "raised $fatal" in out, "")

# ---------------------------------------------------------------------------
for f in os.listdir(HERE):
    if f.endswith((".osdi", ".va")) and not f.startswith("keep_") or f == "_o.cir":
        try:
            os.remove(os.path.join(HERE, f))
        except OSError:
            pass
print(f"\n{'ALL PASS' if ok_all else 'SOME FAILED'}: {n_pass}/{n_total} checks passed")
sys.exit(0 if ok_all else 1)
