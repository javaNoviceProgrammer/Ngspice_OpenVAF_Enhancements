#!/usr/bin/env python3
"""
plot_mdtable.py -- plots of the Enhancement-17 2-D `$table_model` table-based
MOSFET, using version11's own openvaf-r + ngspice. Writes:

  mdtable_iv.png   the classic output characteristics Id vs Vds for a family of
                   Vgs values (simulated), plus a filled contour of the full
                   bilinearly-interpolated I(Vgs, Vds) surface with the tabulated
                   grid lines overlaid.

Every SPICE deck starts with a title line (SPICE treats line 1 as the title!).
"""
import os
import subprocess

import numpy as np
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

HERE = os.path.dirname(os.path.abspath(__file__))
import sys
sys.path.insert(0, os.path.dirname(HERE))  # repo root, for _setup.py
from _setup import VAF as OPENVAF, NG as NGSPICE


def read_grid(path):
    toks = []
    for line in open(path):
        line = line.strip()
        if line and not line.startswith(("#", "//", "*")):
            toks += [float(t) for t in line.split()]
    it = iter(toks)
    n = int(next(it))
    sizes = [int(next(it)) for _ in range(n)]
    axes = [np.array([next(it) for _ in range(s)]) for s in sizes]
    return axes[0], axes[1]


def sweep_id(vg):
    deck = (f"* mos_table output curve\nvg g 0 dc {vg}\nvd d 0 dc 0\nn1 g d 0 mm\n"
            f".model mm mos_table()\n.control\npre_osdi mos_table.osdi\n"
            f"dc vd 0 2 0.02\nwrdata _o.txt v(d) i(vd)\n.endc\n.end\n")
    with open(os.path.join(HERE, "_o.cir"), "w") as fh:
        fh.write(deck)
    subprocess.run([NGSPICE, "-b", "_o.cir"], cwd=HERE, capture_output=True, text=True)
    d = np.atleast_2d(np.loadtxt(os.path.join(HERE, "_o.txt")))
    return d[:, 1], -d[:, 3]  # Vds, Id (d->s)


def main():
    subprocess.run([OPENVAF, "mos_table.va", "-o", "mos_table.osdi"], cwd=HERE, check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    VG, VD = read_grid(os.path.join(HERE, "mos_iv.tbl"))

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(11, 4.4))

    # --- output characteristics: Id vs Vds for a family of Vgs -----------------
    for vg in (0.8, 1.2, 1.6, 2.0):
        vds, idd = sweep_id(vg)
        ax1.plot(vds, idd * 1e3, lw=2, label=f"Vgs = {vg:.1f} V")
    ax1.set(xlabel="Vds [V]", ylabel="Id [mA]",
            title="Output characteristics (bilinear $table\\_model$)")
    ax1.grid(True, alpha=0.3)
    ax1.legend()

    # --- contour of the full interpolated I(Vgs, Vds) surface ------------------
    vg_scan = np.linspace(0, 2, 41)
    grid = np.zeros((len(vg_scan), 101))
    vds_axis = None
    for i, vg in enumerate(vg_scan):
        vds, idd = sweep_id(vg)
        if vds_axis is None:
            vds_axis = vds
        grid[i, :len(idd)] = idd * 1e3
    C = ax2.contourf(vds_axis, vg_scan, grid, levels=20, cmap="viridis")
    ax2.plot(*np.meshgrid(VD, VG), "wo", ms=3, alpha=0.6)  # tabulated grid points
    for v in VG:
        ax2.axhline(v, color="w", lw=0.4, alpha=0.4)
    for v in VD:
        ax2.axvline(v, color="w", lw=0.4, alpha=0.4)
    ax2.set(xlabel="Vds [V]", ylabel="Vgs [V]",
            title="Interpolated I(Vgs, Vds) surface (grid overlaid)")
    fig.colorbar(C, ax=ax2, label="Id [mA]")

    fig.tight_layout()
    fig.savefig(os.path.join(HERE, "mdtable_iv.png"), dpi=150)
    plt.close(fig)
    print("Wrote mdtable_iv.png")


if __name__ == "__main__":
    main()
