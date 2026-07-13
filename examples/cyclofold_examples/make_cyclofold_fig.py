#!/usr/bin/env python3
"""Enhancement-178 figure: exact separable cyclostationary folding.

Panel A -- flicker + conversion onoise spectrum in cyclo mode: the live cyclo
sweep lands on the independent exact-separable referee; the old frequency-flat
identity (= pre-E-178 cyclo, verified digit-for-digit against the old binary)
overestimates by 34% on this circuit. The two-tone `qpnoise ... cyclo` value
(different orbit machinery: QPSS-HB vs PSS shooting) lands on the same point.

Panel B -- "flicker sees <m>^2, white sees <m^2>": |sin(w0 t)|-modulated
flicker through an LTI transfer. Only the DC of the envelope feeds the 1/f
band; the exact law is R1^2*KF*<|I|>^2 = (8/pi^2)*<I^2>, 23% below the old
frequency-flat <I^2> law.

Run:  python3 make_cyclofold_fig.py   ->  cyclofold.png
"""
import math
import os
import re
import subprocess
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from _setup import NG as NGSPICE

G0, G1, R1, C1, F0 = 1e-3, 0.8e-3, 10e3, 100e-12, 1e6
KB, T = 1.380649e-23, 300.15
KF, AF, EF = 1e-9, 2.0, 1.0
M = 5


def zrow(f, g1):
    n = 2*M + 1
    Y = np.zeros((n, n), complex)
    for ni in range(n):
        wn = 2*np.pi*(f + (ni - M)*F0)
        Y[ni, ni] += 1.0/R1 + 1j*wn*C1 + G0
        if ni + 1 < n:
            Y[ni, ni+1] += +1j*g1/2
        if ni - 1 >= 0:
            Y[ni, ni-1] += -1j*g1/2
    return np.linalg.inv(Y)[M, :]


def referee_exact(f, g1, Is, Qmax=2*M):
    Z = zrow(f, g1)
    P = len(Is)
    th = 2*np.pi*np.arange(P)/P
    A = np.zeros(P, complex)
    for k in range(-M, M+1):
        A += Z[k+M]*np.exp(-1j*k*th)
    m = math.sqrt(KF)*np.asarray(Is)**(AF/2.0)
    tot = float(np.sum(np.abs(Z)**2) * 4*KB*T/R1)
    for q in range(-Qmax, Qmax+1):
        B = np.mean(m*A*np.exp(1j*q*th))
        fq = abs(f + q*F0) or f
        tot += abs(B)**2 / fq**EF
    return tot


def referee_oldflat(f, g1, Is):
    Z = zrow(f, g1)
    P = len(Is)
    th = 2*np.pi*np.arange(P)/P
    A = np.zeros(P, complex)
    for k in range(-M, M+1):
        A += Z[k+M]*np.exp(1j*k*th)
    S = 4*KB*T/R1 + KF*np.asarray(Is)**AF/f**EF
    return float(np.mean(S*np.abs(A)**2))


def run(name, deck):
    p = os.path.join(HERE, name)
    open(p, "w").write(deck)
    r = subprocess.run([NGSPICE, "-b", p], capture_output=True, text=True, cwd=HERE)
    return r.stdout + r.stderr


BODY = """V1 lo 0 SIN(0 1 1meg)
VDC a 0 DC 1
R1 a b rmod 10k
B1 b 0 I=(1m + 0.8m*v(lo))*v(b)
C1 b 0 100p
.model rmod R(kf=1e-9 af=2 ef=1)
"""

# ---- Panel A data: live cyclo sweep + orbit + qpnoise point ----
deck = ("* cyclo flicker fig\n" + BODY +
        ".pnoise 1meg 1u b 1024 6 50 5u b vdc dec 4 500 200k cyclo\n"
        ".control\nrun\nprint onoise_spectrum\nsetplot pss1\nwrdata cyfig_td.csv v(b)\n.endc\n.end\n")
out = run("_figA.cir", deck)
pts = {}
for m_ in re.finditer(r"^\d+\s+([\d.eE+-]+)\s+([\d.eE+-]+)", out, re.M):
    pts[float(m_.group(1))] = float(m_.group(2))
rows = [l.split() for l in open(os.path.join(HERE, "cyfig_td.csv")) if l.strip()]
vb = [float(r[1]) for r in rows]
if len(vb) > 1 and abs(vb[0] - vb[-1]) < 1e-9:
    vb = vb[:-1]
Is = [(1.0 - v)/R1 for v in vb]

qout = run("_figQ.cir", "* qp fig\n" + BODY +
           ".control\nqpss v(b) 1meg 2.3meg hb 4\nqpnoise b 1k cyclo\n.endc\n.end\n")
mq = re.search(r"two-tone cyclostationary output.*?onoise density\s*=\s*([-\d.eE+]+)",
               qout, re.S)
qval = float(mq.group(1)) if mq else None

fs = sorted(pts)
fgrid = np.logspace(math.log10(fs[0]), math.log10(fs[-1]), 60)
ref_e = [referee_exact(f, G1, Is) for f in fgrid]
ref_o = [referee_oldflat(f, G1, Is) for f in fgrid]

fig, (axA, axB) = plt.subplots(1, 2, figsize=(11.5, 4.8))
axA.loglog(fgrid, ref_o, "--", color="#d62728", lw=1.8,
           label="frequency-flat identity (= pre-E-178 cyclo): +34% at 1 kHz")
axA.loglog(fgrid, ref_e, "-", color="#1f77b4", lw=1.8,
           label="exact separable referee (independent python)")
axA.loglog(fs, [pts[f] for f in fs], "o", ms=7, mfc="none", mew=1.8,
           color="#2ca02c", label="pnoise cyclo (live)")
if qval:
    axA.loglog([1e3], [qval], "*", ms=14, color="#9467bd",
               label="qpnoise cyclo, QPSS-HB orbit (live, digit-identical)")
axA.set_xlabel("frequency [Hz]")
axA.set_ylabel(r"onoise  [V$^2$/Hz]")
axA.set_title("A. cyclo flicker through LPTV conversion")
axA.legend(fontsize=8)
axA.grid(alpha=0.3, which="both")

# ---- Panel B: |sin|-modulated flicker, <m>^2 vs <m^2> ----
R1f, C1f, f0f = 1e3, 1e-9, 1e6
fdeck = ("* rc flicker cyclo fig\n"
         "V1 a 0 SIN(0 1 1meg)\n"
         f"R1 a b rmod {R1f:g}\n"
         f"C1 b 0 {C1f:g}\n"
         ".model rmod R(kf=1e-9 af=2 ef=1)\n"
         ".pnoise 1meg 1u b 1024 10 50 5u b v1 dec 3 100 1k cyclo\n"
         ".control\nrun\nprint onoise_spectrum\n.endc\n.end\n")
fout = run("_figB.cir", fdeck)
fpts = {}
for m_ in re.finditer(r"^\d+\s+([\d.eE+-]+)\s+([\d.eE+-]+)", fout, re.M):
    fpts[float(m_.group(1))] = float(m_.group(2))
H = 1.0/(1.0 + 1j*2*math.pi*f0f*R1f*C1f)
I2avg = 0.5*abs((1.0 - H)/R1f)**2
old_law = R1f**2*1e-9*I2avg
new_law = old_law*8/math.pi**2
ffs = sorted(fpts)
axB.semilogx(ffs, [f*fpts[f] for f in ffs], "o", ms=9, mfc="none", mew=2,
             color="#2ca02c", label="pnoise cyclo (live), onoise x f")
axB.axhline(new_law, color="#1f77b4", lw=1.8,
            label=r"exact: $R_1^2 K_F \langle|I|\rangle^2 = (8/\pi^2)\langle I^2\rangle$")
axB.axhline(old_law, color="#d62728", ls="--", lw=1.8,
            label=r"old flat law: $R_1^2 K_F \langle I^2\rangle$ (23% high)")
axB.set_ylim(0, old_law*1.35)
axB.set_xlabel("frequency [Hz]")
axB.set_ylabel(r"onoise $\times$ f  [V$^2$]")
axB.set_title(r"B. $|\sin|$-modulated flicker: only $\langle m\rangle$ feeds the 1/f band")
axB.legend(fontsize=8.5)
axB.grid(alpha=0.3, which="both")

fig.suptitle("Exact separable cyclostationary folding: colored noise folded from its "
             "SOURCE frequency, per generator (Enhancement-178)", fontsize=12)
fig.tight_layout(rect=[0, 0, 1, 0.93])
o = os.path.join(HERE, "cyclofold.png")
fig.savefig(o, dpi=110)
print("wrote", o)
