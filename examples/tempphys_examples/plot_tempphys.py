#!/usr/bin/env python3
"""Render the Enhancement-80 thermal-law plots (runs its own sweeps;
needs the corpus for the MEXTRAM panel)."""
import math
import os
import re
import subprocess

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

import sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))  # the examples/ dir, for _setup.py
from _setup import VAF as OPENVAF, NG as NGSPICE
CORPUS = os.path.join(HERE, "..", "..", "VA_TEST", "VA-Models-main", "code")
PLOTS = os.path.join(HERE, "plots")
os.makedirs(PLOTS, exist_ok=True)


def run(deck, name):
    open(os.path.join(HERE, f"_tp_{name}.cir"), "w").write(deck)
    r = subprocess.run([NGSPICE, "-b", f"_tp_{name}.cir"], cwd=HERE,
                       capture_output=True, text=True, timeout=180)
    return r.stdout + r.stderr


def scalar(out, expr):
    m = re.search(rf"{re.escape(expr)}\s*=\s*([-\d.e+]+)", out)
    return float(m.group(1)) if m else None


fig, axes = plt.subplots(1, 3, figsize=(13, 4.2))

# panel 1: $vt vs kT/q
run("* vt\nnx p 0 mm\n.model mm vtprobe\n.control\nset numdgt=12\n"
    "pre_osdi vtprobe.osdi\ndc temp -50 150 5\nwrdata _tp_vtp.txt v(p)\n"
    ".endc\n.end\n", "vtp")
t, v = [], []
for line in open(os.path.join(HERE, "_tp_vtp.txt")):
    p = line.split()
    if len(p) >= 2:
        t.append(float(p[0]))
        v.append(float(p[1]) * 1e3)
k_q = 1.380649e-23 / 1.602176634e-19
axes[0].plot(t, v, "o", ms=3, label="$vt from the model")
axes[0].plot(t, [k_q * (x + 273.15) * 1e3 for x in t], "-", alpha=0.6,
             label="kT/q")
axes[0].set_xlabel("temp [°C]")
axes[0].set_ylabel("$vt [mV]")
axes[0].set_title("$vt tracks kT/q (1e-7)")
axes[0].legend()
axes[0].grid(alpha=0.3)

# panel 2: MEXTRAM Vbe(T) at 1 mA
if os.path.isdir(CORPUS):
    temps = list(range(-25, 130, 10))
    vbes = []
    for tc in temps:
        # 100 uA: the default card's tiny IS puts 1 mA into high injection,
        # where the cold-temperature op wobbles visibly
        out = run(f"* vbe\nib 0 b dc 100u\nVc c 0 DC 1.0\nNX c b 0 mm\n"
                  f".model mm bjt505va\n.option temp={tc}\n"
                  f".control\nset numdgt=12\npre_osdi _bjt.osdi\nop\n"
                  f"print v(b)\n.endc\n.end\n", "vbep")
        vbes.append(scalar(out, "v(b)"))
    axes[1].plot(temps, [x * 1e3 for x in vbes], "s-", ms=4)
    axes[1].set_xlabel("temp [°C]")
    axes[1].set_ylabel("$V_{BE}$ @ 100 µA [mV]")
    axes[1].set_title("MEXTRAM 505: −1.3…−1.5 mV/K")
    axes[1].grid(alpha=0.3)

    # panel 3: PSP103 ZTC — Id(T) at two gate biases
    for vg, style in ((0.35, "o-"), (1.1, "s-")):
        ids = []
        for tc in range(0, 130, 25):
            out = run(f"* ztc\nVg g 0 DC {vg}\nVd d 0 DC 0.8\n"
                      f"NX d g 0 0 mm\n.model mm PSP103VA\n"
                      f".option temp={tc}\n.control\nset numdgt=12\n"
                      f"pre_osdi _psp.osdi\nop\nprint i(vd)\n.endc\n.end\n",
                      "ztcp")
            ids.append(-scalar(out, "i(vd)"))
        norm = ids[0]
        axes[2].plot(list(range(0, 130, 25)), [i / norm for i in ids], style,
                     ms=4, label=f"$V_g$ = {vg} V")
    axes[2].axhline(1.0, ls="--", alpha=0.4)
    axes[2].set_xlabel("temp [°C]")
    axes[2].set_ylabel("$I_d(T)/I_d(0°C)$")
    axes[2].set_title("PSP103: the ZTC sign flip")
    axes[2].legend()
    axes[2].grid(alpha=0.3)

fig.tight_layout()
fig.savefig(os.path.join(PLOTS, "thermal_laws.png"), dpi=110)
print("plots written to plots/")
