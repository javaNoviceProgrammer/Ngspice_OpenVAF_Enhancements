#!/usr/bin/env python3
"""Enhancement-648: an event control under a non-constant condition is refused
(2026-09-16 hunt, F4).

LRM 5.8: "Event control statements (e.g.: timer, cross) cannot be used inside
conditional statements unless the conditional expression is a constant
expression." Only cross/above were checked (LRM 5.10.3.1's own rule); an
initial_step, final_step or timer under `if (V(p,n) > 0)` compiled without a
word, and whether its block ever ran depended on the solver's first guess --
`if (V(p,n) > 0) @(initial_step) k = k + 1;` left k = 0 at an operating point
where V = 1.

Now every event form under a non-constant `if`/`case` is refused with the LRM
5.8 sentence; a literal, a parameter, a string-parameter compare, `analysis()`
or `$temperature` condition is constant and stays allowed; a runtime loop is
not a conditional statement (5.8 names none) and stays allowed for the global
events and timers, while cross/above keep 5.10.3.1's loop rule.
"""
import os
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from _setup import NG as NGSPICE, VAF  # noqa: E402
from _setup import check_both_solvers as _check_both_solvers; _check_both_solvers(__file__)  # noqa: E402

checks = passed = 0
WORK = tempfile.mkdtemp(prefix="eventcond_")
HDR = '`include "disciplines.vams"\n'


def check(label, ok, detail=""):
    global checks, passed
    checks += 1
    passed += bool(ok)
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  [{detail}]" if detail else ""))
    return ok


def compile_src(src, tag):
    path = os.path.join(WORK, f"{tag}.va")
    with open(path, "w") as f:
        f.write(HDR + src)
    r = subprocess.run([VAF, path, "-o", os.path.join(WORK, f"{tag}.osdi")], capture_output=True, text=True)
    return r.returncode == 0, r.stdout + r.stderr


def run(deck, ctl, tag, osdi):
    path = os.path.join(WORK, f"{tag}.cir")
    with open(path, "w") as f:
        f.write(f"* eventcond {tag}\n{deck}\n.control\nset noinit\nset numdgt=12\npre_osdi {osdi}.osdi\n{ctl}\nquit\n.endc\n.end\n")
    p = subprocess.run([NGSPICE, "-b", os.path.basename(path)], capture_output=True, text=True,
                       timeout=180, cwd=WORK, stdin=subprocess.DEVNULL)
    return p.stdout + p.stderr


MOD = lambda name, body: f"module {name}(p,n); inout p,n; electrical p,n;\n{body}\nendmodule\n"
DECK = lambda model: f"v1 1 0 1\n.model {model} {model}\nna1 1 0 {model}"
TAIL = "@(final_step) $strobe(\"k=%d\", k); I(p,n) <+ V(p,n); end"
LRM58 = "help: LRM 5.8: an event control statement cannot be used inside a conditional statement unless the condition is a constant expression"


def refused(label, body, form, tag):
    ok, out = compile_src(MOD("m", body), tag)
    return check(label, not ok and f"{form} is not allowed inside a conditional" in out and LRM58 in out
                 and out.count("error:") == 2, (out.strip().splitlines() or [""])[0][:70])


def accepted(label, body, tag, want_k):
    ok, out = compile_src(MOD("m", body), tag)
    o = run(DECK("m"), "op", tag, tag) if ok else ""
    m = re.search(r"k=(-?\d+)", o)
    return check(label, ok and m is not None and int(m.group(1)) == want_k,
                 (out.strip().splitlines() or [""])[0][:70] if not ok else f"k={m.group(1) if m else '?'}")


# ---------------------------------------------------------------- refused
refused("[1] @(initial_step) under if (V(p,n) > 0) -- the hunt's reproducer",
        "integer k; analog begin if (V(p,n) > 0) @(initial_step) k = k + 1; " + TAIL, "@(initial_step)", "r1")
refused("[2] @(timer) under if (V(p,n) > 0)",
        "integer k; analog begin if (V(p,n) > 0) @(timer(1e-6, 1e-6)) k = k + 1; " + TAIL, "@(timer)", "r2")
refused("[3] @(final_step) under case (V(p,n) > 0.5)",
        "integer k; analog begin case (V(p,n) > 0.5) 1: @(final_step) k = k + 1; default: ; endcase " + TAIL, "@(final_step)", "r3")
refused("[4] under a module variable written from a node voltage",
        "integer k; real x; analog begin x = V(p,n); if (x > 0) @(initial_step) k = k + 1; " + TAIL, "@(initial_step)", "r4")
refused("[5] an event under a constant if nested in a non-constant one",
        "parameter integer en = 1; integer k; analog begin if (V(p,n) > 0) if (en) @(timer(1e-6)) k = k + 1; " + TAIL, "@(timer)", "r5")
refused("[6] `initial_step or final_step` under if (V(p,n) > 0)",
        "integer k; analog begin if (V(p,n) > 0) @(initial_step or final_step) k = k + 1; " + TAIL, "an event control", "r6")
ok, out = compile_src(MOD("m", "integer k; analog begin if (V(p,n) > 0) @(cross(V(p,n) - 0.5, +1)) k = k + 1; " + TAIL), "r7")
check("[7] @(cross) under if (V(p,n) > 0) keeps LRM 5.10.3.1's own message",
      not ok and "@(cross) is not allowed inside a conditional" in out and "LRM 5.10.3.1" in out and LRM58 not in out)
ok, out = compile_src(MOD("m", "integer k, i; analog begin i = 0; while (i < 2) begin @(cross(V(p,n) - 0.5, +1)) k = k + 1; i = i + 1; end " + TAIL), "r8")
check("[8] @(cross) in a while loop is still refused (5.10.3.1)", not ok and "is not allowed inside a repeat/while/for loop" in out)

# ---------------------------------------------------------------- accepted: constant conditions
accepted("[9] under if (1) the event fires (k=1)", "integer k; analog begin if (1) @(initial_step) k = k + 1; " + TAIL, "a1", 1)
accepted("[10] under a parameter condition (k=1)", "parameter integer en = 1; integer k; analog begin if (en) @(initial_step) k = k + 1; " + TAIL, "a2", 1)
accepted("[11] under a string-parameter compare (k=1)", "parameter string mode = \"a\"; integer k; analog begin if (mode == \"a\") @(initial_step) k = k + 1; " + TAIL, "a3", 1)
accepted("[12] under analysis(\"dc\") at an operating point (k=1)", "integer k; analog begin if (analysis(\"dc\")) @(initial_step) k = k + 1; " + TAIL, "a4", 1)
accepted("[13] under a $temperature compare (k=1)", "integer k; analog begin if ($temperature > 300) @(initial_step) k = k + 1; " + TAIL, "a5", 1)
accepted("[14] in a runtime for loop with constant bounds (k=2; 5.8 names conditionals only)",
         "integer k, i; analog begin for (i = 0; i < 2; i = i + 1) @(initial_step) k = k + 1; " + TAIL, "a6", 2)
accepted("[15] the recommended shape: the event at the top, the condition inside (k=1)",
         "integer k; analog begin @(initial_step) if (V(p,n) > -1) k = k + 1; " + TAIL, "a7", 1)

print(f"\n{passed}/{checks} checks passed")
sys.exit(0 if passed == checks else 1)
