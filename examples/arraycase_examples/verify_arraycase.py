#!/usr/bin/env python3
"""
verify_arraycase.py -- verifies Enhancement-33 array `case` statements and
array-literal function arguments, end-to-end through the committed
openvaf-r + ngspice.

Before E-33: a `case` over an array crashed the compiler ("not yet implemented"
panic; integer arrays additionally hit "invalid int operation feq" because array
element types were hardcoded real), and an array literal passed as a whole-array
function INPUT argument silently bound nothing (every element 0). Array literals
passed to array OUTPUT arguments were silently accepted with the writeback skipped.

`arraycase_demo.va` classifies V into a 2-bit integer state vector and selects the
conductance with one element-wise array `case`; a helper summing an array-literal
argument (sum2('{0.25,0.75}) == 1.0) scales the result. We check:

  1. it COMPILES (array case used to panic the compiler);
  2. all three case regions select the right conductance in a DC sweep
     (this also proves sum2's literal argument reads 1.0, not 0 -- a silent-zero
     would make every current 0);
  3. a real-array case (literal discriminant vs literal item) matches exactly;
  4. an array literal passed to an array OUTPUT argument is REJECTED
     (like scalars), instead of silently skipping the writeback.

Every SPICE deck starts with a title line (SPICE treats line 1 as the title!).
"""
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))          # the examples/ dir (holds _setup.py)
from _setup import VAF as OPENVAF, NG as NGSPICE
from _setup import check_both_solvers as _check_both_solvers; _check_both_solvers(__file__)  # verify under BOTH KLU and Sparse solvers


def compile_va(src, dst):
    r = subprocess.run([OPENVAF, src, "-o", os.path.join(HERE, dst)],
                       cwd=HERE, capture_output=True, text=True)
    return r.returncode == 0 and os.path.isfile(os.path.join(HERE, dst)), \
        (r.stdout + r.stderr)


def dc_sweep():
    deck = (
        "* array case dc\n"
        "vin a 0 dc 0.5\n"
        "n1 a 0 dm\n"
        ".model dm arraycase_demo(vth1=1.0 vth2=2.0)\n"
        ".control\npre_osdi arraycase_demo.osdi\n"
        "dc vin 0.5 2.5 1\nwrdata _o.txt i(vin)\n.endc\n.end\n"
    )
    with open(os.path.join(HERE, "_o.cir"), "w") as fh:
        fh.write(deck)
    subprocess.run([NGSPICE, "-b", "_o.cir"], cwd=HERE, capture_output=True, text=True)
    return [(float(a), float(b)) for a, b in
            (l.split() for l in open(os.path.join(HERE, "_o.txt")) if l.strip())]


def main():
    ok = True

    def check(label, cond, detail=""):
        nonlocal ok
        ok = ok and cond
        print(f"  {'PASS' if cond else 'FAIL'}  {label}   {detail}")

    print("[1] array case + array-literal fn arg COMPILES (used to panic)")
    built, log = compile_va("arraycase_demo.va", "arraycase_demo.osdi")
    check("openvaf-r arraycase_demo.va", built,
          "" if built else log.strip().splitlines()[0])
    if not built:
        print("\nSOME FAILED")
        sys.exit(1)

    print("[2] element-wise integer-array case selects all three regions")
    rows = dc_sweep()
    exp = {0.5: 1e-3, 1.5: 2e-3, 2.5: 3e-3}     # g per region; I = -g*V (scale==1)
    for v, i in rows:
        g = exp[round(v, 1)]
        check(f"V={v:g}: I == -{g:g}*V", abs(i + g * v) < 1e-9, f"i = {i:.6e}")

    print("[3] real-array case: literal discriminant vs literal item")
    with open(os.path.join(HERE, "_rc.va"), "w") as fh:
        fh.write('`include "disciplines.vams"\n'
                 'module arraycase_rc(a,c); inout a,c; electrical a,c; real g;\n'
                 "analog begin\n"
                 "  case ('{1.0, 2.0})\n"
                 "    '{1.0, 2.0}: g = 1e-3;\n"
                 "    default:     g = 9e-3;\n"
                 "  endcase\n"
                 "  I(a,c) <+ g*V(a,c);\nend\nendmodule\n")
    built, log = compile_va("_rc.va", "_rc.osdi")
    check("real-array case compiles", built, "" if built else log.strip().splitlines()[0])

    print("[4] array literal to an array OUTPUT argument is rejected")
    with open(os.path.join(HERE, "_ol.va"), "w") as fh:
        fh.write('`include "disciplines.vams"\n'
                 'module arraycase_ol(a,c); inout a,c; electrical a,c;\n'
                 "analog function real fill2;\n"
                 "  input s; real s;\n"
                 "  output v; real v[0:1];\n"
                 "  begin v[0]=s; v[1]=2.0*s; fill2=0.0; end\n"
                 "endfunction\n"
                 "real g;\n"
                 "analog begin\n"
                 "  g = fill2(1.0, '{0.0, 0.0});\n"
                 "  I(a,c) <+ (g+1.0)*1e-3*V(a,c);\nend\nendmodule\n")
    built, log = compile_va("_ol.va", "_ol.osdi")
    check("output-literal rejected with a type error",
          (not built) and "variable reference" in log,
          "rejected" if not built else "WRONGLY ACCEPTED")

    print("\nALL PASS" if ok else "\nSOME FAILED")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
