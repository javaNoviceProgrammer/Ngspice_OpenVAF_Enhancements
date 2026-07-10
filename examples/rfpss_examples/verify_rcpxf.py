#!/usr/bin/env python3
"""
verify_rcpxf.py -- verifies the periodic transfer function (.pxf), Enhancement-125.

PXF is the ADJOINT counterpart of PAC. Where PAC injects one input and reads all
outputs, PXF fixes one output and gives the transfer from the input at each sideband
-- computed by solving the adjoint of the conversion matrix (Hᵀ Ψ = e_{out,0}) once
per frequency and dotting Ψ with the netlist AC-source pattern:

    xf_k(f) = Σ_j Ψ_k(j) · B0(j)

By the identity (H⁻¹B)_out = (H⁻ᵀe_out)ᵀB, the sideband-0 transfer equals the PAC
response at the output exactly -- so for the driven RC low-pass (R=1k, C=1n) driven
by V1 (AC 1), the sideband-0 PXF transfer at b is the low-pass transfer

    |H(f)| = 1 / sqrt(1 + (2*pi*f*R*C)^2)

(0.998 at 10 kHz down to 0.157 at 1 MHz), and the conversion sidebands (xf_usb1,
xf_lsb1) are ~0 for this linear circuit.

NOTE: pxf runs a PSS shooting method (~2 minutes) under the Sparse solver only.
"""
import math
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from _setup import NG as NGSPICE

R, C = 1e3, 1e-9

checks = passed = 0
def check(label, ok, detail=""):
    global checks, passed
    checks += 1; passed += bool(ok)
    print(f"[{'PASS' if ok else 'FAIL'}] {label}" + (f"  ({detail})" if detail and not ok else ""))

def Hlp(f):
    return 1.0 / math.hypot(1.0, 2 * math.pi * f * R * C)

def col(log, name):
    """parse a `print <name>` table -> [(freq, value), ...] (header-aware)."""
    out, on = [], False
    for line in log.splitlines():
        if re.search(r"Index\s+frequency\s+" + re.escape(name), line):
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

with open(os.path.join(HERE, "rc_pxf.cir")) as f:
    lines = f.read().split("\n")
lines.insert(1, ".option sparse")
name = "_rcpxf_sparse.cir"
with open(os.path.join(HERE, name), "w") as f:
    f.write("\n".join(lines))
r = subprocess.run([NGSPICE, "-b", name], capture_output=True, text=True, cwd=HERE)
os.remove(os.path.join(HERE, name))
log = r.stdout + r.stderr

check("`.pxf` is recognized", "unimplemented" not in log.lower()
      and "unsupported" not in log.lower(), log[-400:])
check("[E-125] PSS operating point retained for pxf", "operating point retained" in log)
check("[E-125] pxf sweep announced (adjoint)",
      re.search(r"PXF sweep:.*\(adjoint\)", log) is not None, log[-400:])

xf = col(log, "mag(xf)")
check(f"[E-125] pxf produced a transfer vector (got {len(xf)} points)", len(xf) >= 5,
      f"{len(xf)} pts")
if xf:
    worst = max(abs(v - Hlp(f)) / Hlp(f) for f, v in xf)
    check(f"[E-125] pxf sideband-0 transfer == low-pass |H(f)| = 1/sqrt(1+(2*pi*f*R*C)^2) "
          f"(worst rel err {worst:.2e}) -- equals the PAC transfer by reciprocity",
          worst < 0.02, f"worst {worst:.3e}")
    flo, vlo = xf[0]; fhi, vhi = xf[-1]
    check(f"[E-125] low-f {flo:.4g}Hz |xf| = {Hlp(flo):.4g} (got {vlo:.4g})",
          abs(vlo - Hlp(flo)) / Hlp(flo) < 0.02, str(vlo))
    check(f"[E-125] high-f {fhi:.4g}Hz |xf| = {Hlp(fhi):.4g} (got {vhi:.4g})",
          abs(vhi - Hlp(fhi)) / Hlp(fhi) < 0.02, str(vhi))

for sbname in ("mag(xf_usb1)", "mag(xf_lsb1)"):
    v = col(log, sbname)
    check(f"[E-125] conversion transfer {sbname} vector exists", len(v) >= 5, f"{len(v)} pts")
    if v:
        peak = max(m for _f, m in v)
        check(f"[E-125] {sbname} ~ 0 (no conversion for a linear circuit, peak {peak:.2e})",
              peak < 1e-6, f"peak {peak:.3e}")

print()
print(("ALL PASS" if passed == checks else "FAILURES")
      + f": {passed} passed, {checks - passed} failed")
raise SystemExit(0 if passed == checks else 1)
