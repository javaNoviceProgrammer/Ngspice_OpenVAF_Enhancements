#!/usr/bin/env python3
"""
verify_funcarray.py -- verifies the Enhancement-18 features end-to-end through
version11's own openvaf-r + ngspice:

  * `real coeffs[0:3];`  -- name-then-range array declaration syntax (Part 1)
  * an analog function `polyeval(x, a)` taking a whole ARRAY argument (Part 2),
    called as `polyeval(V(in), coeffs)`.

`funcarray_demo` is a polynomial transfer stage V(out) = 0.5*V(in) + 0.3*V(in)^2,
computed inside the array-argument function by Horner's rule. We check:

  * DC  -- V(out) matches the closed-form polynomial across a sweep;
  * AC  -- the small-signal gain dV(out)/dV(in) matches poly'(bias) = 0.5 + 0.6*bias,
           i.e. the derivative flows through the array-argument function.

Every SPICE deck starts with a title line (SPICE treats line 1 as the title!).
"""
import os
import subprocess
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
import sys
sys.path.insert(0, os.path.dirname(HERE))  # repo root, for _setup.py
from _setup import VAF as OPENVAF, NG as NGSPICE


def poly(x):
    return 0.5 * x + 0.3 * x ** 2


def run(deck, outfile):
    with open(os.path.join(HERE, "_f.cir"), "w") as fh:
        fh.write(deck)
    subprocess.run([NGSPICE, "-b", "_f.cir"], cwd=HERE, capture_output=True, text=True)
    return np.atleast_2d(np.loadtxt(os.path.join(HERE, outfile)))


def main():
    subprocess.run([OPENVAF, "funcarray_demo.va", "-o", "funcarray_demo.osdi"], cwd=HERE, check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    ok = True

    # --- DC: transfer function vs closed-form polynomial -----------------------
    d = run("* funcarray dc\nvin in 0 dc 0\nn1 in out mm\n.model mm funcarray_demo()\n"
            ".control\npre_osdi funcarray_demo.osdi\ndc vin -2 2 0.1\n"
            "wrdata dc.txt v(in) v(out)\n.endc\n.end\n", "dc.txt")
    vin, vout = d[:, 1], d[:, 3]
    dc_err = np.max(np.abs(vout - poly(vin)))
    good = dc_err < 1e-9
    ok = ok and good
    print(f"{'DC: V(out) = poly(V(in)) via array-arg function':50s} max err {dc_err:.2e}  {'PASS' if good else 'FAIL'}")

    # --- AC: small-signal gain vs poly'(bias) = 0.5 + 0.6*bias -----------------
    ac_err = 0.0
    for vb in (-1.0, 0.0, 0.7, 1.5):
        a = run(f"* funcarray ac gain at {vb}\nvin in 0 dc {vb} ac 1\nn1 in out mm\n"
                ".model mm funcarray_demo()\n"
                ".control\npre_osdi funcarray_demo.osdi\nac dec 1 1k 1k\n"
                "wrdata _ac.txt mag(v(out))\n.endc\n.end\n", "_ac.txt")
        gain = float(a[0, -1])  # AC magnitude (always positive)
        ac_err = max(ac_err, abs(gain - abs(0.5 + 0.6 * vb)))
    good = ac_err < 1e-9
    ok = ok and good
    print(f"{'AC: gain = poly-prime(bias) through the function':50s} max err {ac_err:.2e}  {'PASS' if good else 'FAIL'}")

    print("\nALL PASS" if ok else "\nSOME FAILED")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
