#!/usr/bin/env python3
"""
verify_idtic.py -- verifies the Enhancement-28 `idt(...)` initial-condition fix,
end-to-end through version11's own openvaf-r + ngspice.

`idt(expr, ic)`'s initial condition was applied at the DC operating point but LOST
in transient (the integrator restarted from 0). `idtic_demo.va` is an ideal
integrator `v(t) = ic + rate*t`. We check:

  1. DC operating point equals `ic`  (this already worked);
  2. transient RAMP starts from `ic`:  v(t) == ic + rate*t  (used to be rate*t);
  3. with rate=0 the integrator HOLDS at `ic`  (it used to drift to 0).

Every SPICE deck starts with a title line (SPICE treats line 1 as the title!).
"""
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))          # the examples/ dir (holds _setup.py)
from _setup import VAF as OPENVAF, NG as NGSPICE
from _setup import check_both_solvers as _check_both_solvers; _check_both_solvers(__file__)  # verify under BOTH KLU and Sparse solvers


def ngspice(deck, out):
    with open(os.path.join(HERE, "_o.cir"), "w") as fh:
        fh.write(deck)
    r = subprocess.run([NGSPICE, "-b", "_o.cir"], cwd=HERE, capture_output=True, text=True)
    return r.stdout


def op_value(rate, ic):
    out = ngspice(
        f"* idt op\nn1 a 0 dm\n.model dm idtic_demo(rate={rate} ic={ic})\nr1 a 0 1meg\n"
        f".control\npre_osdi idtic_demo.osdi\nop\nprint v(a)\n.endc\n.end\n", None)
    for line in out.splitlines():
        if "v(a)" in line:
            return float(line.split("=")[1])
    return None


def tran_trace(rate, ic, tstop=2.0):
    ngspice(
        f"* idt tran\nn1 a 0 dm\n.model dm idtic_demo(rate={rate} ic={ic})\nr1 a 0 1meg\n"
        f".control\npre_osdi idtic_demo.osdi\ntran 10m {tstop}\n"
        f"wrdata _o.txt v(a)\n.endc\n.end\n", None)
    return [(float(a), float(b)) for a, b in
            (l.split() for l in open(os.path.join(HERE, "_o.txt")) if l.strip())]


def main():
    subprocess.run([OPENVAF, "idtic_demo.va", "-o", "idtic_demo.osdi"],
                   cwd=HERE, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    ok = True

    def check(label, cond, detail=""):
        nonlocal ok
        ok = ok and cond
        print(f"  {'PASS' if cond else 'FAIL'}  {label}   {detail}")

    print("[1] DC operating point equals ic")
    v = op_value(1.0, 3.0)
    check("op(idt(1, 3)) == 3", v is not None and abs(v - 3.0) < 1e-9, f"v(op) = {v}")

    print("[2] transient ramp starts from ic:  v(t) == ic + rate*t  (used to start from 0)")
    rate, ic = 1.0, 3.0
    rows = tran_trace(rate, ic)
    err = max(abs(v - (ic + rate * t)) for t, v in rows if t > 0.02)
    check("idt(1, 3) gives 3 + t", err < 5e-3, f"max |v - (3+t)| = {err:.2e}")

    print("[3] with rate=0 the integrator HOLDS at ic (used to drift to 0)")
    rows = tran_trace(0.0, 7.0)
    dev = max(abs(v - 7.0) for t, v in rows)
    check("idt(0, 7) holds at 7", dev < 1e-6, f"max |v - 7| = {dev:.2e}")

    print("\nALL PASS" if ok else "\nSOME FAILED")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
