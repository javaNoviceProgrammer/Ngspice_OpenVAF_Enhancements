#!/usr/bin/env python3
"""
verify_arrayout.py -- verifies Enhancement-20 array OUTPUT / INOUT arguments to
analog functions, end-to-end through version11's own openvaf-r + ngspice.

`arrayout_demo` builds a 4-tap geometric array via an OUTPUT array argument
(`make_taps`), normalizes it in place via an INOUT array argument (`normalize`),
and uses the sum of the normalized taps as its gain. That sum is 1 by
construction for any `ratio`, so V(out) = V(in) -- but only if both writebacks
(output fill + inout normalize) actually reach the caller's array. We sweep
`ratio` (overridden per .model) and check V(out) == V(in).

Every SPICE deck starts with a title line (SPICE treats line 1 as the title!).
"""
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))          # repo root
from _setup import VAF as OPENVAF, NG as NGSPICE
from _setup import check_both_solvers as _check_both_solvers; _check_both_solvers(__file__)  # verify under BOTH KLU and Sparse solvers


def vout(ratio, vin=1.0):
    deck = (f"* arrayout ratio={ratio}\nvin in 0 dc {vin}\nn1 in out mm\n"
            f".model mm arrayout_demo(ratio={ratio})\n"
            f".control\npre_osdi arrayout_demo.osdi\ndc vin {vin} {vin} 1\n"
            f"wrdata _o.txt v(out)\n.endc\n.end\n")
    with open(os.path.join(HERE, "_o.cir"), "w") as fh:
        fh.write(deck)
    subprocess.run([NGSPICE, "-b", "_o.cir"], cwd=HERE, capture_output=True, text=True)
    with open(os.path.join(HERE, "_o.txt")) as fh:
        return float(fh.read().split()[-1])


def main():
    subprocess.run([OPENVAF, "arrayout_demo.va", "-o", "arrayout_demo.osdi"], cwd=HERE, check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    ok = True
    print(f"{'ratio':>6} {'V(out) (=gain, V(in)=1)':>24} {'expected':>10}  result")
    for ratio in (0.3, 0.5, 0.8, 1.0, 1.5):
        g = vout(ratio, 1.0)
        good = abs(g - 1.0) < 1e-9   # normalized taps always sum to 1
        ok = ok and good
        print(f"{ratio:>6} {g:>24.9f} {1.0:>10}  {'PASS' if good else 'FAIL'}")

    print("\nALL PASS" if ok else "\nSOME FAILED")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
