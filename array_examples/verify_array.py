#!/usr/bin/env python3
"""
verify_array.py -- verifies the Enhancement-14 array literal / aggregate
features end-to-end through version11's own openvaf-r + ngspice:

  * array-valued parameters  (`parameter real [0:3] w = '{...}`) with per-element
    defaults AND per-element SPICE override (`w[0]=...`),
  * whole-array aggregate assignment (`acc = '{...}`) and copy (`b = a`),
  * dynamic (non-constant) indexing (`rev[i]`, `acc[3-i]`) in for-loops.

Each device is a programmable-gain buffer: V(out) = gain * V(in), where `gain`
is computed through the array machinery. We drive V(in)=1 and read V(out), which
equals the gain, and compare against the closed-form value.

Every SPICE deck starts with a title line (SPICE treats line 1 as the title!).
"""
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
import sys
sys.path.insert(0, os.path.dirname(HERE))  # repo root, for _setup.py
from _setup import VAF as OPENVAF, NG as NGSPICE


def compile_va(name):
    subprocess.run([OPENVAF, f"{name}.va", "-o", f"{name}.osdi"], cwd=HERE, check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def gain(model_params, osdi):
    """Return V(out) for V(in)=1, i.e. the device gain, given a `.model` param string."""
    deck = f"""* array_examples gain measurement
vin in 0 dc 1
n1 in out mm
.model mm {model_params}
.control
pre_osdi {osdi}
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
    compile_va("array_demo")
    compile_va("array_copy")

    checks = []  # (label, measured, expected)

    # array_demo default weights: g = 0.1+0.2+0.3+0.4 = 1.0
    checks.append(("array_demo default (w='{0.1,0.2,0.3,0.4})",
                   gain("array_demo()", "array_demo.osdi"), 1.0))

    # array_demo per-element override: g = 0.3+0.4+0.5+0.6 = 1.8
    checks.append(("array_demo override w[0..3]=0.3,0.4,0.5,0.6",
                   gain("array_demo(w[0]=0.3 w[1]=0.4 w[2]=0.5 w[3]=0.6)",
                        "array_demo.osdi"), 1.8))

    # array_demo partial override (only w[2]): g = 0.1+0.2+0.9+0.4 = 1.6
    checks.append(("array_demo override w[2]=0.9 only",
                   gain("array_demo(w[2]=0.9)", "array_demo.osdi"), 1.6))

    # array_copy: aggregate + copy + int->real: gain = (1+2+3)*0.1 = 0.6
    checks.append(("array_copy (b=a='{1,2,3}) gain",
                   gain("array_copy()", "array_copy.osdi"), 0.6))

    ok = True
    print(f"{'check':45s} {'measured':>12s} {'expected':>12s}  result")
    for label, meas, exp in checks:
        good = abs(meas - exp) < 1e-9
        ok = ok and good
        print(f"{label:45s} {meas:12.6f} {exp:12.6f}  {'PASS' if good else 'FAIL'}")

    print("\nALL PASS" if ok else "\nSOME FAILED")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
