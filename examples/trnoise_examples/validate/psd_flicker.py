#!/usr/bin/env python3
"""Statistical validation of the 1/f transient-noise normalisation.

NOT run by the regression -- it needs a 0.2 s transient (~1e6 points) and numpy,
and takes minutes. `../verify_trnoise.py` is the fast suite that guards the
result; this is the measurement that ESTABLISHED it.

WHAT IT PROVES. `flicker_noise(kf, 1)` on a device gives S_i(f) = kf/f. The
injected amplitude is

    Q = sqrt( |power| * (2*pi*ts)^a / (2*ts) )

derived from the generator's structure: ngspice's `f_alpha` is Kasdin's
fractional-noise method, white noise of deviation Q filtered by
H(z) = (1-z^-1)^(-a/2), so |H|^2 -> (2*pi*f*ts)^-a below Nyquist, and discrete
white noise of deviation Q on a grid of period ts has one-sided density
2*Q^2*ts. Equating S(f) = 2*Q^2*ts*(2*pi*f*ts)^-a to |power|/f^a gives Q.

This script measures the transient PSD by Welch averaging and compares it with
`.noise` on the same circuit -- two completely independent code paths. The mean
ratio must be 1.

WHY IT MATTERS. Before the law was derived, the white-noise amplitude
sqrt(power/(2*ts)) was used for flicker too. That is wrong by
sqrt(1/(2*ts*pi)) = 399x at ts = 1 us, and this script is what measured it
(397x, 396x) -- close enough to the predicted 398.9x to confirm the derivation
rather than invite a fitted fudge factor.
"""
import os
import re
import subprocess
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(os.path.dirname(HERE)))
from _setup import NG, VAF  # noqa: E402

TS = 1e-6          # noise grid
TSTOP = 0.2        # long enough to resolve down to ~100 Hz
TSTEP = 5e-6


def build():
    r = subprocess.run([VAF, "flick.va", "-o", "_flick.osdi"], cwd=HERE,
                       capture_output=True, text=True, timeout=600)
    return r.returncode == 0


def deck(kind):
    common = """flicker {kind}
V1 in 0 dc 0 ac 1
Rs in mid 1meg
N1 mid 0 myfl
.model myfl vaflick(r=1meg kf=1e-20)
"""
    if kind == "noise":
        return (common + """.control
option noacct
set numdgt=8
pre_osdi _flick.osdi
noise v(mid) V1 dec 10 10 100k
setplot noise1
print onoise_spectrum[20]
.endc
.end
""").format(kind=kind)
    return (common + """Vn nz 0 dc 0 trnoise(0 {ts} 0 0)
Rz nz 0 1k
.options reltol=1e-6 abstol=1e-18 vntol=1e-15
.control
option noacct
pre_osdi _flick.osdi
tran {step} {stop} 0 {step}
wrdata _flt.txt v(mid)
.endc
.end
""").format(kind=kind, ts=TS, step=TSTEP, stop=TSTOP)


def run(kind):
    p = os.path.join(HERE, "_f_%s.cir" % kind)
    open(p, "w").write(deck(kind))
    r = subprocess.run([NG, "-b", os.path.basename(p)], cwd=HERE,
                       capture_output=True, text=True, timeout=3600, errors="replace")
    return r.stdout + r.stderr


def main():
    if not build():
        print("  model failed to compile")
        return 1
    out = run("noise")
    m = re.search(r"^onoise_spectrum\[20\]\s*=\s*(\S+)", out, re.M)
    if not m:
        print("  .noise produced no spectrum")
        return 1
    ref_amp = float(m.group(1))          # V/sqrt(Hz) at 1 kHz (index 20, dec 10 from 10 Hz)
    A = ref_amp ** 2 * 1000.0            # S(f) = A/f in V^2/Hz

    run("tran")
    d = np.loadtxt(os.path.join(HERE, "_flt.txt"))
    t, v = d[:, 0], d[:, 1]
    dt = np.median(np.diff(t))
    fs = 1.0 / dt
    v = v - v.mean()

    nper = 1 << 15
    w = np.hanning(nper)
    U = (w ** 2).sum() / nper
    seg = [(2.0 * np.abs(np.fft.rfft(v[i:i + nper] * w)) ** 2) / (fs * nper * U)
           for i in range(0, len(v) - nper + 1, nper // 2)]
    P = np.mean(seg, axis=0)
    f = np.fft.rfftfreq(nper, dt)

    band = (f >= 200) & (f <= 20000)
    ratio = P[band] * f[band] / A
    slope = np.polyfit(np.log10(f[band]), np.log10(P[band]), 1)[0]

    print("  Welch segments %d, bins %d" % (len(seg), band.sum()))
    print("  mean  P_tran*f / A = %.4f   (1.0 == agrees with .noise)" % ratio.mean())
    print("  std error of mean  = %.4f" % (ratio.std() / np.sqrt(band.sum())))
    print("  fitted PSD slope   = %.3f   (-1.0 == ideal 1/f)" % slope)

    ok = abs(ratio.mean() - 1.0) < 0.10 and abs(slope + 1.0) < 0.10
    for j in os.listdir(HERE):
        if j.startswith(("_f_", "_flt", "_flick")):
            os.remove(os.path.join(HERE, j))
    print("\n  %s" % ("MATCHES .noise" if ok else "MISMATCH"))
    return 0 if ok else 1


sys.exit(main())
