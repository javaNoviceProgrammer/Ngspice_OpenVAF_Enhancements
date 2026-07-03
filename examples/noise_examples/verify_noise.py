#!/usr/bin/env python3
"""
verify_noise.py -- compile, simulate and *verify* the Enhancement-9 noise
examples against closed-form analytical expectations, then plot them.

For each model we build the .osdi with version10's own openvaf-r, run the
matching .noise deck through version10's own ngspice, read back the
`onoise_spectrum` (output-referred noise voltage density, V/sqrt(Hz)) written
by `wrdata`, and compare it point-by-point with an independent analytical
computation. A nonzero exit status means a mismatch exceeded tolerance.

All four analog noise sources are covered:
  * white_noise()       -> thermal.cir     (flat / white)
  * flicker_noise()     -> flicker.cir     (1/f + white floor)
  * noise_table()       -> table.cir       (interpolated measured spectrum)
  * noise_table_log()   -> table_log.cir   (same spectrum, log10-freq column)
"""
import os
import subprocess
import sys

import numpy as np
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

HERE = os.path.dirname(os.path.abspath(__file__))
import sys
sys.path.insert(0, os.path.dirname(HERE))  # repo root, for _setup.py
from _setup import VAF as OPENVAF, NG as NGSPICE

KB = 1.380649e-23
T = 300.0            # K, matches the models' Temp=300 and the decks' .temp 26.85


def sh(cmd):
    subprocess.run(cmd, cwd=HERE, check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def compile_va(name):
    sh([OPENVAF, name + ".va", "-o", name + ".osdi"])


def run_cir(cir):
    subprocess.run([NGSPICE, "-b", cir], cwd=HERE, check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def read_wrdata(path):
    f, v = [], []
    with open(path) as fh:
        for line in fh:
            parts = line.split()
            if len(parts) < 2:
                continue
            try:
                f.append(float(parts[0]))
                v.append(float(parts[1]))
            except ValueError:
                continue
    return np.array(f), np.array(v)


def zpar(a, b):
    return a * b / (a + b)


def table_interp(freq, xs, ys):
    """Piecewise-linear interp of power ys over log10-freq nodes xs, clamped."""
    lx = np.log10(freq)
    return np.interp(lx, xs, ys)  # np.interp clamps to endpoints, matching OSDI


def check(name, freq, sim, ana, tol=2e-3):
    rel = np.abs(sim - ana) / np.abs(ana)
    worst = rel.max()
    ok = worst < tol
    print(f"  {name:12s}: max relative error = {worst:.3e}  "
          f"({'PASS' if ok else 'FAIL'}, tol={tol:.0e})")
    return ok


def main():
    all_ok = True
    fig, axes = plt.subplots(2, 2, figsize=(11, 8))

    # ---- white_noise: thermal divider -------------------------------------
    compile_va("thermal_noise")
    run_cir("thermal.cir")
    f, sim = read_wrdata("thermal_onoise.txt")
    R1, Rdev = 1e3, 10e3
    zout = zpar(R1, Rdev)
    Sout = 4 * KB * T * (1 / R1 + 1 / Rdev) * zout ** 2
    ana = np.full_like(f, np.sqrt(Sout))
    all_ok &= check("white", f, sim, ana)
    ax = axes[0, 0]
    ax.loglog(f, sim, "b-", lw=2, label="ngspice")
    ax.loglog(f, ana, "r--", lw=1, label="analytic")
    ax.set_title("white_noise() -- thermal (flat)")
    ax.set_xlabel("frequency [Hz]"); ax.set_ylabel("onoise [V/sqrt(Hz)]")
    ax.set_ylim(np.sqrt(Sout) * 0.3, np.sqrt(Sout) * 3.0)
    ax.grid(True, which="both", alpha=0.3); ax.legend()

    # ---- flicker_noise: 1/f + floor ---------------------------------------
    compile_va("flicker_noise")
    run_cir("flicker.cir")
    f, sim = read_wrdata("flicker_onoise.txt")
    R1, Rdev = 1e3, 10e3
    Ib, KF, AF, EF = 1e-3, 1e-12, 2.0, 1.0
    zout = zpar(R1, Rdev)
    Si = 4 * KB * T * (1 / R1 + 1 / Rdev) + KF * abs(Ib) ** AF / f ** EF
    ana = np.sqrt(Si * zout ** 2)
    all_ok &= check("flicker", f, sim, ana)
    ax = axes[0, 1]
    ax.loglog(f, sim, "b-", lw=2, label="ngspice")
    ax.loglog(f, ana, "r--", lw=1, label="analytic")
    ax.set_title("flicker_noise() -- 1/f + white floor")
    ax.set_xlabel("frequency [Hz]"); ax.set_ylabel("onoise [V/sqrt(Hz)]")
    ax.grid(True, which="both", alpha=0.3); ax.legend()

    # ---- noise_table: measured spectrum -----------------------------------
    xs = np.array([0.0, 2.0, 4.0])          # log10(f) nodes
    ys = np.array([1e-12, 1e-12, 1e-16])    # power at nodes
    R1, Rdev = 1e3, 1e9
    zout = zpar(R1, Rdev)

    def table_ana(f):
        Si = table_interp(f, xs, ys) + 4 * KB * T / R1
        return np.sqrt(Si * zout ** 2)

    compile_va("table_noise")
    run_cir("table.cir")
    f, sim = read_wrdata("table_onoise.txt")
    ana = table_ana(f)
    all_ok &= check("table", f, sim, ana)
    ax = axes[1, 0]
    ax.loglog(f, sim, "b-", lw=2, label="ngspice")
    ax.loglog(f, ana, "r--", lw=1, label="analytic")
    ax.set_title("noise_table() -- interpolated measured PSD")
    ax.set_xlabel("frequency [Hz]"); ax.set_ylabel("onoise [V/sqrt(Hz)]")
    ax.grid(True, which="both", alpha=0.3); ax.legend()

    # ---- noise_table_log: identical spectrum ------------------------------
    compile_va("table_noise_log")
    run_cir("table_log.cir")
    fl, siml = read_wrdata("table_log_onoise.txt")
    anal = table_ana(fl)
    all_ok &= check("table_log", fl, siml, anal)
    # also require it to match the linear table bit-for-bit
    dmax = np.abs(siml - sim).max()
    print(f"  table_log vs table: max |diff| = {dmax:.3e}  "
          f"({'PASS' if dmax < 1e-12 else 'FAIL'})")
    all_ok &= dmax < 1e-12
    ax = axes[1, 1]
    ax.loglog(fl, siml, "g-", lw=2, label="noise_table_log")
    ax.loglog(f, sim, "b--", lw=1, label="noise_table")
    ax.set_title("noise_table_log() == noise_table()")
    ax.set_xlabel("frequency [Hz]"); ax.set_ylabel("onoise [V/sqrt(Hz)]")
    ax.grid(True, which="both", alpha=0.3); ax.legend()

    fig.tight_layout()
    fig.savefig(os.path.join(HERE, "noise_spectra.png"), dpi=110)
    print(f"\nwrote noise_spectra.png")
    print("ALL PASS" if all_ok else "SOME CHECKS FAILED")
    sys.exit(0 if all_ok else 1)


if __name__ == "__main__":
    main()
