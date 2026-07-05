#!/usr/bin/env python3
"""
verify_precedence.py -- verifies Enhancement-38 operator precedence, end-to-end
through the committed openvaf-r + ngspice.

`precedence_audit.va` covers every adjacent level pair of the Verilog-AMS
precedence table (LRM Table 4-2), associativity (all binary operators left to
right, the conditional right to left), and the unary-above-`**` corner. Each
failing check adds a distinct power of two to a score on a signal-flow output,
so v(out) == 0 <=> all checks pass and any nonzero value names the failure.

The audit found -- and E-38 fixed -- one observable defect: `%` bound tighter
than `*`/`/` (the LRM puts all three on one left-associative level), so `6*7%4`
parsed as `6*(7%4)` and evaluated to 18 instead of the LRM's `(6*7)%4 = 2`.
(`~^`/`^~` vs `^` was also split across levels -- provably unobservable for
xor/xnor chains, fixed for LRM exactness.)

Checks:
  1. all 28 precedence/associativity checks read exactly 0;
  2. the marquee fix case asserted directly: 6*7%4 == 2 (was 18).

Every SPICE deck starts with a title line (SPICE treats line 1 as the title!).
"""
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))          # the examples/ dir (holds _setup.py)
from _setup import VAF as OPENVAF, NG as NGSPICE


def run(deck, *names):
    with open(os.path.join(HERE, "_o.cir"), "w") as fh:
        fh.write(deck)
    out = subprocess.run([NGSPICE, "-b", "_o.cir"], cwd=HERE,
                         capture_output=True, text=True, timeout=120).stdout
    vals = {}
    for line in out.splitlines():
        for nm in names:
            if line.strip().lower().startswith(nm.lower() + " "):
                vals[nm] = float(line.split("=", 1)[1])
    return vals


def main():
    ok = True

    def check(label, cond, detail=""):
        nonlocal ok
        ok = ok and cond
        print(f"  {'PASS' if cond else 'FAIL'}  {label}   {detail}")

    r = subprocess.run([OPENVAF, "precedence_audit.va", "-o", "precedence_audit.osdi"],
                       cwd=HERE, capture_output=True, text=True)
    check("precedence_audit.va compiles", r.returncode == 0,
          "" if r.returncode == 0 else (r.stdout + r.stderr).strip().splitlines()[0])
    if r.returncode != 0:
        print("\nSOME FAILED")
        sys.exit(1)

    print("[1] all 28 precedence/associativity checks pass (score == 0)")
    v = run("* precedence audit\nn1 o m\n.model m prec_audit\nr1 o 0 1e6\n"
            ".control\npre_osdi precedence_audit.osdi\nop\nprint v(o)\n.endc\n.end\n",
            "v(o)")
    check("score == 0", v["v(o)"] == 0.0,
          f"score = {v['v(o)']:g}" + ("" if v["v(o)"] == 0 else "  <- failing-check bitmask"))

    print("[2] the marquee fix case, asserted directly")
    with open(os.path.join(HERE, "_m.va"), "w") as fh:
        fh.write('`include "disciplines.vams"\n'
                 "module prec_m(out); output out; voltage out;\n"
                 "  integer a;\n"
                 "  analog begin\n"
                 "    a = 6*7%4;\n"
                 "    V(out) <+ a;\n  end\nendmodule\n")
    r = subprocess.run([OPENVAF, "_m.va", "-o", "_m.osdi"],
                       cwd=HERE, capture_output=True, text=True)
    check("fix-case compiles", r.returncode == 0)
    v = run("* m\nn1 o m\n.model m prec_m\nr1 o 0 1e6\n"
            ".control\npre_osdi _m.osdi\nop\nprint v(o)\n.endc\n.end\n", "v(o)")
    check("6*7%4 == 2 (was 18)", v["v(o)"] == 2.0, f"v = {v['v(o)']:g}")

    print("\nALL PASS" if ok else "\nSOME FAILED")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
