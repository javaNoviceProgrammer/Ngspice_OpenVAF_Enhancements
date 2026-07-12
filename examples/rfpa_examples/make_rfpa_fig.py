#!/usr/bin/env python3
"""Enhancement-164 figure: large-signal RF of a real HICUM SiGe-HBT amplifier.

Panel A -- AM-AM: power gain vs input drive, and the third-harmonic distortion
(HD3, in dBc). The gain expands then compresses (the exponential-transconductance
signature of a bipolar), defining the 1-dB compression point; HD3 climbs with the
3:1 slope of a third-order nonlinearity.

Panel B -- two-tone intermodulation: the output spectrum for two equal tones,
from a transient + FFT. The third-order intermodulation products (2f1-f2, 2f2-f1)
sit just outside the two fundamentals -- the in-band distortion that sets an
amplifier's IP3.

Both use transient analysis: the frequency-domain HB/QPSS engines do not converge
on this stiff production model in an amplifier configuration (see the README).

Run:  python3 make_rfpa_fig.py   ->  rfpa_ip3.png
"""
import math
import os
import re
import subprocess
import sys
import tempfile

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.dirname(HERE))
from _setup import VAF as OPENVAF, NG as NGSPICE

ITEST = os.path.join(ROOT, "OpenVAF-master-20260610", "integration_tests")
W = tempfile.mkdtemp(prefix="rfpafig_")
subprocess.run([OPENVAF, "hicuml2.va", "-o", os.path.join(W, "hicuml2.osdi")],
               cwd=os.path.join(ITEST, "HICUML2"), capture_output=True)
MODEL = ".model m hicumL2va t0=1e-11 cjei0=1f cjci0=1f cjep0=1f cjcx0=1f"


def run(deck):
    open(os.path.join(W, "d.cir"), "w").write(deck)
    subprocess.run([NGSPICE, "-b", "d.cir"], cwd=W, capture_output=True, text=True)


# --- Panel A: AM-AM gain + HD3 vs input drive ---
amps = [0.002, 0.004, 0.007, 0.012, 0.02, 0.035, 0.06, 0.1, 0.15, 0.22, 0.3]
pin_dbv, gain_db, hd3_dbc = [], [], []
for a in amps:
    run(f"""* am-am
.control
pre_osdi hicuml2.osdi
.endc
Vcc cc 0 dc 3.0
RC cc c 400
Vsrc s 0 dc 0.77 SIN(0.77 {a} 1G)
Rb s b 50
N1 c b 0 0 0 m
{MODEL}
.control
tran 2p 80n 40n
fourier 1G v(c)
wrdata /dev/null v(c)
.endc
.end
""")
    # parse fourier from stdout captured via a file
    out = subprocess.run([NGSPICE, "-b", os.path.join(W, "d.cir")],
                         cwd=W, capture_output=True, text=True).stdout
    f1 = h3 = None
    for m in re.finditer(r"^\s*(\d+)\s+[-\d.eE+]+\s+([-\d.eE+]+)\s+[-\d.eE+]+\s+([-\d.eE+]+)",
                         out, re.M):
        h = int(m.group(1))
        if h == 1:
            f1 = float(m.group(2))
        if h == 3:
            h3 = float(m.group(3))
    if f1 and h3:
        pin_dbv.append(20 * math.log10(a))
        gain_db.append(20 * math.log10(f1 / a))
        hd3_dbc.append(20 * math.log10(max(h3, 1e-12)))

g0 = gain_db[0]
# 1-dB compression: where gain falls to g0 - 1 on the high-drive side
p1db = None
for i in range(1, len(gain_db)):
    if gain_db[i] < g0 - 1 <= gain_db[i - 1]:
        p1db = pin_dbv[i]
        break

fig, (axA, axB) = plt.subplots(1, 2, figsize=(11, 4.4))
axA.plot(pin_dbv, gain_db, "o-", color="#1f77b4", lw=2, label="power gain")
axA.axhline(g0 - 1, color="#888", ls="--", lw=1, label="gain - 1 dB")
if p1db is not None:
    axA.axvline(p1db, color="#d62728", ls=":", lw=1.5)
    axA.annotate("P1dB", xy=(p1db, g0 - 1), xytext=(p1db - 6, g0 - 4), color="#d62728")
axtw = axA.twinx()
axtw.plot(pin_dbv, hd3_dbc, "s-", color="#d62728", lw=1.5, ms=4, alpha=0.7)
axtw.set_ylabel("HD3  [dBc]", color="#d62728")
axA.set_xlabel("input drive  $20\\log_{10}(V_{in})$  [dBV]")
axA.set_ylabel("power gain  [dB]", color="#1f77b4")
axA.set_title("A. AM-AM compression + HD3 (real SiGe HBT)")
axA.legend(loc="lower left", fontsize=8)
axA.grid(True, alpha=0.3)

# --- Panel B: two-tone IM3 spectrum (transient + FFT) ---
run(f"""* two-tone
.control
pre_osdi hicuml2.osdi
.endc
Vcc cc 0 dc 3.0
RC cc c 400
Vbias b0 0 dc 0.77
Vt1 b1 b0 SIN(0 0.03 10meg)
Vt2 s b1 SIN(0 0.03 11meg)
Rb s b 50
N1 c b 0 0 0 m
{MODEL}
.control
tran 1n 32u 16u
linearize
fft v(c)
let mdb = db(mag(v(c)))
wrdata tt.dat mdb
.endc
.end
""")
fr, md = [], []
for ln in open(os.path.join(W, "tt.dat")):
    p = ln.split()
    if len(p) >= 2:
        fr.append(float(p[0]) / 1e6)
        md.append(float(p[1]))
# reference 0 dBc to the fundamental tones (not the DC component)
ref = max(m for f, m in zip(fr, md) if 9.5 < f < 11.5)
axB.plot(fr, [x - ref for x in md], "-", color="#2ca02c", lw=1)
axB.set_xlim(8.4, 12.6)
axB.set_ylim(-90, 5)
for f, lab, dx in [(10, "f1", 0), (11, "f2", 0), (9, "2f1-f2", -0.35), (12, "2f2-f1", 0.05)]:
    axB.annotate(lab, xy=(f + dx, 2), fontsize=8,
                 color="#d62728" if "f1-" in lab or "f2-" in lab else "#333")
axB.set_xlabel("frequency  [MHz]")
axB.set_ylabel("output spectrum  [dBc]")
axB.set_title("B. Two-tone intermodulation (IM3 products)")
axB.grid(True, alpha=0.3)

fig.tight_layout()
out = os.path.join(HERE, "rfpa_ip3.png")
fig.savefig(out, dpi=110)
print("wrote", out, "| P1dB @", f"{p1db:.1f} dBV" if p1db else "n/a")
