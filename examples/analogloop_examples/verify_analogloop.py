#!/usr/bin/env python3
"""
verify_analogloop.py -- verifies Enhancement-70: the behavioral (runtime)
loop audit, end-to-end through the committed openvaf-r + ngspice.

A 14-probe battery over the analog-block loop statements (the runtime
cousins of E-67's generate audit) found the machinery CORRECT -- every
compiled probe verified numerically exact -- with ONE diagnostic defect,
fixed here:

  an analog operator (ddt/idt/transition/...) inside a LOOP BODY was
  rejected -- correctly, per LRM 4.5.1 -- but with the message
  "not allowed in conditions", pointing users at the wrong construct
  (the validator lumped loop bodies into the conditional context). Loops
  now get their own validation context: the error reads "not allowed in
  loops" with an LRM 4.5.1 note and a hoist-or-generate hint, while the
  if/case message is unchanged.

Pinned as working (all values exact): for / while / do-while (E-19) /
repeat(n); nested loops; PARAMETER-dependent trip counts (honoring
model-card overrides at simulation time -- the exact complement of
E-67's generate restriction); solution-dependent while conditions;
loops over arrays; iterative algorithms (Newton sqrt converging to an
exact 4); contributions inside loops (they accumulate); loops inside
analog functions; `break` correctly rejected (not Verilog-A).

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
                       capture_output=True, text=True, timeout=300, cwd=HERE)
    return r.stdout + r.stderr, os.path.exists(out)


def op_ma(model, override=""):
    deck = (f"* loop {model}\nV1 a 0 DC 1\nN1 a 0 mm\n.model mm {model} {override}\n"
            f".save i(V1)\n.op\n.control\npre_osdi loops_demo.osdi\nrun\nset numdgt=12\n"
            f"print i(V1)\n.endc\n.end\n")
    with open(os.path.join(HERE, "_l.cir"), "w") as fh:
        fh.write(deck)
    r = subprocess.run([NGSPICE, "-b", "_l.cir"],
                       capture_output=True, text=True, timeout=120, cwd=HERE)
    m = re.search(r"v1#branch\s+(-?[0-9.eE+-]+)", r.stdout + r.stderr)
    return float(m.group(1)) * 1e3 if m else float("nan")


out, ok = compile_va("loops_demo.va")
if not ok:
    check("models compile", False, out.splitlines()[0] if out else "")
    raise SystemExit(1)

print("[1] all loop statements, exact conductances")
for mod, want, what in [
    ("lc_for", -10.0, "for (sum 1..4)"),
    ("lc_while", -10.0, "while"),
    ("lc_dowhile", -10.0, "do-while (E-19 pin)"),
    ("lc_repeat", -10.0, "repeat(10)"),
    ("lc_nested", -12.0, "nested for (3x4)"),
    ("lc_array", -10.0, "loop over an array"),
    ("lc_newton", -4.0, "iterative Newton sqrt(16) == 4 exactly"),
    ("lc_contrib", -3.0, "contribution inside a loop accumulates"),
    ("lc_fn", -5.0, "loop in an analog function (5!/24k)"),
]:
    got = op_ma(mod)
    check(what, abs(got - want) < 1e-9, f"({got:.9g} mA)")

print("[2] parameter-dependent trip count honors model-card overrides")
check("default n=10 -> 10 mS", abs(op_ma("lc_param") + 10.0) < 1e-9)
check("model-card n=25 -> 25 mS (simulation-time binding)",
      abs(op_ma("lc_param", "n=25") + 25.0) < 1e-9)

print("[3] the fixed diagnostic: analog operator in a loop names LOOPS")
out, made = compile_va("_ddt_in_loop.va")
check("rejected with 'not allowed in loops' + LRM 4.5.1 note",
      not made and "not allowed in loops" in out and "4.5.1" in out
      and "not allowed in conditions" not in out)

print(f"\n{'ALL PASS' if failed == 0 else 'FAILURES'}: {passed} passed, {failed} failed")
raise SystemExit(1 if failed else 0)
