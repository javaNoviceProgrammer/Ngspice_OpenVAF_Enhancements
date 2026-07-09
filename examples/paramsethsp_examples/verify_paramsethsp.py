#!/usr/bin/env python3
"""
verify_paramsethsp.py -- verifies Enhancement-44 paramset hierarchical system
parameters, end-to-end through the committed openvaf-r + ngspice.

Per LRM 6.4 a paramset may set hierarchical system parameters alongside its
target-parameter bindings (`.$mfactor = 8;` -- the canonical quad-device
idiom). Previously that line was a parse error ("unexpected token system
function identifier"). E-44 parses it, stores it as a hidden localparam in the
E-21 twin module (`$paramset$mfactor`, so ngspice's `m=` alias keeps pointing
at the instance value), and composes it with the instance-level value in
`sim_back` -- rewriting every use of the system parameter: explicit `$mfactor`
reads, the DAE builder's automatic flow scaling, its noise scaling, and the
derivative code. Composition follows the LRM hierarchy rules: multiplicative
for $mfactor/$hflip/$vflip, additive for $xposition/$yposition/$angle.

Checks (all exact):
  1. quad idiom: `.r = 2e3; .$mfactor = 8;` -> 250 ohm effective (4 mA at 1 V)
  2. netlist m COMPOSES: quad + m=3 -> effective 24 -> 12 mA
  3. all six HSPs read composed values; instance overrides compose on top
     (multiplicative m/flips, additive positions/angle)
  4. the override expression may reference the paramset's own card parameters
     (`.$mfactor = nf;`), tracking nf overrides from the model card
  5. noise scales with the paramset multiplicity exactly like netlist m=
  6. `.$vt = 1;` (not a hierarchical system parameter) is a clean diagnostic
  7. plain paramsets (no HSPs) are unchanged

Every SPICE deck starts with a title line (SPICE treats line 1 as the title!).
"""
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from _setup import VAF as OPENVAF, NG as NGSPICE
from _setup import check_both_solvers as _check_both_solvers; _check_both_solvers(__file__)  # verify under BOTH KLU and Sparse solvers


def run(deck, *names):
    with open(os.path.join(HERE, "_p.cir"), "w") as fh:
        fh.write(deck)
    out = subprocess.run([NGSPICE, "-b", "_p.cir"], cwd=HERE,
                         capture_output=True, text=True, timeout=120).stdout
    vals = {}
    for line in out.splitlines():
        stripped = line.strip().lower()
        for nm in names:
            if stripped.startswith(nm.lower() + " ") and nm not in vals:
                vals[nm] = float(line.split("=", 1)[1].strip())
    return vals


def deck_i(model, inst_extra=""):
    return (f"* E-44 {model}\nVs in 0 DC 1\nNDUT in 0 nm {inst_extra}\n"
            f".model nm {model}\n"
            ".control\npre_osdi paramsethsp_demo.osdi\nop\nprint i(vs)\n.endc\n.end\n")


def deck_v(model, inst_extra=""):
    return (f"* E-44 {model}\nNDUT out 0 nm {inst_extra}\nR1 out 0 1G\n"
            f".model nm {model}\n"
            ".control\npre_osdi paramsethsp_demo.osdi\nop\nprint v(out)\n.endc\n.end\n")


def main():
    subprocess.run([OPENVAF, "paramsethsp_demo.va", "-o", "paramsethsp_demo.osdi"],
                   cwd=HERE, check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    ok = True

    def check(label, got, want, tol=1e-9):
        nonlocal ok
        good = abs(got - want) < tol
        ok = ok and good
        print(f"  {'PASS' if good else 'FAIL'}  {label}   got {got:.6e}, want {want:.6e}")

    print("[1] quad idiom: .r=2e3 + .$mfactor=8 -> 250 ohm effective")
    v = run(deck_i("quad"), "i(vs)")
    check("i(vs) = -4mA", v["i(vs)"], -4e-3, 1e-12)

    print("[2] netlist m composes multiplicatively: quad + m=3 -> 24x")
    v = run(deck_i("quad", "m=3"), "i(vs)")
    check("i(vs) = -12mA", v["i(vs)"], -12e-3, 1e-12)

    print("[3] all six HSPs compose (reads)")
    v = run(deck_v("hspset"), "v(out)")
    check("8000+200+10+45-0.1-0.01", v["v(out)"], 8254.89, 1e-6)
    v = run(deck_v("hspset", "m=3 _xposition=5 _hflip=-1"), "v(out)")
    check("24000+700+10+45+0.1-0.01 (x m, + pos, x flip)",
          v["v(out)"], 24755.09, 1e-6)

    print("[4] override expr over card params: .$mfactor = nf")
    v = run(deck_i("byfingers"), "i(vs)")
    check("nf=5 default -> -5mA", v["i(vs)"], -5e-3, 1e-12)
    v = run(deck_i("byfingers(nf=2)"), "i(vs)")
    check("nf=2 card -> -2mA", v["i(vs)"], -2e-3, 1e-12)

    print("[5] noise scales with paramset multiplicity")
    deck = ("* noise\nVs in 0 DC 0 AC 1\nR2 in 0 1k\nNDUT out 0 nm\nR1 out 0 1G\n"
            ".model nm nquad\n.control\npre_osdi paramsethsp_demo.osdi\n"
            "noise v(out) vs lin 1 1k 1k\nprint onoise_spectrum\n.endc\n.end\n")
    v = run(deck, "onoise_spectrum")
    check("PSD x4, Z/4: onoise = 5e-4", v["onoise_spectrum"], 5e-4, 1e-9)

    print("[6] non-HSP system function rejected cleanly")
    src = ('`include "disciplines.vams"\nmodule rb(a, c);\n'
           "  inout a, c; electrical a, c;\n  analog I(a,c) <+ V(a,c)/1e3;\nendmodule\n"
           "paramset pbad rb;\n  .$vt = 1.0;\nendparamset\n")
    with open(os.path.join(HERE, "_bad.va"), "w") as fh:
        fh.write(src)
    r = subprocess.run([OPENVAF, "_bad.va", "-o", "_bad.osdi"], cwd=HERE,
                       capture_output=True, text=True, timeout=60)
    good = (r.returncode != 0
            and "'$vt' is not a hierarchical system parameter" in r.stderr
            and "crashed" not in r.stdout + r.stderr)
    ok = ok and good
    print(f"  {'PASS' if good else 'FAIL'}  .$vt rejected with named diagnostic")

    print()
    print("ALL PASS" if ok else "SOME CHECKS FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
