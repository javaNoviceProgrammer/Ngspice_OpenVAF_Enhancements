#!/usr/bin/env python3
"""
verify_mdarray.py -- verifies Enhancement-15 multi-dimensional array support
end-to-end through version11's own openvaf-r + ngspice:

  * multi-dimensional array parameters (`parameter real [0:1][0:1] w = '{'{..},'{..}}`)
    with per-element defaults AND per-element SPICE override (`w[1][1]=...`),
  * nested-literal aggregate assignment (`acc = '{'{..},'{..}}`),
  * dynamic (runtime) multi-index read/write (`tr[j][i] = acc[i][j]`).

`mdarray_demo` is a weighted-gain buffer: V(out) = gain * V(in), where the gain
is the sum of a 2x2 weight matrix, computed entirely through the multi-dim array
machinery. Driving V(in)=1 and reading V(out) yields the gain.

Every SPICE deck starts with a title line (SPICE treats line 1 as the title!).
"""
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
import sys
sys.path.insert(0, os.path.dirname(HERE))  # repo root, for _setup.py
from _setup import VAF as OPENVAF, NG as NGSPICE
from _setup import check_both_solvers as _check_both_solvers; _check_both_solvers(__file__)  # verify under BOTH KLU and Sparse solvers


def gain(model_params):
    deck = f"""* mdarray gain measurement
vin in 0 dc 1
n1 in out mm
.model mm {model_params}
.control
pre_osdi mdarray_demo.osdi
dc vin 1 1 1
wrdata _g.txt v(out)
.endc
.end
"""
    with open(os.path.join(HERE, "_g.cir"), "w") as fh:
        fh.write(deck)
    subprocess.run([NGSPICE, "-b", "_g.cir"], cwd=HERE, capture_output=True, text=True)
    with open(os.path.join(HERE, "_g.txt")) as fh:
        return float(fh.read().split()[-1])


def main():
    subprocess.run([OPENVAF, "mdarray_demo.va", "-o", "mdarray_demo.osdi"], cwd=HERE, check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    checks = [
        # default 2-D weight matrix: g = 0.1+0.2+0.3+0.4 = 1.0
        ("default w='{'{0.1,0.2},'{0.3,0.4}}", gain("mdarray_demo()"), 1.0),
        # override a single element w[1][1]: g = 0.1+0.2+0.3+0.9 = 1.5
        ("override w[1][1]=0.9", gain("mdarray_demo(w[1][1]=0.9)"), 1.5),
        # override two elements: g = 0.5+0.2+0.3+0.5 = 1.5
        ("override w[0][0]=0.5 w[1][1]=0.5", gain("mdarray_demo(w[0][0]=0.5 w[1][1]=0.5)"), 1.5),
    ]

    ok = True
    print(f"{'check':40s} {'measured':>12s} {'expected':>12s}  result")
    for label, meas, exp in checks:
        good = abs(meas - exp) < 1e-9
        ok = ok and good
        print(f"{label:40s} {meas:12.6f} {exp:12.6f}  {'PASS' if good else 'FAIL'}")

    print("\nALL PASS" if ok else "\nSOME FAILED")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
