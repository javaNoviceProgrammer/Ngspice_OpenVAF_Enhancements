#!/usr/bin/env python3
"""
plot_mc.py -- DC, AC and transient Monte-Carlo of the `rc_mc` RC low-pass whose
gain / R / C are randomized per instance by Enhancement-10's $rdist_normal().

Runs a single ngspice job (this version's binary) that instantiates N filters --
all sharing one input source -- and performs `dc`, `ac` and `tran` back to back,
dumping each with `wrdata`. Then it overlays the N random responses against the
nominal (unperturbed) response and writes three PNGs:

    mc_dc.png    family of DC transfer lines  (random slopes = random gain)
    mc_ac.png    spread of Bode magnitudes    (random gain + random cutoff)
    mc_tran.png  spread of step responses     (random final value + tau)

Because every draw is a stable, reproducible function of (seed, call site), each
instance is self-consistent across all three analyses (Enhancement-10.md).
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

N = 30            # Monte-Carlo instances (seeds 1..N)
R0, C0 = 1.0e3, 1.0e-6
SIGMA = 0.15
FC = 1.0 / (2 * np.pi * R0 * C0)   # nominal cutoff ~159 Hz
TAU = R0 * C0                       # nominal time constant = 1 ms


def build_and_run():
    subprocess.run([OPENVAF, "rc_mc.va", "-o", "rc_mc.osdi"], cwd=HERE, check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    insts = [f"n{i} in o{i} m{i}" for i in range(1, N + 1)]
    mods = [f".model m{i} rc_mc(seed={i} sigma={SIGMA} R0={R0} C0={C0})"
            for i in range(1, N + 1)]
    v_dc = " ".join(f"v(o{i})" for i in range(1, N + 1))
    vdb = " ".join(f"vdb(o{i})" for i in range(1, N + 1))
    deck = f"""* rc_mc Monte-Carlo: DC, AC, transient
vin in 0 dc 0 ac 1 pulse(0 1 1u 1u 1u 1 2)
{chr(10).join(insts)}
{chr(10).join(mods)}
.control
pre_osdi rc_mc.osdi
dc vin 0 1 0.02
wrdata mc_dc.txt {v_dc}
ac dec 60 1 1e5
wrdata mc_ac.txt {vdb}
tran 20u 5m
wrdata mc_tran.txt {v_dc}
.endc
.end
"""
    with open(os.path.join(HERE, "mc.cir"), "w") as fh:
        fh.write(deck)
    r = subprocess.run([NGSPICE, "-b", "mc.cir"], cwd=HERE,
                       capture_output=True, text=True)
    for tag in ("mc_dc.txt", "mc_ac.txt", "mc_tran.txt"):
        if not os.path.exists(os.path.join(HERE, tag)):
            sys.exit(f"ngspice did not produce {tag}:\n{r.stderr}\n{r.stdout[-500:]}")


def load(tag):
    """wrdata writes interleaved (x, y1, x, y2, ...) columns -> (x, Y[N])."""
    d = np.loadtxt(os.path.join(HERE, tag))
    return d[:, 0], d[:, 1::2]


def curve_style(n):
    return plt.cm.viridis(np.linspace(0, 1, n))


def main():
    build_and_run()
    colors = curve_style(N)

    # --- DC -----------------------------------------------------------------
    vin, dc = load("mc_dc.txt")
    fig, ax = plt.subplots(figsize=(6.5, 4.6))
    for i in range(N):
        ax.plot(vin, dc[:, i], color=colors[i], lw=1, alpha=0.7)
    ax.plot(vin, vin, "k--", lw=2, label="nominal (gain = 1)")
    gains = dc[-1, :] / vin[-1]
    ax.set(xlabel="V(in) [V]", ylabel="V(out) [V]",
           title=f"DC Monte-Carlo (N={N}): random gain "
                 f"{gains.mean():.2f} $\\pm$ {gains.std():.2f}")
    ax.grid(True, alpha=0.3)
    ax.legend(loc="upper left")
    fig.tight_layout()
    fig.savefig(os.path.join(HERE, "mc_dc.png"), dpi=150)
    plt.close(fig)

    # --- AC -----------------------------------------------------------------
    freq, ac = load("mc_ac.txt")
    fig, ax = plt.subplots(figsize=(6.5, 4.6))
    for i in range(N):
        ax.semilogx(freq, ac[:, i], color=colors[i], lw=1, alpha=0.7)
    nominal_db = 20 * np.log10(1.0 / np.abs(1 + 1j * freq / FC))
    ax.semilogx(freq, nominal_db, "k--", lw=2, label="nominal")
    ax.axvline(FC, color="gray", ls=":", lw=1, label=f"nominal fc = {FC:.0f} Hz")
    ax.set(xlabel="Frequency [Hz]", ylabel="|V(out)/V(in)| [dB]",
           title=f"AC Monte-Carlo (N={N}): randomized gain & cutoff")
    ax.grid(True, which="both", alpha=0.3)
    ax.legend(loc="lower left")
    fig.tight_layout()
    fig.savefig(os.path.join(HERE, "mc_ac.png"), dpi=150)
    plt.close(fig)

    # --- Transient ----------------------------------------------------------
    t, tr = load("mc_tran.txt")
    tms = t * 1e3
    fig, ax = plt.subplots(figsize=(6.5, 4.6))
    for i in range(N):
        ax.plot(tms, tr[:, i], color=colors[i], lw=1, alpha=0.7)
    nominal = 1.0 * (1 - np.exp(-t / TAU))
    ax.plot(tms, nominal, "k--", lw=2, label=f"nominal ($\\tau$ = {TAU*1e3:.1f} ms)")
    ax.set(xlabel="Time [ms]", ylabel="V(out) [V]",
           title=f"Transient Monte-Carlo (N={N}): 1 V step response")
    ax.grid(True, alpha=0.3)
    ax.legend(loc="lower right")
    fig.tight_layout()
    fig.savefig(os.path.join(HERE, "mc_tran.png"), dpi=150)
    plt.close(fig)

    print(f"Wrote mc_dc.png, mc_ac.png, mc_tran.png (N={N} seeds)")
    print(f"  DC  gain:  mean={gains.mean():.3f}  std={gains.std():.3f}  "
          f"(nominal 1.000)")
    dc_gain_db = ac[0, :]  # low-frequency asymptote ~ 20log10(gain)
    print(f"  AC  low-f gain: {dc_gain_db.mean():.2f} +/- {dc_gain_db.std():.2f} dB")
    finals = tr[-1, :]
    print(f"  TR  final value: mean={finals.mean():.3f}  std={finals.std():.3f}")


if __name__ == "__main__":
    main()
