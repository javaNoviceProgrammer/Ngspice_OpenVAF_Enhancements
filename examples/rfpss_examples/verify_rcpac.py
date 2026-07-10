#!/usr/bin/env python3
"""
verify_rcpac.py -- verifies the `.pac` command (Enhancement-122): a periodic-AC
frequency sweep built on PSS.

`.pac` runs PSS to find the periodic operating point, then sweeps a small-signal
input frequency and, at each point, solves the harmonic conversion matrix
(Enhancement-121) built from the periodic Jacobian G_k, C_k -- emitting the
0-th-sideband node responses as a complex plot vs frequency.

For the driven RC low-pass (`R=1k`, `C=1n`) the circuit is linear, so its periodic
Jacobian is time-invariant: the conversion matrix is block-diagonal and its 0-block
is the ordinary AC matrix at the input frequency. The PAC sideband-0 response at the
osc node `b` (unit current injected there) therefore equals the AC driving-point
impedance across the whole sweep:

    |Z(f)| = 1 / |1/R + j*2*pi*f*C|

`.pac` syntax:
    .pac Fguess StabTime OscNode Points Harmonics SC_iter Steady_coeff \\
         <DEC|OCT|LIN> Npts Fstart Fstop

NOTE: PAC runs a PSS shooting method (~2 minutes) and is run here under the Sparse
solver only (the demanding case); the conversion-matrix path is solver-agnostic and
already exercised under KLU by the E-120/121 sampling path.
"""
import math
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from _setup import NG as NGSPICE

R, C, f0 = 1e3, 1e-9, 1e6

checks = passed = 0
def check(label, ok, detail=""):
    global checks, passed
    checks += 1; passed += bool(ok)
    print(f"[{'PASS' if ok else 'FAIL'}] {label}" + (f"  ({detail})" if detail and not ok else ""))

def Zana(f):
    """analytic AC driving-point |Z| at node b: 1/|1/R + j*2*pi*f*C|."""
    return 1.0 / math.hypot(1.0 / R, 2 * math.pi * f * C)

# --- run rc_pac.cir under Sparse ---
deck = "rc_pac.cir"
with open(os.path.join(HERE, deck)) as f:
    lines = f.read().split("\n")
lines.insert(1, ".option sparse")
name = "_rcpac_sparse.cir"
with open(os.path.join(HERE, name), "w") as f:
    f.write("\n".join(lines))
r = subprocess.run([NGSPICE, "-b", name], capture_output=True, text=True, cwd=HERE)
os.remove(os.path.join(HERE, name))
log = r.stdout + r.stderr

# the analysis ran
check("`.pac` is recognized (not an unimplemented dot command)",
      "unimplemented" not in log.lower() and "unsupported" not in log.lower(), log[-400:])
check("[E-122] PSS operating point retained for the sweep",
      "operating point retained" in log)
msweep = re.search(r"PAC sweep:\s*(dec|oct|lin) from\s*([-\d.eE+]+)\s*to\s*([-\d.eE+]+)\s*Hz", log)
check("[E-122] PAC sweep announced", msweep is not None, log[-400:])

# parse the printed mag(b) table: rows "<idx> <freq> <mag>"
pts = []
for line in log.splitlines():
    p = line.split()
    if len(p) == 3:
        try:
            idx, freq, mag = int(p[0]), float(p[1]), float(p[2])
            if freq > 0:
                pts.append((freq, mag))
        except ValueError:
            pass
check(f"[E-122] PAC produced a frequency-swept output vector (got {len(pts)} points)",
      len(pts) >= 5, f"{len(pts)} points")

# every swept point matches the analytic AC driving-point impedance
if pts:
    worst = max(abs(m - Zana(f)) / Zana(f) for f, m in pts)
    check(f"[E-122] PAC sideband-0 |b(f)| == AC driving-point |Z(f)| across the sweep "
          f"(worst rel err {worst:.2e})", worst < 0.02, f"worst {worst:.3e}")
    # spot-check endpoints against hand values
    flo, mlo = pts[0]
    fhi, mhi = pts[-1]
    check(f"[E-122] low-f point ~ |Z({flo:.4g})| = {Zana(flo):.4g} (got {mlo:.4g})",
          abs(mlo - Zana(flo)) / Zana(flo) < 0.02, str(mlo))
    check(f"[E-122] high-f point ~ |Z({fhi:.4g})| = {Zana(fhi):.4g} (got {mhi:.4g})",
          abs(mhi - Zana(fhi)) / Zana(fhi) < 0.02, str(mhi))

# --- Enhancement-123: source-referenced stimulus + multi-sideband output ---
# rc_pac_src.cir drives V1 with `AC 1`, so the PAC stimulus is that netlist source
# (a periodic-AC transfer) rather than a unit current at the osc node -- the
# sideband-0 response at b is now the low-pass TRANSFER |H(f)| = 1/sqrt(1+(2*pi*f*R*C)^2)
# (0.998 -> 0.157), not the driving-point impedance. The trailing `2` asks for 2
# conversion sidebands each side; for this linear circuit b_usb1/b_lsb1 are ~0.
def Hlp(f):
    return 1.0 / math.hypot(1.0, 2 * math.pi * f * R * C)

def cols_by_header(log):
    """parse ngspice `print` tables -> {vector_name: [(freq, value), ...]}."""
    out, cur = {}, None
    for line in log.splitlines():
        m = re.search(r"Index\s+frequency\s+(\S+)", line)
        if m:
            cur = m.group(1); out.setdefault(cur, [])
            continue
        p = line.split()
        if cur and len(p) == 3:
            try:
                out[cur].append((float(p[1]), float(p[2])))
            except ValueError:
                pass
    return out

with open(os.path.join(HERE, "rc_pac_src.cir")) as f:
    lines = f.read().split("\n")
lines.insert(1, ".option sparse")
name = "_rcpacsrc_sparse.cir"
with open(os.path.join(HERE, name), "w") as f:
    f.write("\n".join(lines))
r2 = subprocess.run([NGSPICE, "-b", name], capture_output=True, text=True, cwd=HERE)
os.remove(os.path.join(HERE, name))
log2 = r2.stdout + r2.stderr

check("[E-123] PAC uses the netlist AC source as the stimulus",
      "stimulus: netlist AC source" in log2, log2[-400:])
msb = re.search(r"stimulus:.*?;\s*(\d+)\s*sidebands", log2)
check("[E-123] multi-sideband output announced (5 sidebands for maxsideband=2)",
      msb is not None and int(msb.group(1)) == 5, msb.group(1) if msb else None)

cols = cols_by_header(log2)
b = cols.get("mag(b)", [])
check(f"[E-123] source-referenced sideband-0 is the AC transfer, not the impedance "
      f"(got {b[0][1]:.4g} at {b[0][0]:.4g} Hz -> expect {Hlp(b[0][0]):.4g})" if b else
      "[E-123] mag(b) parsed",
      len(b) >= 5 and max(abs(m - Hlp(f)) / Hlp(f) for f, m in b) < 0.02,
      f"worst {max(abs(m-Hlp(f))/Hlp(f) for f,m in b):.2e}" if b else "no data")

for sbname in ("mag(b_usb1)", "mag(b_lsb1)"):
    v = cols.get(sbname, [])
    check(f"[E-123] conversion sideband {sbname} vector exists", len(v) >= 5,
          f"{len(v)} points")
    if v:
        peak = max(m for _f, m in v)
        check(f"[E-123] {sbname} ~ 0 (no conversion for a linear circuit, peak {peak:.2e})",
              peak < 1e-9, f"peak {peak:.3e}")

print()
print(("ALL PASS" if passed == checks else "FAILURES")
      + f": {passed} passed, {checks - passed} failed")
raise SystemExit(0 if passed == checks else 1)
