#!/usr/bin/env python3
"""
verify_hb.py -- Enhancement-134: Harmonic Balance.

`hb <f0> <K> [points] [maxiter]` finds the periodic steady state in the FREQUENCY
domain by Newton: each node voltage is a truncated Fourier series
V(t)=sum_{k=-K..K} V_k e^{jk w0 t}, and the KCL residual F_k = I_R,k(V) + [dq/dt]_k
- Is_k = 0 is solved with the E-121 conversion matrix as the exact Jacobian.

Key point (the reason nonlinear reactive works with no charge extraction): the
reactive current dq/dt = C(v)*v' by the chain rule, so its spectrum is the
conversion matrix's reactive term applied to V, using the sampled C(t) that already
captures the nonlinearity.

Each check drives a nonlinear circuit with a current tone and compares HB's spectrum
against ngspice's own transient + `fourier` steady-state harmonics (both numpy-free,
read from stdout):

  [1] nonlinear resistor           -- resistive HB, quadratic convergence
  [2] nonlinear R + linear C       -- linear reactive (magnitude AND phase via C)
  [3] nonlinear C (OSDI varactor)  -- NONLINEAR reactive: 2nd harmonic from Q(v)

HB drives an ordinary transient/AC load, so it is solver-independent.
"""
import math
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))  # the examples/ dir, for _setup.py
from _setup import NG as NGSPICE, VAF as OPENVAF

checks = passed = 0
def check(label, ok, detail=""):
    global checks, passed
    checks += 1; passed += bool(ok)
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  [{detail}]" if detail and not ok else ""))


def run(deck, name="_hb"):
    p = os.path.join(HERE, name + ".cir")
    with open(p, "w") as f:
        f.write(deck)
    try:
        r = subprocess.run([NGSPICE, "-b", p], capture_output=True, text=True, timeout=120)
    finally:
        if os.path.exists(p):
            os.remove(p)
    return r.stdout + r.stderr


_HBROW = re.compile(r"^\s+(\w+)\s+(\d+)\s+[-\d.eE+]+\s+([-\d.eE+]+)\s+[-\d.eE+]+\s*$", re.M)
_FROW  = re.compile(r"^\s*(\d+)\s+[-\d.eE+]+\s+([-\d.eE+]+)\s+", re.M)

def hb_spectrum(out, node):
    """HB table -> {harmonic: |V|} for the given node."""
    d = {}
    for m in _HBROW.finditer(out):
        if m.group(1) == node:
            d[int(m.group(2))] = float(m.group(3))
    return d

def fourier_spectrum(out):
    """ngspice `fourier` table -> {harmonic: magnitude}."""
    d = {}
    started = False
    for line in out.splitlines():
        if "Harmonic" in line and "Magnitude" in line:
            started = True
            continue
        if started:
            m = re.match(r"\s*(\d+)\s+[-\d.eE+]+\s+([-\d.eE+]+)\s", line)
            if m:
                d[int(m.group(1))] = abs(float(m.group(2)))
            elif line.strip() == "":
                break
    return d

def iters(out):
    m = re.search(r"converged in (\d+) iterations", out)
    return int(m.group(1)) if m else None


def deck(nl, f0="100meg", K=5, pre="", tstep="0.01n", tstop="200n"):
    return (f"* hb test\n{nl}\n.options numdgt=7\n.control\n{pre}"
            f"hb {f0} {K}\ntran {tstep} {tstop} 0 {tstep}\nfourier {f0} v(n)\n.endc\n.end\n")


def compare(label, nl, harmonics, tol=3e-2, pre="", K=5):
    out = run(deck(nl, pre=pre, K=K))
    hb = hb_spectrum(out, "n")
    fo = fourier_spectrum(out)
    ok = True
    detail = ""
    for k in harmonics:
        a, b = hb.get(k), fo.get(k)
        if a is None or b is None:
            ok = False; detail = f"h{k}: hb={a} four={b}"; continue
        if abs(a - b) > tol * max(b, 1e-9):
            ok = False; detail = f"h{k}: hb={a:.4e} four={b:.4e}"
    check(f"{label}: HB harmonics {harmonics} match transient/fourier", ok, detail)
    return out, hb, fo


print("Enhancement-134: Harmonic Balance")

# [1] nonlinear resistor: fundamental + 3rd harmonic must match, and Newton must
# converge quadratically (a handful of iterations).
out, hb, fo = compare("nonlinear R",
    "I1 0 n SIN(0 0.1m 100meg)\nR1 n 0 1k\nBnl n 0 I = 0.5e-3*V(n)*V(n)*V(n)",
    [1, 3])
n = iters(out)
check(f"HB converges quadratically ({n} iterations)", n is not None and n <= 8, str(n))
check("odd nonlinearity: 2nd harmonic ~0",
      hb.get(2, 1) < 1e-6 * max(hb.get(1, 1), 1e-9))

# [2] nonlinear R + LINEAR C: reactive shifts phase and rolls off the 3rd harmonic;
# HB must still match the transient fourier (magnitude captures the C effect).
compare("nonlinear R + linear C",
    "I1 0 n SIN(0 0.5m 100meg)\nR1 n 0 1k\nBnl n 0 I = 0.5e-3*V(n)*V(n)*V(n)\nC1 n 0 500f",
    [1, 3])

# [4] built-in DIODE half-wave rectifier: a junction device with internal voltage
# limiting -- the sharp rectified waveform has strong DC..3rd harmonics. This is the
# hard case: HB must settle the limited junction at each sample (else the diode looks
# linear). Match the transient fourier for DC..3rd.
compare("diode rectifier (junction limiting)",
    "V1 s 0 SIN(0 1 100meg)\nRs s a 100\nD1 a n DMOD\nRn n 0 1k\n.model DMOD D(IS=1e-12 N=1.2)",
    [0, 1, 2, 3], tol=1.5e-2, K=8)

# [3] NONLINEAR C (OSDI varactor): the V^2 charge term makes a 2nd harmonic a linear
# cap cannot -- the key "full nonlinear reactive" check.
osdi = os.path.join(HERE, "vavar.osdi")
cr = subprocess.run([OPENVAF, os.path.join(HERE, "vavar.va"), "-o", osdi],
                    capture_output=True, text=True, timeout=120)
if os.path.exists(osdi):
    nl = ("I1 0 n SIN(0 0.5m 100meg)\nR1 n 0 1k\nBnl n 0 I = 0.5e-3*V(n)*V(n)*V(n)\n"
          "N1 n 0 varmod\n.model varmod vavar cj0=500f gamma=0.3")
    out, hb, fo = compare("OSDI nonlinear C (varactor)", nl,
                          [1, 2, 3], pre=f"pre_osdi {osdi}\n")
    os.remove(osdi)
    check(f"nonlinear charge makes a real 2nd harmonic (|V2|={hb.get(2,0):.3e} > 1e-3)",
          hb.get(2, 0) > 1e-3)
else:
    check("OSDI varactor: compiled vavar.va", False, cr.stderr.strip()[:80])

# [5] SOLVER PARITY: HB must give the SAME spectrum under KLU and Sparse. HB runs its
# own dense complex Newton solve on the conversion matrix; the sparse/KLU choice only
# affects how the periodic G(t)/C(t) are read from the device matrix (spSetComplex for
# Sparse vs the complex CSC binding for KLU). Run the diode rectifier -- a real,
# junction-LIMITED nonlinear device -- under both and require a bit-close match.
def solver_spectrum(sol):
    nl = ("V1 s 0 SIN(0 1 100meg)\nRs s a 100\nD1 a n DMOD\nRn n 0 1k\n"
          f".model DMOD D(IS=1e-12 N=1.2)\n.options {sol}")
    out = run(f"* hb solver parity\n{nl}\n.control\nhb 100meg 8\n.endc\n.end\n")
    return out, hb_spectrum(out, "n")

outk, hbk = solver_spectrum("klu")
outs, hbs = solver_spectrum("sparse")
klu_active = "Using KLU" in outk
common = set(hbk) & set(hbs)
maxrel = max((abs(hbk[k] - hbs[k]) / max(hbs[k], 1e-9) for k in common), default=1.0)
check("HB is solver-independent: KLU vs Sparse spectra identical",
      klu_active and common and maxrel < 1e-6,
      f"klu_active={klu_active} maxrel={maxrel:.2e}")

print(f"\n{'ALL PASS' if passed == checks else 'FAILURES'}: {passed}/{checks} passed")
sys.exit(0 if passed == checks else 1)
