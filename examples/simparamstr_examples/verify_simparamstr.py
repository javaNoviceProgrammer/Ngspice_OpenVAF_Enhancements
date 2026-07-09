#!/usr/bin/env python3
"""
verify_simparamstr.py -- verifies Enhancement-25 `$simparam$str(name)`, end-to-end
through version11's own openvaf-r + ngspice (which also required an ngspice-side
change: OSDIload now exposes string simulator parameters).

`simparamstr_demo.va` sets its conductance from `$simparam$str("analysis_name")`
(read into a string variable and compared): g_dc in dc/op, g_ac in ac, g_tran in
tran. Running each analysis and checking the current confirms the correct string
is returned in each case -- which never worked before (the builtin was mis-typed,
the runtime lookup was bugged, and ngspice exposed no string parameters).

Every SPICE deck starts with a title line (SPICE treats line 1 as the title!).
"""
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))          # repo root
from _setup import VAF as OPENVAF, NG as NGSPICE
from _setup import check_both_solvers as _check_both_solvers; _check_both_solvers(__file__)  # verify under BOTH KLU and Sparse solvers

G_DC, G_AC, G_TRAN = 1.0e-3, 2.0e-3, 3.0e-3


def ngspice(deck):
    with open(os.path.join(HERE, "_o.cir"), "w") as fh:
        fh.write(deck)
    subprocess.run([NGSPICE, "-b", "_o.cir"], cwd=HERE, capture_output=True, text=True)
    with open(os.path.join(HERE, "_o.txt")) as fh:
        return float(fh.read().split()[-1])


def dc_conductance():
    # I = g_dc * V at V=1  ->  |i(vin)| = g_dc
    deck = ("* simparamstr dc\nvin a 0 dc 1\nn1 a 0 dm\n.model dm simparamstr_demo\n"
            ".control\npre_osdi simparamstr_demo.osdi\ndc vin 1 1 1\n"
            "wrdata _o.txt i(vin)\n.endc\n.end\n")
    return -ngspice(deck)


def ac_conductance():
    deck = ("* simparamstr ac\nvin a 0 dc 0.4 ac 1\nn1 a 0 dm\n.model dm simparamstr_demo\n"
            ".control\npre_osdi simparamstr_demo.osdi\nac lin 1 1 1\n"
            "wrdata _o.txt mag(i(vin))\n.endc\n.end\n")
    return ngspice(deck)


def tran_conductance():
    deck = ("* simparamstr tran\nvin a 0 dc 1\nn1 a 0 dm\n.model dm simparamstr_demo\n"
            ".control\npre_osdi simparamstr_demo.osdi\ntran 1u 2u\n"
            "wrdata _o.txt i(vin)\n.endc\n.end\n")
    return -ngspice(deck)


def main():
    subprocess.run([OPENVAF, "simparamstr_demo.va", "-o", "simparamstr_demo.osdi"],
                   cwd=HERE, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    checks = [
        ('$simparam$str("analysis_name") == "dc"   (op/dc)', dc_conductance(),   G_DC),
        ('$simparam$str("analysis_name") == "ac"   (ac)',    ac_conductance(),   G_AC),
        ('$simparam$str("analysis_name") == "tran" (tran)',  tran_conductance(), G_TRAN),
    ]

    ok = True
    print(f"{'check':50} {'g got':>10} {'expected':>10}  result")
    for label, got, exp in checks:
        good = abs(got - exp) < 1e-9
        ok = ok and good
        print(f"{label:50} {got:>10.5g} {exp:>10.5g}  {'PASS' if good else 'FAIL'}")

    print("\nALL PASS" if ok else "\nSOME FAILED")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
