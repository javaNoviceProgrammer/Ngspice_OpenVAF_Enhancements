#!/usr/bin/env python3
"""Enhancement-177: pnoise noise-folding referee + the folded-flicker frequency fix.

THE REFEREE. The E-175 audit left periodic noise analysis "correct by
construction, not correct by measurement": the folding of device noise through
LPTV conversion had never been checked against anything independent. This
example embeds a from-scratch referee: for the 1-node LPTV-conductance circuit

    VDC(1V) -- R1(10k, noisy) -- node b ;  i_B = (g0 + g1*sin(w0 t))*v(b) ; C1

the conversion matrix is small enough to build directly in Python
(Y_nm = delta_nm*(1/R1 + j*w_n*C1 + g0) + G_{n-m}, G_{+-1} = -+j*g1/2), and

    onoise(f) = sum_k |Z_k(f)|^2 * S(|f + k*f0|)

is plain arithmetic -- a genuinely independent implementation of the same
physics. A TRNOISE transient Monte-Carlo cross-check (no shared code OR theory;
see make_pnoisefold_fig.py) confirms the folding ratio within statistical
error, so the referee itself is anchored to the time domain.

THE BUG IT CAUGHT. The stationary pnoise/qpnoise/phasenoise sideband loops set
the noise-evaluation frequency ONCE to the output frequency. But the
sideband-k adjoint carries noise that ORIGINATES at |f + k*f0| -- a
frequency-dependent source PSD (flicker 1/f, noise_table) must be evaluated
there. Pre-fix pnoise reproduced the referee's deliberately-wrong
"evaluate-everything-at-f" model DIGIT-FOR-DIGIT (1.114323e-14 vs
1.114323e-14 at 1 kHz -- a 21% overestimate on this circuit, unbounded as
f << f0); post-fix it reproduces the correct model digit-for-digit
(9.175472e-15). White noise is frequency-flat and LTI circuits have no k != 0
transfer, which is why every earlier check passed (the E-171/E-175
accidental-correctness pattern, third occurrence).

The cyclostationary mode's time-domain identity assumes a frequency-flat
source PSD (exact for modulated-white noise; documented in dcpss.c) -- use the
stationary mode when folded flicker matters.

Checks (both solvers via the dual-solver harness):
  [1] WHITE folding: pnoise == referee at 3 frequencies (<=0.1%) -- the
      sideband bookkeeping (adjoint, thermal density, sum) is measured-correct.
  [2] FLICKER folding: pnoise == referee-with-correct-source-frequencies
      (<=0.5%; sample-0 bias read from the retained orbit).
  [3] the pre-fix signature is ABSENT (pnoise is NOT the wrong-frequency
      model, which is 21% higher at 1 kHz on this circuit).
  [4] pumping strengthens the noise floor by the referee's predicted ratio
      (folding is real and quantitatively right: about 1.86x here).
  [5] LTI limit: with g1 = 0 the pnoise spectrum equals plain .noise.

Every SPICE deck starts with a title line (SPICE treats line 1 as the title!).
"""
import math
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from _setup import NG as NGSPICE
from _setup import check_both_solvers as _check_both_solvers
_check_both_solvers(__file__)

passed = failed = 0


def check(name, ok, detail=""):
    global passed, failed
    if ok:
        passed += 1
        print(f"  PASS  {name} {detail}")
    else:
        failed += 1
        print(f"  FAIL  {name} {detail}")


def run_deck(name, deck):
    path = os.path.join(HERE, name)
    open(path, "w").write(deck)
    r = subprocess.run([NGSPICE, "-b", path], capture_output=True, text=True,
                       timeout=300, cwd=HERE)
    return r.stdout + r.stderr


def onoise_table(out):
    pts = {}
    for m in re.finditer(r"^\d+\s+([\d.eE+-]+)\s+([\d.eE+-]+)", out, re.M):
        pts[float(m.group(1))] = float(m.group(2))
    return pts


# ---------------- the independent referee (pure python) ----------------
G0, G1, R1, C1, F0 = 1e-3, 0.8e-3, 10e3, 100e-12, 1e6
KB, T = 1.380649e-23, 300.15                     # ngspice default 27 C
KF, AF, EF = 1e-9, 2.0, 1.0
M = 5                                            # 11 sidebands (Harmonics=6)


def zrow(f, g1):
    """row of Y^-1 at output sideband 0: transimpedance from injection at b,
    sideband k, to v(b) at sideband 0. Pure-python complex Gaussian solve."""
    n = 2 * M + 1
    A = [[0j] * n for _ in range(n)]
    for ni in range(n):
        wn = 2 * math.pi * (f + (ni - M) * F0)
        A[ni][ni] += 1.0 / R1 + 1j * wn * C1 + G0
        if ni + 1 < n:
            A[ni][ni + 1] += +1j * g1 / 2
        if ni - 1 >= 0:
            A[ni][ni - 1] += -1j * g1 / 2
    # solve A^T x = e_M  (adjoint row) via Gaussian elimination
    b = [0j] * n
    b[M] = 1.0
    AT = [[A[c][r] for c in range(n)] for r in range(n)]
    for col in range(n):
        piv = max(range(col, n), key=lambda r: abs(AT[r][col]))
        AT[col], AT[piv] = AT[piv], AT[col]
        b[col], b[piv] = b[piv], b[col]
        for r in range(col + 1, n):
            fct = AT[r][col] / AT[col][col]
            for c in range(col, n):
                AT[r][c] -= fct * AT[col][c]
            b[r] -= fct * b[col]
    x = [0j] * n
    for r in range(n - 1, -1, -1):
        acc = b[r]
        for c in range(r + 1, n):
            acc -= AT[r][c] * x[c]
        x[r] = acc / AT[r][r]
    return x


def referee(f, g1, flicker_I=None, wrong_freq=False):
    Z = zrow(f, g1)
    tot = 0.0
    for mi in range(2 * M + 1):
        k = mi - M
        fsrc = f if wrong_freq else abs(f + k * F0)
        S = 4 * KB * T / R1
        if flicker_I is not None:
            S += KF * flicker_I ** AF / (fsrc ** EF)
        tot += abs(Z[mi]) ** 2 * S
    return tot


BODY = """V1 lo 0 SIN(0 1 1meg)
VDC a 0 DC 1
R1 a b {rmod}10k
B1 b 0 I=(1m + {g1}*v(lo))*v(b)
C1 b 0 100p
"""

# ---------------- [1] white folding vs referee ----------------
deck = ("* white folding\n" + BODY.format(rmod="", g1="0.8m") +
        ".pnoise 1meg 1u b 1024 6 50 5u b vdc lin 3 50k 150k\n"
        ".control\nset sqrnoise\nrun\nprint onoise_spectrum\n.endc\n.end\n")
out = run_deck("_w.cir", deck)
pts = onoise_table(out)
ok = len(pts) == 3 and all(
    abs(v - referee(f, G1)) <= 1e-3 * referee(f, G1) for f, v in pts.items())
check("[1] WHITE folding: pnoise == independent referee at 3 freqs (<=0.1%)",
      ok, f"(50k: pnoise={pts.get(5e4, 0):.5e} ref={referee(5e4, G1):.5e})")

# ---------------- [2]+[3] flicker folding ----------------
deck = ("* flicker folding\n" +
        BODY.format(rmod="rmod ", g1="0.8m") +
        ".model rmod R(kf=1e-9 af=2 ef=1)\n"
        ".pnoise 1meg 1u b 1024 6 50 5u b vdc lin 3 1k 100k\n"
        ".control\nset sqrnoise\nrun\nprint onoise_spectrum\nsetplot pss1\nwrdata _pnf_td.csv v(b)\n.endc\n.end\n")
out = run_deck("_f.cir", deck)
pts = onoise_table(out)
rows = [l.split() for l in open(os.path.join(HERE, "_pnf_td.csv")) if l.strip()]
vb0 = float(rows[0][1])                      # sample-0 bias (stationary pnoise uses it)
I0 = (1.0 - vb0) / R1
ok = len(pts) == 3 and all(
    abs(v - referee(f, G1, I0)) <= 5e-3 * referee(f, G1, I0) for f, v in pts.items())
check("[2] FLICKER folding: pnoise == referee with per-sideband source freqs (<=0.5%)",
      ok, f"(1k: pnoise={pts.get(1e3, 0):.5e} ref={referee(1e3, G1, I0):.5e})")
wrong = referee(1e3, G1, I0, wrong_freq=True)
ok = 1e3 in pts and abs(pts[1e3] - wrong) > 0.1 * wrong
check("[3] pre-fix signature ABSENT (pnoise != wrong-frequency model, 21% higher)",
      ok, f"(wrong-model value would be {wrong:.5e})")

# ---------------- [4] the folding ratio is real ----------------
deck = ("* nopump\n" + BODY.format(rmod="", g1="0") +
        ".pnoise 1meg 1u b 1024 6 50 5u b vdc lin 3 50k 150k\n"
        ".control\nset sqrnoise\nrun\nprint onoise_spectrum\n.endc\n.end\n")
out = run_deck("_n.cir", deck)
npts = onoise_table(out)
pdeck = ("* pump\n" + BODY.format(rmod="", g1="0.8m") +
         ".pnoise 1meg 1u b 1024 6 50 5u b vdc lin 3 50k 150k\n"
         ".control\nset sqrnoise\nrun\nprint onoise_spectrum\n.endc\n.end\n")
out = run_deck("_p.cir", pdeck)
ppts = onoise_table(out)
ok = True
for f in (5e4, 1e5, 1.5e5):
    want = referee(f, G1) / referee(f, 0.0)
    got = ppts[f] / npts[f]
    if abs(got - want) > 1e-3 * want:
        ok = False
check("[4] pump/no-pump folding ratio == referee ratio (~1.86x, TRNOISE-MC confirmed)",
      ok, f"(50k ratio: pnoise={ppts[5e4]/npts[5e4]:.4f} ref={referee(5e4, G1)/referee(5e4, 0.0):.4f})")

# ---------------- [5] LTI limit: pnoise(g1=0) == .noise ----------------
deck = ("* lti noise\n" + BODY.format(rmod="", g1="0").replace("VDC a 0 DC 1", "VDC a 0 DC 1 AC 1") +
        ".noise v(b) vdc lin 3 50k 150k 1\n"
        ".control\nset sqrnoise\nrun\nsetplot noise1\nprint onoise_spectrum\n.endc\n.end\n")
out = run_deck("_l.cir", deck)
lpts = onoise_table(out)
# Enhancement-193: both analyses now honor `sqrnoise`; with it set here, both
# report the squared V^2/Hz density, so pnoise(g1=0) equals plain .noise directly
# (before E-193 pnoise was V^2/Hz while .noise defaulted to V/sqrt(Hz)).
ok = len(lpts) == 3 and all(abs(npts[f] - lpts[f]) <= 1e-6 * lpts[f] for f in lpts)
check("[5] LTI limit: pnoise(g1=0) == plain .noise (both V^2/Hz via sqrnoise)", ok,
      f"(50k: pnoise={npts.get(5e4, 0):.6e} noise={lpts.get(5e4, 0):.6e})")

print(f"\n{passed} passed, {failed} failed")
raise SystemExit(1 if failed else 0)
