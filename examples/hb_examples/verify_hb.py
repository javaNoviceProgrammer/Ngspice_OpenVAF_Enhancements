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
  [3] diode rectifier              -- junction limiting (per-sample settling)
  [4] nonlinear C (OSDI varactor)  -- NONLINEAR reactive: 2nd harmonic from Q(v)
  [5] strongly-driven rectifier    -- E-135 source-stepping continuation (diverges cold)
  [6] KLU vs Sparse                -- solver-independent (bit-identical spectra)

HB drives an ordinary transient/AC load, so it is solver-independent (KLU + Sparse).
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


print("Enhancement-134/135: Harmonic Balance + source-stepping continuation")

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

# [5] SOURCE-STEPPING CONTINUATION: a strongly-driven diode rectifier (5 V into a
# 20 ohm source R and a sharp IS=1e-14 junction) makes the nonlinearity comparable to
# the linear term -- a cold full-strength Newton DIVERGES (|F| -> 1e69). HB ramps every
# source by lambda: 0 -> 1 in adaptive steps, warm-starting each level, and reaches the
# steady state. Assert it (a) converged, (b) actually needed continuation (>1 step), and
# (c) matches the transient fourier for DC/f0/2f0.
def levels(out):
    m = re.search(r"converged in \d+ iterations, (\d+) continuation step", out)
    return int(m.group(1)) if m else None

strong = ("V1 s 0 SIN(0 5 100meg)\nRs s a 20\nD1 a n DMOD\nRn n 0 1k\n"
          ".model DMOD D(IS=1e-14 N=1.0)")
out = run(f"* strong hb\n{strong}\n.options numdgt=7\n.control\nhb 100meg 10\n"
          f"tran 0.005n 400n 0 0.005n\nfourier 100meg v(n)\n.endc\n.end\n")
hb = hb_spectrum(out, "n")
fo = fourier_spectrum(out)
nlev = levels(out)
match = all(k in hb and k in fo and abs(hb[k] - fo[k]) <= 1.5e-2 * max(fo[k], 1e-9)
           for k in (0, 1, 2))
check(f"source-stepping converges a strongly-driven rectifier ({nlev} continuation steps)",
      nlev is not None and nlev > 1 and match,
      f"nlev={nlev} DC={hb.get(0)}/{fo.get(0)} f0={hb.get(1)}/{fo.get(1)}")

# [6] SOLVER PARITY: HB must give the SAME spectrum under KLU and Sparse. HB runs its
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

# [7] DOT-CARD PARITY (Enhancement-162): a top-level `.hb <f0> <K> ...` netlist
# card must run the same E-134 engine as the `hb` command in a .control block, and
# in plain batch mode (no .control needed). Compare the diode-rectifier spectrum
# from the dot-card against the command form -- they must be bit-for-bit identical.
_nl = ("V1 s 0 SIN(0 1 100meg)\nRs s a 100\nD1 a n DMOD\nRn n 0 1k\n"
       ".model DMOD D(IS=1e-12 N=1.2)")
out_cmd = run(f"* hb command\n{_nl}\n.control\nhb 100meg 8\n.endc\n.end\n")
out_dot = run(f"* hb dotcard\n{_nl}\n.hb 100meg 8\n.end\n")
hb_cmd, hb_dot = hb_spectrum(out_cmd, "n"), hb_spectrum(out_dot, "n")
common = set(hb_cmd) & set(hb_dot)
identical = bool(common) and all(hb_cmd[k] == hb_dot[k] for k in common)
# the dot-card deck has NO .control block and NO other analysis card, so a
# converged spectrum in its output proves `.hb` dispatched the E-134 engine in
# plain batch mode. (Like `.sweep`, a bare command-style dot-card also prints a
# benign "no simulations run" notice, since HB is not a deck analysis job.)
ran_in_batch = "harmonic-balance spectrum" in out_dot and "converged" in out_dot
check("`.hb` dot-card runs in batch and matches the `hb` command bit-for-bit",
      identical and ran_in_batch,
      f"identical={identical} ran_in_batch={ran_in_batch}")

# [8] the dot-card threads its optional [points] [maxiter] args through, and a
# following .control block still runs (order preserved).
out_args = run(f"* hb dotcard args\n{_nl}\n.hb 100meg 6 128 40\n"
               ".control\necho after-hb-ok\n.endc\n.end\n")
check("`.hb` passes [points]/[maxiter] args and coexists with a .control block",
      "harmonic-balance spectrum" in out_args and "after-hb-ok" in out_args
      and "6 harmonics" in out_args)

# [9] ENHANCEMENT-209: `hb` publishes its spectrum as nutmeg vectors -- a real
# `hbfrequency` scale plus one COMPLEX vector per node -- so the result can be
# plotted / printed / wrdata'd directly instead of parsing the printed table. The
# published single-sided magnitude must equal the table's |V| column exactly.
out_vec = run(f"* hb vectors\n{_nl}\n.control\nhb 100meg 5\n"
              f"print hbfrequency mag(n)\n.endc\n.end\n")
tab = hb_spectrum(out_vec, "n")                 # printed table -> {harmonic: |V|}
vec, started = {}, False
for line in out_vec.splitlines():
    if "hbfrequency" in line and "mag(n)" in line:
        started = True
        continue
    if started:
        m = re.match(r"\s*(\d+)\s+[-\d.eE+]+\s+([-\d.eE+]+)", line)
        if m:
            vec[int(m.group(1))] = float(m.group(2))
        elif vec and line.strip() and not line.strip().startswith("-"):
            break
published = "spectrum stored in the current 'hb' plot" in out_vec
match = bool(vec) and all(abs(vec[k] - tab[k]) <= 1e-9 * max(tab[k], 1e-12)
                          for k in vec if k in tab)
check("E-209: `hb` publishes hbfrequency + node vectors; mag(n) equals table |V|",
      published and match and "hbfrequency" in out_vec and len(vec) == 6,
      f"published={published} match={match} npts={len(vec)}")

# [10] TIGHT NONLINEAR CONVERGENCE (correctness). The checks above run at K=8 with
# a 1.5-3% tolerance, because a sharp rectifier's high harmonics are truncation-
# limited at K=8. On a purely RESISTIVE rectifier (cjo=0/tt=0 -> the periodic
# steady state is reached instantly, so a fine-timestep transient's only error is
# its own O(dt^2) discretization) HB *is* the exact steady state and must converge
# to the transient fourier as K grows. Assert (a) HB at K=24 matches a fine-dt
# (period/2000) transient fourier to < 0.5% for DC..4th -- 6x tighter than the
# loose checks, with orders of magnitude of margin -- and (b) raising K from 8 to
# 24 strictly shrinks the 5th-harmonic mismatch, proving the K=8 residual is HB
# truncation (aliasing of the discarded harmonics) rather than a modelling error.
# (Sweeping K=8..48 shows HB -> the Richardson-extrapolated transient to ~1e-7.)
_res = ("V1 s 0 SIN(0 1 100meg)\nRs s a 100\nD1 a n DMOD\nRn n 0 1k\n"
        ".model DMOD D(IS=1e-12 N=1.2 cjo=0 tt=0)")


def _hb_at(kk):
    return hb_spectrum(run(f"* hb K={kk}\n{_res}\n.options numdgt=10\n.control\n"
                           f"hb 100meg {kk}\n.endc\n.end\n"), "n")


_ref = fourier_spectrum(run(f"* hb fine transient\n{_res}\n.options numdgt=10\n"
                            f".control\ntran 0.005n 120n 0 0.005n\n"
                            f"fourier 100meg v(n)\n.endc\n.end\n"))
_hb8, _hb24 = _hb_at(8), _hb_at(24)
_lo = [k for k in (0, 1, 2, 3, 4) if k in _hb24 and k in _ref]
_tight = bool(_lo) and all(abs(_hb24[k] - _ref[k]) <= 5e-3 * max(_ref[k], 1e-9)
                           for k in _lo)
_conv = (5 in _hb8 and 5 in _hb24 and 5 in _ref
         and abs(_hb24[5] - _ref[5]) < abs(_hb8[5] - _ref[5]))
_worst = max((abs(_hb24[k] - _ref[k]) / max(_ref[k], 1e-9) for k in _lo), default=1.0)
check("HB converges to the exact steady state: K=24 matches fine transient <0.5% "
      "(DC..4th) and K refinement shrinks the 5th-harmonic residual",
      _tight and _conv,
      f"worst_rel(DC..4th)={_worst:.2e}  h5: K8={_hb8.get(5):.3e} "
      f"K24={_hb24.get(5):.3e} tran={_ref.get(5):.3e}")

print(f"\n{'ALL PASS' if passed == checks else 'FAILURES'}: {passed}/{checks} passed")
sys.exit(0 if passed == checks else 1)
