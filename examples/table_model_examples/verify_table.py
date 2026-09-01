#!/usr/bin/env python3
"""
verify_table.py -- verifies the Enhancement-16 `$table_model` lookup-table
interpolation end-to-end through version11's own openvaf-r + ngspice:

  * `table_xfer` -- an INLINE-array transfer function V(out)=table(V(in)); its DC
    sweep must match a reference piecewise-linear interpolation with LINEAR
    end extrapolation -- the LRM 9.21.2 default since the E-527 kernel audit
    (no control string used to clamp; "1C" is the spelling that clamps now).
  * `table_res`  -- a FILE-based nonlinear resistor I(p,n)=table(V(p,n)); driven
    through a series resistor, its nonlinear DC operating point must converge to
    the analytic solution -- which only works if the interpolation is
    DIFFERENTIABLE (its slope dI/dV is the Jacobian conductance).

Reference interpolation is computed with numpy; the nonlinear DC reference is a
bisection root-solve of the same piecewise-linear I-V (no scipy needed).

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
from _setup import check_both_solvers as _check_both_solvers; _check_both_solvers(__file__)  # verify under BOTH KLU and Sparse solvers

# The two tables, mirrored here for the reference computations.
XFER_XP = [0.0, 1.0, 2.0, 3.0]
XFER_FP = [0.0, 1.0, 4.0, 9.0]
IV_XP = [0.0, 0.2, 0.4, 0.6, 0.8, 1.0, 1.2]
IV_FP = [0.0, 1e-5, 5e-5, 2e-4, 6e-4, 1.5e-3, 3e-3]
RS = 1e3


def compile_va(name):
    subprocess.run([OPENVAF, f"{name}.va", "-o", f"{name}.osdi"], cwd=HERE, check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def run_ngspice(deck, outfile):
    with open(os.path.join(HERE, "_t.cir"), "w") as fh:
        fh.write(deck)
    subprocess.run([NGSPICE, "-b", "_t.cir"], cwd=HERE, capture_output=True, text=True)
    return np.loadtxt(os.path.join(HERE, outfile))


def iv_lin(v):
    """Piecewise-linear I-V with linear extrapolation above the last point."""
    if v >= IV_XP[-1]:
        slope = (IV_FP[-1] - IV_FP[-2]) / (IV_XP[-1] - IV_XP[-2])
        return IV_FP[-1] + (v - IV_XP[-1]) * slope
    if v <= IV_XP[0]:
        slope = (IV_FP[1] - IV_FP[0]) / (IV_XP[1] - IV_XP[0])
        return IV_FP[0] + (v - IV_XP[0]) * slope
    return float(np.interp(v, IV_XP, IV_FP))


def solve_dc(vin):
    """Bisection solve of (vin - V)/RS = iv_lin(V)."""
    f = lambda V: (vin - V) / RS - iv_lin(V)
    lo, hi = -1.0, vin + 1.0
    for _ in range(200):
        mid = 0.5 * (lo + hi)
        if f(lo) * f(mid) <= 0:
            hi = mid
        else:
            lo = mid
    return 0.5 * (lo + hi)


def main():
    compile_va("table_xfer")
    compile_va("table_res")
    ok = True

    # --- transfer function: V(out) vs reference interpolation -----------------
    deck = ("* table_xfer sweep\n"
            "vin in 0 dc 0\nn1 in out mm\n.model mm table_xfer()\n"
            ".control\npre_osdi table_xfer.osdi\n"
            "dc vin -1 5 0.25\nwrdata xfer.txt v(in) v(out)\n.endc\n.end\n")
    d = run_ngspice(deck, "xfer.txt")
    vin, vout = d[:, 1], d[:, 3]
    # LRM 9.21.2 default: LINEAR extrapolation on both ends (E-527); numpy's
    # np.interp clamps, so continue the end-segment slopes explicitly.
    ref = np.interp(vin, XFER_XP, XFER_FP)
    lo_slope = (XFER_FP[1] - XFER_FP[0]) / (XFER_XP[1] - XFER_XP[0])
    hi_slope = (XFER_FP[-1] - XFER_FP[-2]) / (XFER_XP[-1] - XFER_XP[-2])
    below = vin < XFER_XP[0]
    above = vin > XFER_XP[-1]
    ref[below] = XFER_FP[0] + (vin[below] - XFER_XP[0]) * lo_slope
    ref[above] = XFER_FP[-1] + (vin[above] - XFER_XP[-1]) * hi_slope
    xfer_err = np.max(np.abs(vout - ref))
    good = xfer_err < 1e-9
    ok = ok and good
    print(f"{'transfer function (inline table, lin ext)':44s} max err {xfer_err:.2e}  {'PASS' if good else 'FAIL'}")

    # --- DC: nonlinear resistor operating point vs analytic root --------------
    deck = ("* table_res nonlinear DC\n"
            "vin in 0 dc 1\nrs in nn 1k\nn1 nn 0 mm\n.model mm table_res()\n"
            ".control\npre_osdi table_res.osdi\n"
            "dc vin 0 2 0.1\nwrdata res.txt v(nn)\n.endc\n.end\n")
    d = run_ngspice(deck, "res.txt")
    sweep, vnn = d[:, 0], d[:, 1]
    ref = np.array([solve_dc(vi) for vi in sweep])
    res_err = np.max(np.abs(vnn - ref))
    good = res_err < 1e-6
    ok = ok and good
    print(f"{'DC: nonlinear op-point via table Jacobian':44s} max err {res_err:.2e} V  {'PASS' if good else 'FAIL'}")

    # --- AC: small-signal conductance g = dI/dV must equal the table slope ----
    def slope_at(v):
        i = min(range(len(IV_XP) - 1), key=lambda k: abs(0.5 * (IV_XP[k] + IV_XP[k + 1]) - v))
        return (IV_FP[i + 1] - IV_FP[i]) / (IV_XP[i + 1] - IV_XP[i])

    ac_err = 0.0
    for v0 in (0.5, 0.7, 0.9, 1.1):
        deck = (f"* table_res AC conductance at {v0}\n"
                f"vbias nn 0 dc {v0} ac 1\nn1 nn 0 mm\n.model mm table_res()\n"
                ".control\npre_osdi table_res.osdi\n"
                "ac dec 1 1k 1k\nwrdata _ac.txt mag(i(vbias))\n.endc\n.end\n")
        a = np.atleast_2d(run_ngspice(deck, "_ac.txt"))
        g = float(a[0, -1])
        ac_err = max(ac_err, abs(g - slope_at(v0)))
    good = ac_err < 1e-9
    ok = ok and good
    print(f"{'AC: small-signal g = table slope':44s} max err {ac_err:.2e} S  {'PASS' if good else 'FAIL'}")

    # --- Transient: V(out) must track table(V(in)) instantaneously ------------
    deck = ("* table_xfer transient (sine input 0..3V)\n"
            "vin in 0 dc 0 sin(1.5 1.5 100)\nn1 in out mm\n.model mm table_xfer()\n"
            ".control\npre_osdi table_xfer.osdi\n"
            "tran 50u 20m\nwrdata tran.txt v(in) v(out)\n.endc\n.end\n")
    d = run_ngspice(deck, "tran.txt")
    tvin, tvout = d[:, 1], d[:, 3]
    tran_err = np.max(np.abs(tvout - np.interp(tvin, XFER_XP, XFER_FP)))
    good = tran_err < 1e-6
    ok = ok and good
    print(f"{'Transient: V(out) tracks table(V(in))':44s} max err {tran_err:.2e}  {'PASS' if good else 'FAIL'}")

    print("\nALL PASS" if ok else "\nSOME FAILED")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
