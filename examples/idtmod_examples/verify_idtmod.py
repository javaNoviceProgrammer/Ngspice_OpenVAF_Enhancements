#!/usr/bin/env python3
"""
verify_idtmod.py -- verifies the Enhancement-27 `idtmod(...)` fix, end-to-end
through version11's own openvaf-r + ngspice.

`idtmod` previously integrated correctly for the FIRST period but broke at the
first modulo wrap (VCO froze / sawtooth diverged), and its offset form read the
wrong argument. This checks the fix over MANY periods:

  1. VCO -- a modulo-1 phase drives sin(2*pi*phase); the output must track
     sin(2*pi*freq*t) across several periods (it used to freeze after one);
  2. sawtooth -- idtmod(1, 0, modu, off) must produce a clean sawtooth whose value
     stays in [off, off+modu) and wraps correctly (it used to diverge), including
     the offset form (which used to read the modulus as the offset).

Every SPICE deck starts with a title line (SPICE treats line 1 as the title!).
"""
import math
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))          # repo root
from _setup import VAF as OPENVAF, NG as NGSPICE
from _setup import check_both_solvers as _check_both_solvers; _check_both_solvers(__file__)  # verify under BOTH KLU and Sparse solvers


def tran(model_line, tstop, tmax):
    deck = (f"* idtmod\nn1 out 0 dm\n{model_line}\nr1 out 0 1meg\n"
            f".control\npre_osdi idtmod_demo.osdi\ntran {tmax} {tstop} 0 {tmax}\n"
            f"wrdata _o.txt v(out)\n.endc\n.end\n")
    with open(os.path.join(HERE, "_o.cir"), "w") as fh:
        fh.write(deck)
    subprocess.run([NGSPICE, "-b", "_o.cir"], cwd=HERE, capture_output=True, text=True)
    return [(float(a), float(b)) for a, b in
            (l.split() for l in open(os.path.join(HERE, "_o.txt")) if l.strip())]


def floor_mod(x, m):
    return x - m * math.floor(x / m)


def main():
    subprocess.run([OPENVAF, "idtmod_demo.va", "-o", "idtmod_demo.osdi"],
                   cwd=HERE, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    ok = True

    def check(label, cond, detail=""):
        nonlocal ok
        ok = ok and cond
        print(f"  {'PASS' if cond else 'FAIL'}  {label}   {detail}")

    # 1. VCO across ~3 periods (freq=1): v(out) == sin(2*pi*t)
    rows = tran(".model dm vco(freq=1.0)", 3.0, 2e-3)
    err = max(abs(v - math.sin(2 * math.pi * t)) for t, v in rows if t > 0.05)
    print("[1] VCO: modulo-1 phase drives sin (used to freeze after the 1st wrap)")
    check("v(out) tracks sin(2*pi*t) across 3 periods", err < 5e-3, f"max err = {err:.2e}")

    # 2. sawtooth off=0 and off=5: value in [off, off+modu) and equals off+floor_mod(t-off, modu)
    print("[2] sawtooth wraps correctly (used to diverge); offset form uses the right arg")
    for off in (0.0, 5.0):
        rows = tran(f".model dm saw(rate=1.0 modu=2.0 off={off})", 5.0, 5e-3)
        in_range = all(off - 1e-6 <= v < off + 2.0 + 1e-6 for t, v in rows if t > 0.02)
        # error away from the wrap discontinuities
        err = max((abs(v - (off + floor_mod(t - off, 2.0)))
                   for t, v in rows
                   if t > 0.05 and 0.05 < floor_mod(t - off, 2.0) < 1.95),
                  default=1.0)
        check(f"off={off}: value in [{off}, {off + 2.0}) and wraps correctly",
              in_range and err < 5e-3, f"in_range={in_range}  max err = {err:.2e}")

    print("\nALL PASS" if ok else "\nSOME FAILED")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
