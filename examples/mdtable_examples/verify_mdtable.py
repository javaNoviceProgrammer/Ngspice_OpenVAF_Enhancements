#!/usr/bin/env python3
"""
verify_mdtable.py -- verifies Enhancement-17 multi-dimensional `$table_model`
(2-D bilinear) end-to-end through version11's own openvaf-r + ngspice.

`mos_table` is a table-based MOSFET whose drain current is a 2-D lookup table
I(Vgs, Vds) read from `mos_iv.tbl`. We check, strictly inside the grid:

  * DC  -- the drain current I(d,s) over a (Vgs, Vds) scan matches a reference
    bilinear interpolation of the same grid (computed as nested np.interp);
  * AC  -- the small-signal transconductance gm = dId/dVgs and output
    conductance gds = dId/dVds match the two partial derivatives of that bilinear
    surface (so the 2-D Jacobian is correct).

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


def read_grid(path):
    toks = []
    for line in open(path):
        line = line.strip()
        if not line or line.startswith(("#", "//", "*")):
            continue
        toks += [float(t) for t in line.split()]
    it = iter(toks)
    n = int(next(it))
    sizes = [int(next(it)) for _ in range(n)]
    axes = [np.array([next(it) for _ in range(s)]) for s in sizes]
    vals = np.array([next(it) for _ in range(sizes[0] * sizes[1])]).reshape(sizes)
    return axes[0], axes[1], vals


VG, VD, VAL = read_grid(os.path.join(HERE, "mos_iv.tbl"))


def bilinear(vg, vd):
    """Reference bilinear interpolation = nested 1-D interpolation (matches interp_nd)."""
    rows = [np.interp(vd, VD, VAL[i, :]) for i in range(len(VG))]
    return np.interp(vg, VG, rows)


def run(deck, outfile):
    with open(os.path.join(HERE, "_m.cir"), "w") as fh:
        fh.write(deck)
    subprocess.run([NGSPICE, "-b", "_m.cir"], cwd=HERE, capture_output=True, text=True)
    return np.atleast_2d(np.loadtxt(os.path.join(HERE, outfile)))


def idrain(vg, vd):
    """DC drain current at a bias (Id flows d->s, i.e. -i(vd))."""
    d = run(f"* mos_table op\nvg g 0 dc {vg}\nvd d 0 dc {vd}\nn1 g d 0 mm\n.model mm mos_table()\n"
            f".control\npre_osdi mos_table.osdi\ndc vd {vd} {vd} 1\nwrdata _i.txt i(vd)\n.endc\n.end\n",
            "_i.txt")
    return -float(d[0, -1])


def main():
    subprocess.run([OPENVAF, "mos_table.va", "-o", "mos_table.osdi"], cwd=HERE, check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    ok = True

    # --- DC: I(d,s) over a (Vgs, Vds) scan vs bilinear reference ---------------
    dc_err = 0.0
    for vg in (0.5, 0.9, 1.3, 1.7):
        d = run(f"* mos_table dc\nvg g 0 dc {vg}\nvd d 0 dc 0\nn1 g d 0 mm\n.model mm mos_table()\n"
                f".control\npre_osdi mos_table.osdi\ndc vd 0.1 1.9 0.1\nwrdata _dc.txt v(d) i(vd)\n.endc\n.end\n",
                "_dc.txt")
        vd, iid = d[:, 1], -d[:, 3]
        ref = np.array([bilinear(vg, x) for x in vd])
        dc_err = max(dc_err, np.max(np.abs(iid - ref)))
    good = dc_err < 1e-12
    ok = ok and good
    print(f"{'DC: 2-D I(Vgs,Vds) vs bilinear reference':46s} max err {dc_err:.2e} A  {'PASS' if good else 'FAIL'}")

    # --- AC: gm = dId/dVgs and gds = dId/dVds vs bilinear partials --------------
    def gm_gds_sim(vg, vd):
        out = {}
        for drv, node in (("g", "vg"), ("d", "vd")):
            d = run(f"* small-signal via AC (drive {drv})\n"
                    f"vg g 0 dc {vg} ac {1 if drv=='g' else 0}\n"
                    f"vd d 0 dc {vd} ac {1 if drv=='d' else 0}\n"
                    f"n1 g d 0 mm\n.model mm mos_table()\n"
                    f".control\npre_osdi mos_table.osdi\nac dec 1 1k 1k\nwrdata _ac.txt mag(i(vd))\n.endc\n.end\n",
                    "_ac.txt")
            out[drv] = float(d[0, -1])
        return out["g"], out["d"]  # |dId/dVgs|, |dId/dVds|

    h = 1e-4
    ac_err = 0.0
    for (vg, vd) in ((0.9, 0.5), (1.3, 1.1), (1.7, 0.7)):
        gm_ref = (bilinear(vg + h, vd) - bilinear(vg - h, vd)) / (2 * h)
        gds_ref = (bilinear(vg, vd + h) - bilinear(vg, vd - h)) / (2 * h)
        gm, gds = gm_gds_sim(vg, vd)
        ac_err = max(ac_err, abs(gm - gm_ref), abs(gds - gds_ref))
    good = ac_err < 1e-9
    ok = ok and good
    print(f"{'AC: gm, gds vs bilinear partials':46s} max err {ac_err:.2e} S  {'PASS' if good else 'FAIL'}")

    print("\nALL PASS" if ok else "\nSOME FAILED")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
