#!/usr/bin/env python3
"""Enhancement-198: the `stb` stability / loop-gain analysis.

`stb <Vprobe> <Iprobe> <ac-sweep>` measures a feedback loop's small-signal loop
gain T(f) by Middlebrook/Tian double injection, WITHOUT breaking the DC bias, and
corrects for the loading at the break point (which a single injection cannot). The
user marks the break with a probe pair in the loop wire between the driving node A
and the loaded node B:

    Vprobe A B dc 0 ac 0    series 0 V source (carries the DC bias current)
    Iprobe 0 B dc 0 ac 0    shunt 0 A source, ground -> load node B

Two AC sweeps combine into T = (Tv*Ti - 1)/(Tv + Ti + 2), from which the phase
margin (180 + phase(T) at |T| = 1) and gain margin (-|T|_dB at phase = -180) are
reported and T is stored as the complex vector `loopgain`.

Test loop: a 3-pole op-amp macromodel (A0, poles 10 Hz / 1 MHz / 3 MHz) in a
beta = 0.1 divider feedback (closed-loop gain 10). With an ideal (zero-impedance)
output the loop gain is exactly A(s)*beta, so PM/GM have closed-form values;
with a finite output impedance the break is LOADED and only the full double
injection recovers the true margins -- verified by probe-location independence.

It is a front-end command, independent of the linear solver, so it runs once.
Every SPICE deck starts with a title line (SPICE treats line 1 as the title!).
"""
import os
import re
import subprocess
import sys
import math
import cmath

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from _setup import NG as NGSPICE

passed = failed = 0
POLES = (10.0, 1e6, 3e6)
BETA = 0.1
C1 = 1.0 / (2 * math.pi * 10.0 * 1e5)
C2 = 1.0 / (2 * math.pi * 1e6 * 1e3)
C3 = 1.0 / (2 * math.pi * 3e6 * 1e3)


def check(label, ok, detail=""):
    global passed, failed
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  {detail}" if detail else ""))
    if ok:
        passed += 1
    else:
        failed += 1


def run(deck):
    open(os.path.join(HERE, "_t.cir"), "w").write(deck)
    r = subprocess.run([NGSPICE, "-b", "_t.cir"], capture_output=True, text=True,
                       cwd=HERE, timeout=60)
    return r.stdout + r.stderr


def opamp(a0, rout, probe):
    """3-pole op-amp loop; probe='clean' (mid->inn, high-Z load) or 'loaded'
    (out->rt, driven through rout)."""
    g4 = a0 / 1e5
    out = "out" if rout == 0 else "obuf"
    L = ["* stb test loop",
         "Vin inp 0 dc 0 ac 0",
         "G1 0 n1 inp inn 1", "R1 n1 0 1e5", f"C1 n1 0 {C1:.9g}",
         "E2 n2 0 n1 0 1", "R2 n2 n3 1k", f"C2 n3 0 {C2:.9g}",
         "E3 n4 0 n3 0 1", "R3 n4 n5 1k", f"C3 n5 0 {C3:.9g}",
         f"E4 {out} 0 n5 0 {g4:.9g}"]
    if rout > 0:
        L.append(f"Rout obuf out {rout}")
    if probe == "clean":
        L += ["Rf out mid 9k", "Rg mid 0 1k",
              "Vstb mid inn dc 0 ac 0", "Istb 0 inn dc 0 ac 0"]
    else:  # loaded
        L += ["Vstb out rt dc 0 ac 0", "Istb 0 rt dc 0 ac 0",
              "Rf rt inn 9k", "Rg inn 0 1k"]
    return "\n".join(L) + "\n"


def stb_deck(a0, rout, probe, extra=""):
    return opamp(a0, rout, probe) + (
        ".control\n"
        "stb Vstb Istb dec 40 1 10meg\n"
        f"{extra}"
        ".endc\n.end\n")


def margins(out):
    pm = re.search(r"phase margin\s*:\s*([-\d.]+)\s*deg\s*\(at fc\s*=\s*([\d.eE+]+)", out)
    gm = re.search(r"gain margin\s*:\s*([-\d.]+)\s*dB\s*\(at f\s*=\s*([\d.eE+]+)", out)
    dc = re.search(r"DC loop gain\s*:\s*([-\d.]+)\s*dB", out)
    return (float(pm.group(1)) if pm else None,
            float(pm.group(2)) if pm else None,
            float(gm.group(1)) if gm else None,
            float(dc.group(1)) if dc else None)


def Tf(f, a0):
    s = 1j * f
    z = a0
    for p in POLES:
        z = z / (1 + s / p)
    return z * BETA


def analytic_margins(a0):
    """PM/GM of T=A*beta via the same crossover interpolation stb uses."""
    fs = [10 ** (k / 60.0) for k in range(0, 60 * 7 + 1)]  # 1..1e7
    T = [Tf(f, a0) for f in fs]
    mag = [abs(t) for t in T]
    ph = [math.degrees(cmath.phase(t)) for t in T]
    for i in range(1, len(ph)):
        while ph[i] - ph[i - 1] > 180:
            ph[i] -= 360
        while ph[i] - ph[i - 1] < -180:
            ph[i] += 360
    pm = fc = gm = None
    for i in range(1, len(mag)):
        if pm is None and (mag[i - 1] - 1) * (mag[i] - 1) <= 0 and mag[i - 1] != mag[i]:
            t = (0 - math.log10(mag[i - 1])) / (math.log10(mag[i]) - math.log10(mag[i - 1]))
            fc = fs[i - 1] * (fs[i] / fs[i - 1]) ** t
            pm = 180 + ph[i - 1] + t * (ph[i] - ph[i - 1])
    for i in range(1, len(ph)):
        if gm is None and (ph[i - 1] + 180) * (ph[i] + 180) <= 0 and ph[i - 1] != ph[i]:
            t = (-180 - ph[i - 1]) / (ph[i] - ph[i - 1])
            m0, m1 = 20 * math.log10(mag[i - 1]), 20 * math.log10(mag[i])
            gm = -(m0 + t * (m1 - m0))
    return pm, fc, gm


# ---- 1. ideal-output loop: stb margins match the closed-form A(s)*beta ----
o = run(stb_deck(1e5, 0, "clean"))
pm, fc, gm, dc = margins(o)
apm, afc, agm = analytic_margins(1e5)
ok1 = (pm is not None and abs(pm - apm) < 0.5 and gm is not None and abs(gm - agm) < 0.5
       and fc is not None and abs(fc - afc) / afc < 0.02)
check(f"[analytic] PM/GM match closed-form loop gain (PM={apm:.1f} deg, GM={agm:.1f} dB)",
      ok1, f"(stb PM={pm} @ {fc}, GM={gm}; analytic PM={apm:.2f} GM={agm:.2f})")

# ---- 2. loaded break: the current injection corrects the loading, so the same
#         loop probed at a LOADED point gives the SAME margins as at a clean point ----
oc = run(stb_deck(1e5, 1e3, "clean"))
ol = run(stb_deck(1e5, 1e3, "loaded"))
pmc, fcc, gmc, _ = margins(oc)
pml, fcl, gml, _ = margins(ol)
ok2 = (pmc is not None and pml is not None and abs(pmc - pml) < 0.3
       and gmc is not None and gml is not None and abs(gmc - gml) < 0.3)
check("[loading] loaded-break margins == clean-break margins (double injection "
      "corrects loading; a single injection would not)",
      ok2, f"(clean PM={pmc} GM={gmc}; loaded PM={pml} GM={gml})")

# ---- 3. a lower-margin design (10x gain): stb tracks the reduced PM vs analytic ----
o3 = run(stb_deck(1e6, 0, "clean"))
pm3, fc3, gm3, _ = margins(o3)
apm3, afc3, agm3 = analytic_margins(1e6)
ok3 = (pm3 is not None and abs(pm3 - apm3) < 0.6 and pm3 < 45.0)
check(f"[tracks] a 10x-gain design has a smaller PM ({apm3:.1f} deg); stb reports it",
      ok3, f"(stb PM={pm3}; analytic {apm3:.2f})")

# ---- 4. loopgain vector: complex, right length, DC value matches |A(1Hz)*beta| ----
o4 = run(stb_deck(1e5, 0, "clean",
                  "print loopgain[0]\nlet n=length(loopgain)\nprint n\n"))
m0 = re.search(r"loopgain\[0\]\s*=\s*([-\d.eE+]+),\s*([-\d.eE+]+)", o4)
mn = re.search(r"(?im)^\s*n\s*=\s*([\d.eE+]+)", o4)
if m0:
    mag0 = math.hypot(float(m0.group(1)), float(m0.group(2)))
    want0 = abs(Tf(1.0, 1e5))
    n = int(float(mn.group(1))) if mn else 0
    ok4 = abs(mag0 - want0) / want0 < 0.02 and n == 281
else:
    ok4 = False
check("[vector] complex 'loopgain' stored (281 pts, |T(1Hz)| matches analytic)",
      ok4, f"(|loopgain[0]|={mag0 if m0 else None} want {abs(Tf(1.0,1e5)):.4g})" if m0 else "(not stored)")

# ---- 5. a bad probe name is reported cleanly (no crash) ----
o5 = run(stb_deck(1e5, 0, "clean").replace("stb Vstb Istb", "stb Vnope Istb"))
ok5 = "no such probe" in o5.lower()
check("[error] an unknown probe source is reported cleanly", ok5)

# tidy
for f in ("_t.cir",):
    p = os.path.join(HERE, f)
    if os.path.exists(p):
        os.remove(p)

print(f"\n{passed} passed, {failed} failed")
raise SystemExit(1 if failed else 0)
