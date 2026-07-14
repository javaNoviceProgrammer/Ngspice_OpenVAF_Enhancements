#!/usr/bin/env python3
"""
verify_rcpnoise.py -- verifies periodic noise (.pnoise), Enhancement-124.

`.pnoise` runs PSS to find the periodic operating point, then folds every device's
noise through the harmonic conversion matrix (E-121) over all sidebands to get the
output noise spectrum. Each device's noise routine (thermal, shot, flicker, OSDI
`load_noise`) computes S*|dTransimpedance|^2 reading the transimpedance from
CKTrhs/CKTirhs; loading the sideband-k adjoint conversion solution into CKTrhs and
summing the device contributions over k = -M..M folds the noise exactly.

For the driven RC low-pass (R=1k, C=1n) the circuit is linear, so its periodic
Jacobian is time-invariant: the conversion matrix is block-diagonal and only
sideband 0 contributes -- pnoise reduces to ordinary `.noise`. Only R1's thermal
noise is present, so the output noise density at b is

    S_out(f) = 4*k*T*R1 / (1 + (2*pi*f*R1*C1)^2)   [V^2/Hz]

which this script checks pnoise against, and also cross-checks against a plain
`.noise` run of the same network.

NOTE: pnoise runs a PSS shooting method (~2 minutes) under the Sparse solver only.
"""
import math
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from _setup import NG as NGSPICE

BOLTZ, TEMP, R, C = 1.380649e-23, 300.15, 1e3, 1e-9   # TEMP = 27 C default

checks = passed = 0
def check(label, ok, detail=""):
    global checks, passed
    checks += 1; passed += bool(ok)
    print(f"[{'PASS' if ok else 'FAIL'}] {label}" + (f"  ({detail})" if detail and not ok else ""))

def Sana(f):
    """analytic output thermal-noise density at b: 4kTR/(1+(2*pi*f*R*C)^2) [V^2/Hz]."""
    return 4.0 * BOLTZ * TEMP * R / (1.0 + (2 * math.pi * f * R * C) ** 2)

def Aana(f):
    """same density as an AMPLITUDE spectral density [V/sqrt(Hz)] -- Enhancement-193:
    .pnoise now honors `sqrnoise` and, like .noise, defaults to V/sqrt(Hz)."""
    return math.sqrt(Sana(f))

def table(log, col="onoise_spectrum"):
    """parse a `print <col>` table -> [(freq, value), ...] (header-aware)."""
    out, on = [], False
    for line in log.splitlines():
        if re.search(r"Index\s+frequency\s+" + re.escape(col), line):
            on = True; continue
        if on:
            p = line.split()
            if len(p) == 3:
                try:
                    out.append((float(p[1]), float(p[2])))
                except ValueError:
                    if out:
                        break
    return out

def run(deck_text, name):
    path = os.path.join(HERE, name)
    with open(path, "w") as f:
        f.write(deck_text)
    r = subprocess.run([NGSPICE, "-b", name], capture_output=True, text=True, cwd=HERE)
    os.remove(path)
    return r.stdout + r.stderr

# --- pnoise (Sparse) ---
with open(os.path.join(HERE, "rc_pnoise.cir")) as f:
    lines = f.read().split("\n")
lines.insert(1, ".option sparse")
plog = run("\n".join(lines), "_rcpnoise_sparse.cir")

check("`.pnoise` is recognized", "unimplemented" not in plog.lower()
      and "unsupported" not in plog.lower(), plog[-400:])
check("[E-124] PSS operating point retained for pnoise", "operating point retained" in plog)
msw = re.search(r"PNOISE sweep:.*folding\s+(\d+)\s+sidebands", plog)
check("[E-124] pnoise sweep announced (folds sidebands)", msw is not None, plog[-400:])

pts = table(plog, "onoise_spectrum")
check(f"[E-124] pnoise produced an onoise spectrum (got {len(pts)} points)", len(pts) >= 5,
      f"{len(pts)} pts")
if pts:
    # Enhancement-193: pnoise defaults to V/sqrt(Hz) (amplitude), like .noise
    worst = max(abs(v - Aana(f)) / Aana(f) for f, v in pts)
    check(f"[E-124] pnoise onoise == sqrt(4kTR/(1+(2*pi*f*R*C)^2)) [V/sqrt(Hz)] across the sweep "
          f"(worst rel err {worst:.2e})", worst < 0.03, f"worst {worst:.3e}")
    flo, vlo = pts[0]; fhi, vhi = pts[-1]
    check(f"[E-124] low-f {flo:.4g}Hz onoise = {Aana(flo):.4e} (got {vlo:.4e})",
          abs(vlo - Aana(flo)) / Aana(flo) < 0.03, str(vlo))
    check(f"[E-124] high-f {fhi:.4g}Hz onoise = {Aana(fhi):.4e} (got {vhi:.4e})",
          abs(vhi - Aana(fhi)) / Aana(fhi) < 0.03, str(vhi))

# --- cross-check: plain .noise of the same network (no PSS, fast). Enhancement-193:
# both analyses now default to V/sqrt(Hz), so no `set sqrnoise` needed on either. ---
nref = run(
    "* noise ref\n"
    "V1 a 0 DC 0 AC 1\nR1 a b 1k\nC1 b 0 1n\n"
    ".noise v(b) v1 dec 10 10k 1meg\n"
    ".control\nrun\nsetplot noise1\nprint onoise_spectrum\n.endc\n.end\n",
    "_rcnoise_ref.cir")
nref_pts = table(nref, "onoise_spectrum")
check(f"[E-124] .noise reference produced a spectrum (got {len(nref_pts)} points)",
      len(nref_pts) >= 5)
if pts and nref_pts and len(pts) == len(nref_pts):
    worst = max(abs(a[1] - b[1]) / b[1] for a, b in zip(pts, nref_pts))
    check(f"[E-124] pnoise matches plain .noise for this linear circuit "
          f"(worst rel err {worst:.2e})", worst < 0.03, f"worst {worst:.3e}")

print()
print(("ALL PASS" if passed == checks else "FAILURES")
      + f": {passed} passed, {checks - passed} failed")
raise SystemExit(0 if passed == checks else 1)
