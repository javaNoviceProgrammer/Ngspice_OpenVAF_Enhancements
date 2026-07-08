#!/usr/bin/env python3
"""
verify_noisetable.py -- verifies Enhancement-109 (noise_table / noise_table_log
interpolation per the LRM), through the committed
openvaf-r + ngspice.

LRM 4.6.4.3: noise_table performs piecewise-LINEAR interpolation of the power
over FREQUENCY. LRM 4.6.4.4: noise_table_log takes the same (Hz, power) input
but interpolates LOG-LOG: P = 10^(lerp of log10 p over log10 f). Both clamp to
the endpoint powers outside the tabulated range. Before this fix, noise_table
interpolated linearly over log10(f), and noise_table_log expected a
log10-frequency input and interpolated the raw power.

  [1] noisetable_demo.va compiles (both forms)
  [2] noise_table: onoise at 10/100/1000 Hz matches the LINEAR-in-f law
      (at 100 Hz: S = 1.1818e-12, NOT the 2e-12 the old lin-log gave)
  [3] noise_table_log: onoise matches the LOG-LOG law (at 100 Hz: S = 1e-14)
  [4] clamping: below/above the tabulated range the PSD holds the endpoint
"""
import math
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from _setup import VAF as OPENVAF, NG as NGSPICE

R = 1e3   # 1/G of the device conductance

checks = passed = 0
def check(label, ok, detail=""):
    global checks, passed
    checks += 1; passed += bool(ok)
    print(f"[{'PASS' if ok else 'FAIL'}] {label}" + (f"  ({detail})" if detail and not ok else ""))

def run_noise(kind, fstart, fstop):
    deck = (f"* noisetable kind={kind}\n"
            "vin in 0 dc 0 ac 1\nrin in out 1t\nn1 out 0 dut\n"
            f".model dut noisetable_demo kind={kind}\n"
            ".control\npre_osdi noisetable_demo.osdi\n"
            f"noise v(out) vin dec 10 {fstart} {fstop}\n"
            "setplot noise1\nlet os = onoise_spectrum\nlet fr = frequency\n"
            "wrdata _nt_out.txt os\n.endc\n.end\n")
    with open(os.path.join(HERE, "_nt.cir"), "w") as f:
        f.write(deck)
    subprocess.run([NGSPICE, "-b", "_nt.cir"], capture_output=True, text=True, cwd=HERE)
    pts = []
    with open(os.path.join(HERE, "_nt_out.txt")) as f:
        for line in f:
            parts = line.split()
            if len(parts) >= 2:
                pts.append((float(parts[0]), float(parts[1])))
    return pts

def at(pts, freq):
    return min(pts, key=lambda p: abs(p[0] - freq))[1]

for f in ("noisetable_demo.osdi", "_nt.cir", "_nt_out.txt"):
    p = os.path.join(HERE, f)
    if os.path.exists(p):
        os.remove(p)

r = subprocess.run([OPENVAF, "noisetable_demo.va"], capture_output=True, text=True, cwd=HERE)
compiled = r.returncode == 0 and os.path.exists(os.path.join(HERE, "noisetable_demo.osdi"))
check("noisetable_demo.va compiles", compiled,
      (r.stderr or r.stdout).strip().splitlines()[0] if (r.stderr or r.stdout).strip() else "")

if compiled:
    tol = 2e-3
    # [2] linear form
    pts = run_noise(0, 10, 1000)
    def S_lin(f):
        f = min(max(f, 10.0), 1000.0)
        return 1e-12 + (3e-12 - 1e-12) * (f - 10.0) / (1000.0 - 10.0)
    for f in (10.0, 100.0, 1000.0):
        exp = math.sqrt(S_lin(f)) * R
        got = at(pts, f)
        check(f"noise_table linear-in-f @ {f:g} Hz", abs(got - exp) <= tol * exp,
              f"got {got:.6e} expected {exp:.6e}")
    # [3] log-log form
    pts = run_noise(1, 10, 1000)
    def S_log(f):
        f = min(max(f, 10.0), 1000.0)
        lf = (math.log10(f) - 1.0) / (3.0 - 1.0)
        return 10 ** (math.log10(1e-12) + (math.log10(1e-16) - math.log10(1e-12)) * lf)
    for f in (10.0, 100.0, 1000.0):
        exp = math.sqrt(S_log(f)) * R
        got = at(pts, f)
        check(f"noise_table_log log-log @ {f:g} Hz", abs(got - exp) <= tol * exp,
              f"got {got:.6e} expected {exp:.6e}")
    # [4] clamping outside the range (1 Hz below, 10 kHz above, linear form)
    pts = run_noise(0, 1, 100000)
    lo = at(pts, 1.0);  lo_exp = math.sqrt(1e-12) * R
    hi = at(pts, 1e5);  hi_exp = math.sqrt(3e-12) * R
    check("clamp below range holds S(fmin)", abs(lo - lo_exp) <= tol * lo_exp,
          f"got {lo:.6e} expected {lo_exp:.6e}")
    check("clamp above range holds S(fmax)", abs(hi - hi_exp) <= tol * hi_exp,
          f"got {hi:.6e} expected {hi_exp:.6e}")

for f in ("noisetable_demo.osdi", "_nt.cir", "_nt_out.txt"):
    p = os.path.join(HERE, f)
    if os.path.exists(p):
        os.remove(p)

print(f"\n{passed}/{checks} checks passed")
raise SystemExit(0 if passed == checks else 1)
