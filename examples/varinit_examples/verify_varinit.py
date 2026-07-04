#!/usr/bin/env python3
"""
verify_varinit.py -- verifies Enhancement-43 variable initializers, end-to-end
through the committed openvaf-r + ngspice.

Declaration initializers are evaluated once at simulation start (LRM): an
unwritten variable reads its initializer, and event-updated state starts from
it. Scalars (incl. parameter-dependent constant expressions and strings)
already worked; E-43 completes the feature:

  * ARRAY declaration initializers, 1-D and multi-dimensional, split row-major
    into per-element leaves through the same machinery as array parameters --
    previously "expected real value but found real[0:N]" (once per element);
  * analog-function arguments WITHOUT a type declaration default to `real`
    (like the untyped return) -- previously `Type::Err` crashed the compiler
    at the first cast ("unknown cast found Real -> Err");
  * a `'{...}` initializer whose leaf count doesn't match the array (vars AND
    params) is a clean named diagnostic -- previously "invalid HIR: Missing"
    compiler crash.

Checks:
  1. scalar/param-dep/string inits read exactly; `y = 2*p+1` tracks p override
  2. init-once: `integer cnt = 10` + @(cross) counts 10 -> 10+N, never resets
  3. arrays: 1-D real + integer, 2-D, 3-D, param-dependent leaves = 66 + 4*s,
     tracking an `s` override; array element init + event update starts at 100
  4. function-local scalar + array initializers and an untyped `input v`
     argument evaluate exactly (used to be a compiler crash)
  5. wrong leaf count (too few / too many / scalar-on-array; var and param)
     rejected with "array initializer for 'x' has N elements but ..."

Every SPICE deck starts with a title line (SPICE treats line 1 as the title!).
"""
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from _setup import VAF as OPENVAF, NG as NGSPICE


def run(deck, *names):
    with open(os.path.join(HERE, "_v.cir"), "w") as fh:
        fh.write(deck)
    out = subprocess.run([NGSPICE, "-b", "_v.cir"], cwd=HERE,
                         capture_output=True, text=True, timeout=120).stdout
    vals = {}
    for line in out.splitlines():
        stripped = line.strip().lower()
        for nm in names:
            key = nm.lower()
            if (stripped.startswith(key + " ") or stripped.startswith(key + "=")) \
                    and nm not in vals:
                vals[nm] = float(line.split("=", 1)[1].strip())
    return vals


def op_deck(model, params="", extra=""):
    return (f"* E-43 {model}\nNDUT out 0 nm\nR1 out 0 1k\n"
            f".model nm {model}({params})\n"
            ".control\npre_osdi varinit_demo.osdi\nop\nprint v(out)\n"
            f"{extra}.endc\n.end\n")


def main():
    subprocess.run([OPENVAF, "varinit_demo.va", "-o",
                    os.path.join(HERE, "varinit_demo.osdi")],
                   cwd=HERE, check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    ok = True

    def check(label, got, want, tol=1e-9):
        nonlocal ok
        good = abs(got - want) < tol
        ok = ok and good
        print(f"  {'PASS' if good else 'FAIL'}  {label}   got {got:.6e}, want {want:.6e}")

    print("[1] scalar + param-dependent + string initializers")
    v = run(op_deck("vscalar"), "v(out)")
    check("x+n+y+100 (p=4)", v["v(out)"], 2.5 + 3 + 9 + 100)
    v = run(op_deck("vscalar", "p=10"), "v(out)")
    check("y tracks p=10", v["v(out)"], 2.5 + 3 + 21 + 100)

    print("[2] init-once: counter starts at 10, counts rising crossings")
    deck = ("* persist\nVs in 0 DC 0 SIN(0 1 100k)\nNDUT in out nm\nR1 out 0 1k\n"
            ".model nm vpersist\n.tran 0.5u 32u\n"
            ".control\npre_osdi varinit_demo.osdi\nrun\n"
            "print v(out)[0]\nmeas tran vfin FIND v(out) AT=31.5u\n.endc\n.end\n")
    v = run(deck, "v(out)[0]", "vfin")
    check("t=0 reads the initializer", v["v(out)[0]"], 10.0)
    check("counts from 10 (10+4 crossings)", v["vfin"], 14.0, 0.5)

    print("[3] array initializers: 1-D/2-D/3-D + param-dependent leaves")
    v = run(op_deck("varray"), "v(out)")
    check("66 + 4*s, s=2", v["v(out)"], 74.0)
    v = run(op_deck("varray", "s=5"), "v(out)")
    check("leaves track s=5", v["v(out)"], 86.0)
    deck = ("* arr persist\nVs in 0 DC 0 SIN(0 1 100k)\nNDUT in out nm\nR1 out 0 1k\n"
            ".model nm varraypersist\n.tran 0.5u 32u\n"
            ".control\npre_osdi varinit_demo.osdi\nrun\nprint v(out)[0]\n.endc\n.end\n")
    v = run(deck, "v(out)[0]")
    check("array element starts at its leaf (100)", v["v(out)[0]"], 100.0)

    print("[4] function-local scalar+array inits, untyped arg (was ICE)")
    v = run(op_deck("vfunc"), "v(out)")
    check("f(8) = 0.25 + 0.875*8", v["v(out)"], 7.25)

    print("[5] wrong leaf counts are clean errors (was a compiler crash)")
    bad_cases = [
        ("too few",   "real x[0:2] = '{1.0, 2.0};"),
        ("too many",  "real x[0:2] = '{1.0, 2.0, 3.0, 4.0};"),
        ("scalar on array", "real x[0:2] = 1.0;"),
        ("param too few", "parameter real [0:2] x = '{1.0, 2.0};"),
    ]
    for label, decl in bad_cases:
        src = ('`include "disciplines.vams"\nmodule bad(a, c);\n'
               f"  inout a, c; electrical a, c;\n  {decl}\n"
               "  analog V(a,c) <+ x[0];\nendmodule\n")
        with open(os.path.join(HERE, "_bad.va"), "w") as fh:
            fh.write(src)
        r = subprocess.run([OPENVAF, "_bad.va", "-o", "_bad.osdi"], cwd=HERE,
                           capture_output=True, text=True, timeout=60)
        good = (r.returncode != 0 and "array initializer for 'x' has" in r.stderr
                and "crashed" not in r.stdout + r.stderr)
        ok = ok and good
        print(f"  {'PASS' if good else 'FAIL'}  {label}: named diagnostic, no crash")

    print()
    print("ALL PASS" if ok else "SOME CHECKS FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
