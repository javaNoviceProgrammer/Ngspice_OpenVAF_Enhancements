#!/usr/bin/env python3
"""
verify_arrayret.py -- verifies Enhancement-23 array RETURN values from analog
functions, end-to-end through version11's own openvaf-r + ngspice.

`arrayret_demo.va` implements a cubic polynomial device two ways:
  * `polyret`     -- a function returns the power array {1,V,V^2,V^3} (array
                     return), summed with the coefficients at the call site;
  * `polyret_arg` -- the returned array is fed straight into an array-*argument*
                     function (E-18), composing array return with array argument.

Both must equal  I = c0 + c1*V + c2*V^2 + c3*V^3.  We check the DC current
against that closed form across a bias sweep, and the AC conductance against the
exact derivative gm = c1 + 2*c2*V + 3*c3*V^2 (the autodiff Jacobian flowing
through the array return). Both modules must agree.

Every SPICE deck starts with a title line (SPICE treats line 1 as the title!).
"""
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))          # repo root
from _setup import VAF as OPENVAF, NG as NGSPICE

C0, C1, C2, C3 = 0.10, 0.50, 0.30, 0.05


def poly(v):
    return C0 + C1 * v + C2 * v * v + C3 * v * v * v


def dpoly(v):
    return C1 + 2 * C2 * v + 3 * C3 * v * v


def last(fname):
    with open(os.path.join(HERE, fname)) as fh:
        return float(fh.read().split()[-1])


def dc_I(model, vbias):
    deck = (f"* dc\nva a 0 dc {vbias}\nn1 a 0 dm\n.model dm {model}\n"
            f".control\npre_osdi arrayret_demo.osdi\ndc va {vbias} {vbias} 1\n"
            f"wrdata _o.txt i(va)\n.endc\n.end\n")
    with open(os.path.join(HERE, "_o.cir"), "w") as fh:
        fh.write(deck)
    subprocess.run([NGSPICE, "-b", "_o.cir"], cwd=HERE, capture_output=True, text=True)
    return -last("_o.txt")


def ac_gm(model, vbias):
    deck = (f"* ac\nva a 0 dc {vbias} ac 1\nn1 a 0 dm\n.model dm {model}\n"
            f".control\npre_osdi arrayret_demo.osdi\nac lin 1 1 1\n"
            f"wrdata _o.txt mag(i(va))\n.endc\n.end\n")
    with open(os.path.join(HERE, "_o.cir"), "w") as fh:
        fh.write(deck)
    subprocess.run([NGSPICE, "-b", "_o.cir"], cwd=HERE, capture_output=True, text=True)
    return last("_o.txt")


def main():
    subprocess.run([OPENVAF, "arrayret_demo.va", "-o", "arrayret_demo.osdi"],
                   cwd=HERE, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    ok = True
    print(f"{'model':14} {'V':>5} {'DC I':>12} {'expect':>12} {'AC gm':>10} {'expect':>10}  result")
    for model in ("polyret", "polyret_arg"):
        for v in (-0.8, -0.3, 0.2, 0.7, 1.2):
            i = dc_I(model, v)
            gm = ac_gm(model, v)
            gi = abs(dpoly(v))  # AC magnitude
            good = abs(i - poly(v)) < 1e-9 and abs(gm - gi) < 1e-9
            ok = ok and good
            print(f"{model:14} {v:>5.1f} {i:>12.6f} {poly(v):>12.6f} {gm:>10.5f} {gi:>10.5f}  "
                  f"{'PASS' if good else 'FAIL'}")

    print("\nALL PASS" if ok else "\nSOME FAILED")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
