#!/usr/bin/env python3
"""
verify_complexpole.py -- verifies Enhancement-31 complex conjugate poles/zeros in the
laplace/zi ROOT forms, end-to-end through the committed openvaf-r + ngspice.

The pole/zero vectors of `*_np`/`*_zd`/`*_zp` are (real, imag) PAIRS. Before E-31 the
compiler read them as individual REAL roots, so complex poles/zeros -- every resonant
or underdamped section -- were impossible (they produced garbage / unstable results).

`complexpole_demo.va` builds two 2nd-order sections that REQUIRE complex roots and
compares the root form against the equivalent `laplace_nd` polynomial baseline:

  1. resonant LPF via laplace_np (complex conjugate POLES) == laplace_nd, and it shows
     a real resonant PEAK (> 0 dB) near f0 -- impossible with real-only roots;
  2. notch via laplace_zd (imaginary-axis complex ZEROS) == laplace_nd, with a deep
     NULL at f0.

Every SPICE deck starts with a title line (SPICE treats line 1 as the title!).
"""
import math
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))          # the examples/ dir (holds _setup.py)
from _setup import VAF as OPENVAF, NG as NGSPICE
from _setup import check_both_solvers as _check_both_solvers; _check_both_solvers(__file__)  # verify under BOTH KLU and Sparse solvers

F0 = 1e6
Q = 8.0


def ac_sweep(cols):
    """AC sweep 100k..10MHz; return list of (freq, {col: dB})."""
    names = " ".join(f"vdb({c})" for c in cols)
    deck = (
        "* complexpole ac\n"
        "vin in 0 dc 0 ac 1\n"
        "n1 in lp_nd lp_np notch_nd notch_zd cm\n"
        f".model cm complexpole_demo(w0={2*math.pi*F0} Q={Q})\n"
        "rl1 lp_nd 0 1e12\nrl2 lp_np 0 1e12\nrn1 notch_nd 0 1e12\nrn2 notch_zd 0 1e12\n"
        ".control\npre_osdi complexpole_demo.osdi\n"
        f"ac dec 40 1e5 1e7\nwrdata _o.txt {names}\n.endc\n.end\n"
    )
    with open(os.path.join(HERE, "_o.cir"), "w") as fh:
        fh.write(deck)
    subprocess.run([NGSPICE, "-b", "_o.cir"], cwd=HERE, capture_output=True, text=True)
    rows = []
    for line in open(os.path.join(HERE, "_o.txt")):
        v = line.split()
        if not v:
            continue
        # wrdata writes freq,val pairs per column: f v1 f v2 f v3 f v4
        freq = float(v[0])
        vals = {cols[i]: float(v[2 * i + 1]) for i in range(len(cols))}
        rows.append((freq, vals))
    return rows


def main():
    subprocess.run([OPENVAF, "complexpole_demo.va", "-o", "complexpole_demo.osdi"],
                   cwd=HERE, check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    ok = True

    def check(label, cond, detail=""):
        nonlocal ok
        ok = ok and cond
        print(f"  {'PASS' if cond else 'FAIL'}  {label}   {detail}")

    rows = ac_sweep(["lp_nd", "lp_np", "notch_nd", "notch_zd"])

    print("[1] resonant LPF: laplace_np (complex POLES) matches laplace_nd baseline")
    max_lp_err = max(abs(v["lp_np"] - v["lp_nd"]) for _, v in rows)
    check("|np - nd| < 1e-3 dB across the sweep", max_lp_err < 1e-3,
          f"max |np-nd| = {max_lp_err:.2e} dB")

    print("[2] complex poles give a real resonant PEAK near f0 (impossible with real roots)")
    fpk, gpk = max(((f, v["lp_np"]) for f, v in rows), key=lambda t: t[1])
    check("peak > +12 dB (Q=8 -> ~18 dB)", gpk > 12.0, f"peak {gpk:.2f} dB at {fpk/1e6:.3f} MHz")
    check("peak sits near f0 = 1 MHz", 0.9e6 < fpk < 1.1e6, f"fpk = {fpk/1e6:.3f} MHz")

    print("[3] notch: laplace_zd (complex ZEROS) matches laplace_nd baseline")
    # Enhancement-395: compare only where the response is above the simulator's
    # numerical noise floor. The two spellings are algebraically identical, but
    # since E-395 normalised the ROOT forms to the LRM's prod(1 - s/r) they no
    # longer reach the null through bit-identical arithmetic -- and AT the null
    # the response is ~300 dB down, so both node voltages are around 1e-15 and a
    # dB comparison there measures the linear solver, not the filter. That it
    # measures the solver is directly visible: the unrestricted maximum differed
    # between Sparse (7.70 dB) and KLU (9.43 dB) for the same netlist. The null
    # itself is not going unchecked -- [4] below asserts its depth and position.
    NOISE_FLOOR_DB = -100.0
    band = [(f, v) for f, v in rows if v["notch_nd"] > NOISE_FLOOR_DB]
    max_n_err = max(abs(v["notch_zd"] - v["notch_nd"]) for _, v in band)
    check(f"|zd - nd| < 1e-3 dB wherever the response is above {NOISE_FLOOR_DB:.0f} dB",
          max_n_err < 1e-3,
          f"max |zd-nd| = {max_n_err:.2e} dB over {len(band)}/{len(rows)} points")

    print("[4] complex zeros give a deep NULL at f0")
    fmin, gmin = min(((f, v["notch_zd"]) for f, v in rows), key=lambda t: t[1])
    check("notch null < -40 dB near f0", gmin < -40.0 and 0.9e6 < fmin < 1.1e6,
          f"min {gmin:.1f} dB at {fmin/1e6:.3f} MHz")

    print("\nALL PASS" if ok else "\nSOME FAILED")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
