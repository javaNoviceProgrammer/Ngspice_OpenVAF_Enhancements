#!/usr/bin/env python3
"""
verify_analysis.py -- verifies Enhancement-30 variadic `analysis(arg1, arg2, ...)`,
end-to-end through the committed openvaf-r + ngspice.

The LRM's `analysis()` takes a LIST of analysis-name strings and returns true if the
current analysis matches ANY of them. OpenVAF used to accept exactly one argument,
so `analysis("ac","tran","noise")` failed to compile. Now it is variadic (per-arg
results OR'd together).

`analysis_demo.va` is a conductance that is `g_static` at the DC operating point and
`g_dynamic` for the dynamic analyses, selected by one list-form call
`if (analysis("ac","tran","noise")) g = g_dynamic;`. We check:

  1. it COMPILES (the multi-argument list form used to be a hard error);
  2. DC   -> g_static   (none of the listed dynamic analyses match);
  3. AC   -> g_dynamic  (matches "ac");
  4. TRAN -> g_dynamic  (matches "tran");
  5. OR-not-sum: a separate model returns analysis("static","dc","ic") at .op, which
     must be exactly 1 (both "static" and "dc" hold -> OR clamps to 1, not 2/3).

Every SPICE deck starts with a title line (SPICE treats line 1 as the title!).
"""
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))          # the examples/ dir (holds _setup.py)
from _setup import VAF as OPENVAF, NG as NGSPICE
from _setup import check_both_solvers as _check_both_solvers; _check_both_solvers(__file__)  # verify under BOTH KLU and Sparse solvers


def build(va, osdi):
    r = subprocess.run([OPENVAF, va, "-o", os.path.join(HERE, osdi)],
                       cwd=HERE, capture_output=True, text=True)
    return r.returncode == 0, (r.stdout + r.stderr)


def ngspice(deck):
    with open(os.path.join(HERE, "_o.cir"), "w") as fh:
        fh.write(deck)
    subprocess.run([NGSPICE, "-b", "_o.cir"], cwd=HERE, capture_output=True, text=True)


def wr(deck, col=1):
    ngspice(deck)
    rows = [l.split() for l in open(os.path.join(HERE, "_o.txt")) if l.strip()]
    return float(rows[-1][col])


def ac_mag(deck):
    """Return |i(vm)| from a single-point AC print."""
    with open(os.path.join(HERE, "_o.cir"), "w") as fh:
        fh.write(deck)
    out = subprocess.run([NGSPICE, "-b", "_o.cir"], cwd=HERE,
                         capture_output=True, text=True).stdout
    for line in out.splitlines():
        if line.strip().lower().startswith("i(vm) "):
            re, im = line.split("=", 1)[1].split(",")
            return (float(re) ** 2 + float(im) ** 2) ** 0.5
    return None


def op_val(deck):
    with open(os.path.join(HERE, "_o.cir"), "w") as fh:
        fh.write(deck)
    out = subprocess.run([NGSPICE, "-b", "_o.cir"], cwd=HERE,
                         capture_output=True, text=True).stdout
    for line in out.splitlines():
        if line.strip().lower().startswith("i(vm) "):
            return float(line.split("=", 1)[1])
    return None


def main():
    ok = True

    def check(label, cond, detail=""):
        nonlocal ok
        ok = ok and cond
        print(f"  {'PASS' if cond else 'FAIL'}  {label}   {detail}")

    print("[1] the multi-argument list form compiles")
    built, log = build("analysis_demo.va", "analysis_demo.osdi")
    check("analysis_demo.va compiles", built, "" if built else log.strip().splitlines()[0])
    if not built:
        print("\nSOME FAILED")
        sys.exit(1)

    gs, gd = 1e-3, 4e-3
    inst = ("n1 a 0 am\n.model am analysis_demo(g_static=%g g_dynamic=%g)\n" % (gs, gd))

    print("[2] DC -> g_static (none of ac/tran/noise match)")
    v = wr("* dc\nvm a 0 dc 1\n" + inst +
           ".control\npre_osdi analysis_demo.osdi\ndc vm 1 1 1\nwrdata _o.txt i(vm)\n.endc\n.end\n")
    check("i(vm) == -g_static", abs(v + gs) < 1e-9, f"{v:.6e} vs {-gs:.6e}")

    print("[3] AC -> g_dynamic (matches \"ac\")")
    m = ac_mag("* ac\nvm a 0 dc 0.5 ac 1\n" + inst +
               ".control\npre_osdi analysis_demo.osdi\nac lin 1 1k 1k\nprint i(vm)\n.endc\n.end\n")
    check("|i(vm)| == g_dynamic", abs(m - gd) < 1e-9, f"{m:.6e} vs {gd:.6e}")

    print("[4] TRAN -> g_dynamic (matches \"tran\")")
    v = wr("* tran\nvm a 0 dc 1\n" + inst +
           ".control\npre_osdi analysis_demo.osdi\ntran 1m 2m\nwrdata _o.txt i(vm)\n.endc\n.end\n")
    check("i(vm) == -g_dynamic", abs(v + gd) < 1e-9, f"{v:.6e} vs {-gd:.6e}")

    print("[5] OR-not-sum: analysis(\"static\",\"dc\",\"ic\") at .op == 1")
    with open(os.path.join(HERE, "_or.va"), "w") as fh:
        fh.write('`include "disciplines.vams"\n'
                 'module analysis_or(a, b);\n  inout a, b; electrical a, b;\n'
                 '  analog I(a,b) <+ analysis("static","dc","ic") * 1e-3;\nendmodule\n')
    built, log = build("_or.va", "_or.osdi")
    check("analysis_or.va compiles", built, "" if built else log.strip().splitlines()[0])
    v = op_val("* or\nn1 a 0 am\n.model am analysis_or\nvm a 0 dc 0\n"
               ".control\npre_osdi _or.osdi\nop\nprint i(vm)\n.endc\n.end\n")
    check("i(vm) == -1e-3 (OR=1, not a sum)", v is not None and abs(v + 1e-3) < 1e-9,
          f"{v} (sum would be -2e-3 or -3e-3)")

    print("\nALL PASS" if ok else "\nSOME FAILED")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
