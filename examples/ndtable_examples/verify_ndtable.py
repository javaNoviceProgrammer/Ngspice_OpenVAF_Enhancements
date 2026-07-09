#!/usr/bin/env python3
"""
verify_ndtable.py -- verifies Enhancement-40 N-dimensional $table_model, end-to-end
through the committed openvaf-r + ngspice.

$table_model was hard-capped at 3 dimensions by its signature list (a 4-D call
errored "expected at most 2 arguments but found 6") even though the grid reader
and the recursive multilinear interpolation were fully dimension-general. E-40
makes the builtin variadic (shape-synthesised signatures + shape-based lowering
dispatch, which also resolves the 5-argument arity ambiguity 3-D+ctrl vs 4-D).

The demo grids hold MULTILINEAR functions, which multilinear interpolation
reproduces EXACTLY at any off-grid point -- so every check asserts analytic
equality:

  1. 4-D with control string:    f4(1.5,0.25,0.75,0.4) = 7.9625
  2. 4-D without control string  (the ambiguous 5-argument arity)
  3. 5-D with control string:    f5(.5,.5,.5,.5,1.0) = 6.5625
  4. parameter-swept 4-D lookup stays exact at a second point
  5. regression lock: 1-D inline and 2-D file forms still exact
     (also covered by table_model/mdtable/cubic_table suites).

Every SPICE deck starts with a title line (SPICE treats line 1 as the title!).
"""
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))          # the examples/ dir (holds _setup.py)
from _setup import VAF as OPENVAF, NG as NGSPICE
from _setup import check_both_solvers as _check_both_solvers; _check_both_solvers(__file__)  # verify under BOTH KLU and Sparse solvers

f4 = lambda x, y, z, w: 2 + x + 2*y + 3*z + 4*w + x*y*z*w
f5 = lambda a, b, c, d, e: 1 + a + 2*b + 3*c + 4*d + 0.5*e + a*b*c*d*e


def compile_va(src, dst):
    r = subprocess.run([OPENVAF, src, "-o", os.path.join(HERE, dst)],
                       cwd=HERE, capture_output=True, text=True)
    return r.returncode == 0 and os.path.isfile(os.path.join(HERE, dst)), \
        (r.stdout + r.stderr)


def op_current(deck):
    with open(os.path.join(HERE, "_o.cir"), "w") as fh:
        fh.write(deck)
    out = subprocess.run([NGSPICE, "-b", "_o.cir"], cwd=HERE,
                         capture_output=True, text=True, timeout=120).stdout
    for line in out.splitlines():
        if line.strip().lower().startswith("i(vin) "):
            return float(line.split("=", 1)[1])
    return None


def main():
    ok = True

    def check(label, cond, detail=""):
        nonlocal ok
        ok = ok and cond
        print(f"  {'PASS' if cond else 'FAIL'}  {label}   {detail}")

    print("[1] 4-D $table_model compiles (used to error at the signature cap)")
    built, log = compile_va("ndtable_demo.va", "ndtable_demo.osdi")
    check("openvaf-r ndtable_demo.va", built,
          "" if built else log.strip().splitlines()[0])
    if not built:
        print("\nSOME FAILED")
        sys.exit(1)

    print("[2] 4-D lookups are analytically exact (multilinear grid)")
    for x, y, z, w in ((1.5, 0.25, 0.75, 0.4), (0.3, 0.9, 0.1, 0.45)):
        exp = f4(x, y, z, w)
        i = op_current("* nd4\nvin a 0 dc 1\nn1 a 0 dm\n"
                       f".model dm ndtable_demo(x={x} y={y} z={z} w={w})\n"
                       ".control\npre_osdi ndtable_demo.osdi\nop\nprint i(vin)\n.endc\n.end\n")
        check(f"f4({x},{y},{z},{w}) == {exp:g}", abs(i + 1e-3 * exp) < 1e-12,
              f"i = {i:.9e}")

    print("[3] 4-D without control string (the ambiguous 5-argument arity)")
    with open(os.path.join(HERE, "_n4.va"), "w") as fh:
        fh.write('`include "disciplines.vams"\n'
                 "module nd4b(a,c); inout a,c; electrical a,c;\n  real v;\n"
                 "  analog begin\n"
                 '    v = $table_model(1.5, 0.25, 0.75, 0.4, "grid4.tbl");\n'
                 "    I(a,c) <+ 1e-3*v*V(a,c);\n  end\nendmodule\n")
    built, log = compile_va("_n4.va", "_n4.osdi")
    check("compiles", built, "" if built else log.strip().splitlines()[0])
    i = op_current("* n4b\nvin a 0 dc 1\nn1 a 0 dm\n.model dm nd4b\n"
                   ".control\npre_osdi _n4.osdi\nop\nprint i(vin)\n.endc\n.end\n")
    check("value exact", abs(i + 1e-3 * f4(1.5, 0.25, 0.75, 0.4)) < 1e-12, f"i = {i:.9e}")

    print("[4] 5-D with control string")
    with open(os.path.join(HERE, "_n5.va"), "w") as fh:
        fh.write('`include "disciplines.vams"\n'
                 "module nd5(a,c); inout a,c; electrical a,c;\n  real v;\n"
                 "  analog begin\n"
                 '    v = $table_model(0.5, 0.5, 0.5, 0.5, 1.0, "grid5.tbl", "1L");\n'
                 "    I(a,c) <+ 1e-3*v*V(a,c);\n  end\nendmodule\n")
    built, log = compile_va("_n5.va", "_n5.osdi")
    check("compiles", built, "" if built else log.strip().splitlines()[0])
    i = op_current("* n5\nvin a 0 dc 1\nn1 a 0 dm\n.model dm nd5\n"
                   ".control\npre_osdi _n5.osdi\nop\nprint i(vin)\n.endc\n.end\n")
    check("value exact", abs(i + 1e-3 * f5(.5, .5, .5, .5, 1.0)) < 1e-12, f"i = {i:.9e}")

    print("[5] regression lock: 1-D inline form still exact")
    with open(os.path.join(HERE, "_n1.va"), "w") as fh:
        fh.write('`include "disciplines.vams"\n'
                 "module nd1(a,c); inout a,c; electrical a,c;\n  real v;\n"
                 "  analog begin\n"
                 "    v = $table_model(1.5, '{0,0, 1,1, 2,4, 3,9});\n"
                 "    I(a,c) <+ 1e-3*v*V(a,c);\n  end\nendmodule\n")
    built, log = compile_va("_n1.va", "_n1.osdi")
    check("compiles", built, "" if built else log.strip().splitlines()[0])
    i = op_current("* n1\nvin a 0 dc 1\nn1 a 0 dm\n.model dm nd1\n"
                   ".control\npre_osdi _n1.osdi\nop\nprint i(vin)\n.endc\n.end\n")
    check("interp(1.5) == 2.5", abs(i + 1e-3 * 2.5) < 1e-12, f"i = {i:.9e}")

    print("\nALL PASS" if ok else "\nSOME FAILED")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
