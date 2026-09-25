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
from _setup import check_both_solvers as _check_both_solvers; _check_both_solvers(__file__)  # verify under BOTH KLU and Sparse solvers


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


def compile_ok(name):
    """Enhancement-715: compile `name`, True on success (the E-714 compiler refuses
    `array_const.va`, and the suite must report that rather than stop)."""
    r = subprocess.run([OPENVAF, f"{name}.va", "-o", f"{name}.osdi"], cwd=HERE,
                       capture_output=True, text=True)
    return r.returncode == 0


def gain_or_refusal(model_params, osdi):
    """Like `gain`, but returns (gain, None) or (nan, message) when ngspice refuses the
    card at setup -- a parameter outside its range -- instead of reading a stale file."""
    try:
        os.remove(os.path.join(HERE, "_g.txt"))
    except OSError:
        pass
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
    r = subprocess.run([NGSPICE, "-b", "_g.cir"], cwd=HERE, capture_output=True, text=True)
    out = r.stdout + r.stderr
    if not os.path.exists(os.path.join(HERE, "_g.txt")):
        msg = next((l.strip() for l in out.splitlines() if "out of bounds" in l), "refused")
        return float("nan"), msg
    with open(os.path.join(HERE, "_g.txt")) as fh:
        return float(fh.read().split()[-1]), None


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

    # Enhancement-715 (correctness campaign F1 of 2026-09-25): an element of an
    # array parameter in every constant context -- another parameter's default, a
    # localparam, a range bound, another array's literal, an integer default. The
    # E-714 compiler refused the module ("'w' was not found in the current scope").
    # gain = gsum + gtwice + glim + q[0] + q[1] + nsum/100
    #      = (w1+w2) + 2 w0 + glim + w3 + w0 + (n0+n1)/100
    if compile_ok("array_const"):
        g = lambda params: gain_or_refusal(f"array_const({params})", "array_const.osdi")
        # defaults: 0.5 + 0.2 + 0.25 + 0.4 + 0.1 + 0.05
        checks.append(("array_const defaults (elements in every constant context)", g("")[0], 1.5))
        # the derived default follows the element it reads: gsum = 0.7 + 0.3
        checks.append(("array_const w[1]=0.7 moves gsum = w[1]+w[2]", g("w[1]=0.7")[0], 2.0))
        # a given value wins over the derived default
        checks.append(("array_const gsum=0.9 given wins", g("gsum=0.9")[0], 1.9))
        # one element feeds a localparam, an array literal and a range bound at once
        checks.append(("array_const w[0]=0.05: localparam, q[1] and the range follow",
                       g("w[0]=0.05")[0], 1.35))
        # the range [w[0]:w[3]] is judged with the elements' values: 0.5 is outside
        # [0.1:0.4] and refused at setup, inside [0.1:0.6] once w[3] moves
        val, msg = g("glim=0.5")
        checks.append(("array_const glim=0.5 outside [w[0]:w[3]] refused at setup",
                       1.0 if msg and "out of bounds" in msg else 0.0, 1.0))
        checks.append(("array_const glim=0.5 w[3]=0.6 inside the moved range",
                       g("glim=0.5 w[3]=0.6")[0], 1.95))
        # integer elements in an integer default
        checks.append(("array_const n[1]=7 moves nsum = n[0]+n[1]", g("n[1]=7")[0], 1.54))
    else:
        for label in ("array_const compiles (elements in every constant context)",):
            checks.append((label, float("nan"), 1.0))
        print("array_const.va refused by this compiler: the 7 Enhancement-715 checks fail")
        for label in ("w[1]=0.7", "gsum=0.9", "w[0]=0.05", "glim=0.5 refused", "glim=0.5 w[3]=0.6", "n[1]=7"):
            checks.append((f"array_const {label}", float("nan"), 1.0))

    ok = True
    print(f"{'check':45s} {'measured':>12s} {'expected':>12s}  result")
    for label, meas, exp in checks:
        good = meas == meas and abs(meas - exp) < 1e-9
        ok = ok and good
        print(f"{label:45s} {meas:12.6f} {exp:12.6f}  {'PASS' if good else 'FAIL'}")

    print("\nALL PASS" if ok else "\nSOME FAILED")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
