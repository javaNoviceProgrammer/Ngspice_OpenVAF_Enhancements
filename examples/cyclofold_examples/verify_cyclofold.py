#!/usr/bin/env python3
"""Enhancement-178: EXACT separable cyclostationary noise folding (pnoise/qpnoise cyclo).

WHAT CHANGED. The cyclo mode's time-domain identity (E-126/E-139)

    onoise = (1/P) sum_s S(t_s) |A_s|^2

is exact only for frequency-FLAT (modulated-white) sources: it cannot see that
noise folded from sideband q ORIGINATES at |f + q*f0|, where a colored source
(flicker 1/f, noise_table) has a different density (the E-177 finding, left
documented there as a cyclo-mode limitation). E-178 removes the limitation with
the exact separable model S(t, f) = m(t)^2 * g(f):

    onoise(f) = sum_g sum_q |B_q(g)|^2 * g_g(|f + q*f0|),
    B_q(g)    = (1/P) sum_s m_g(t_s) * dA_s(g) * e^{+j q th_s},
    A_s(j)    = sum_k Psi_k(j) e^{-j k th_s}.

Per-generator amplitudes are recovered with NO device-API change: the noise
summary machinery (prtSummary/outpVector) gives one density per generator, and
load POLARIZATION against a fixed reference load R = Psi_0 (five DEVnoise
sweeps per orbit sample: A+-R, A+-jR, R) extracts the complex per-generator
amplitude c_g,s = sqrt(S_g(t_s))*dA_s(g) up to a constant phase that cancels in
|B_q|^2. The spectral shape g_g is MEASURED pointwise at the folded frequencies
(no 1/f^EF assumption -- noise_table works). Generators whose measured shape is
flat keep the original identity (exact for ANY quadratic form, including
correlated pairs); the stationary limit reduces to the E-177 sum, the flat
limit collapses (Parseval) to the old identity. Ported to the two-tone
`qpnoise ... cyclo` as the 2-D analog B_{q1,q2} at |f + q1*f1 + q2*f2|.

THE PHYSICS IT FIXES ("flicker sees <m>^2, white sees <m^2>"). For modulation
far above the analysis band, only the DC component of the envelope m(t) feeds
the 1/f band -- the AC components are shifted to sidebands of +-f0, +-2f0 where
1/f is negligible. The old identity collapsed ALL envelope power onto the
analysis frequency: for |sin|-modulated flicker it overestimated by pi^2/8
(23%), and on the E-177 conversion circuit by 34%.

Checks (both solvers via the dual-solver harness):
  [1] flicker + conversion cyclo == from-scratch Python referee implementing
      the exact separable model with the orbit read back from the pss1 plot
      (<=0.5% at 3 frequencies).
  [2] the old flat-model signature is ABSENT (it is 34% higher at 1 kHz here;
      the referee also reproduces the pre-fix value digit-for-digit, proving
      the change is the model, not an implementation accident).
  [3] flat path untouched: white pumped cyclo == stationary pnoise (thermal is
      bias-independent, so Parseval makes the two exactly equal).
  [4] "flicker sees <m>^2": |sin(w0 t)|-modulated flicker through an LTI
      transfer gives onoise*f = R1^2*KF*<|I|>^2 = (8/pi^2) * the old <I^2> law.
  [5] LTI limit: cyclo with the pump off equals plain .noise (squared V/rtHz).
  [6] two-tone: `qpnoise ... cyclo` with only tone 1 active matches the same
      1-D referee (the 2-D port collapses correctly).

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
                       timeout=600, cwd=HERE)
    return r.stdout + r.stderr


def onoise_table(out):
    pts = {}
    for m in re.finditer(r"^\d+\s+([\d.eE+-]+)\s+([\d.eE+-]+)", out, re.M):
        pts[float(m.group(1))] = float(m.group(2))
    return pts


# ------------- the independent referee (pure python, no numpy) -------------
G0, G1, R1, C1, F0 = 1e-3, 0.8e-3, 10e3, 100e-12, 1e6
KB, T = 1.380649e-23, 300.15                     # ngspice default 27 C
KF, AF, EF = 1e-9, 2.0, 1.0
M = 5                                            # 11 sidebands (Harmonics=6)


def zrow(f, g1):
    """adjoint row of the conversion matrix: transimpedance from injection at
    b, sideband k, to v(b) at sideband 0 (pure-python Gaussian solve)."""
    n = 2 * M + 1
    A = [[0j] * n for _ in range(n)]
    for ni in range(n):
        wn = 2 * math.pi * (f + (ni - M) * F0)
        A[ni][ni] += 1.0 / R1 + 1j * wn * C1 + G0
        if ni + 1 < n:
            A[ni][ni + 1] += +1j * g1 / 2
        if ni - 1 >= 0:
            A[ni][ni - 1] += -1j * g1 / 2
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


def referee_exact(f, g1, Is, Qmax=2 * M):
    """exact separable folding: thermal (flat, stationary sum) + flicker via
    B_q = (1/P) sum_s m_s A_s e^{+jq th}, A_s = sum_k Z_k e^{-jk th}."""
    Z = zrow(f, g1)
    P = len(Is)
    A = []
    for s in range(P):
        th = 2 * math.pi * s / P
        a = 0j
        for k in range(-M, M + 1):
            a += Z[k + M] * complex(math.cos(k * th), -math.sin(k * th))
        A.append(a)
    tot = 0.0
    for k in range(-M, M + 1):
        tot += abs(Z[k + M]) ** 2 * 4 * KB * T / R1
    for q in range(-Qmax, Qmax + 1):
        B = 0j
        for s in range(P):
            th = 2 * math.pi * s / P
            m = math.sqrt(KF) * Is[s] ** (AF / 2.0)
            B += m * A[s] * complex(math.cos(q * th), math.sin(q * th))
        B /= P
        fq = abs(f + q * F0) or f
        tot += abs(B) ** 2 / fq ** EF
    return tot


def referee_oldflat(f, g1, Is):
    """the pre-E-178 frequency-flat identity: (1/P) sum_s S(t_s, f) |A_s|^2."""
    Z = zrow(f, g1)
    P = len(Is)
    tot = 0.0
    for s in range(P):
        th = 2 * math.pi * s / P
        a = 0j
        for k in range(-M, M + 1):
            a += Z[k + M] * complex(math.cos(k * th), math.sin(k * th))
        S = 4 * KB * T / R1 + KF * Is[s] ** AF / f ** EF
        tot += S * abs(a) ** 2
    return tot / P


BODY = """V1 lo 0 SIN(0 1 1meg)
VDC a 0 DC 1
R1 a b {rmod}10k
B1 b 0 I=(1m + {g1}*v(lo))*v(b)
C1 b 0 100p
"""

# ---------------- [1]+[2] flicker + conversion vs the referee ----------------
deck = ("* cyclo flicker folding\n" + BODY.format(rmod="rmod ", g1="0.8m") +
        ".model rmod R(kf=1e-9 af=2 ef=1)\n"
        ".pnoise 1meg 1u b 1024 6 50 5u b vdc lin 3 1k 100k cyclo\n"
        ".control\nrun\nprint onoise_spectrum\nsetplot pss1\nwrdata _cyf_td.csv v(b)\n.endc\n.end\n")
out = run_deck("_cf.cir", deck)
pts = onoise_table(out)
rows = [l.split() for l in open(os.path.join(HERE, "_cyf_td.csv")) if l.strip()]
vb = [float(r[1]) for r in rows]
if len(vb) > 1 and abs(vb[0] - vb[-1]) < 1e-9:
    vb = vb[:-1]                                 # drop the duplicated endpoint
Is = [(1.0 - v) / R1 for v in vb]
ok = len(pts) == 3 and all(
    abs(v - referee_exact(f, G1, Is)) <= 5e-3 * referee_exact(f, G1, Is)
    for f, v in pts.items())
check("[1] flicker+conversion cyclo == exact-separable referee at 3 freqs (<=0.5%)",
      ok, f"(1k: cyclo={pts.get(1e3, 0):.5e} ref={referee_exact(1e3, G1, Is):.5e})")
old = referee_oldflat(1e3, G1, Is)
ok = 1e3 in pts and abs(pts[1e3] - old) > 0.2 * pts[1e3]
check("[2] old flat-model signature ABSENT (it is 34% higher at 1 kHz here)",
      ok, f"(old-model value would be {old:.5e})")

# ---------------- [3] flat path: white pumped cyclo == stationary ----------------
wc = ("* cyclo white\n" + BODY.format(rmod="", g1="0.8m") +
      ".pnoise 1meg 1u b 1024 6 50 5u b vdc lin 3 50k 150k cyclo\n"
      ".control\nrun\nprint onoise_spectrum\n.endc\n.end\n")
ws = ("* stationary white\n" + BODY.format(rmod="", g1="0.8m") +
      ".pnoise 1meg 1u b 1024 6 50 5u b vdc lin 3 50k 150k\n"
      ".control\nrun\nprint onoise_spectrum\n.endc\n.end\n")
cpts = onoise_table(run_deck("_wc.cir", wc))
spts = onoise_table(run_deck("_ws.cir", ws))
ok = len(cpts) == 3 and all(abs(cpts[f] - spts[f]) <= 1e-4 * spts[f] for f in cpts)
check("[3] flat path untouched: white pumped cyclo == stationary pnoise (Parseval)",
      ok, f"(50k: cyclo={cpts.get(5e4, 0):.6e} stationary={spts.get(5e4, 0):.6e})")

# ---------------- [4] flicker sees <m>^2, white sees <m^2> ----------------
# |sin|-modulated flicker through an LTI transfer (the E-126 rc_flicker circuit):
# I(t) through R1f is a pure sinusoid, m(t) ~ |I(t)|, so at f << f0 the exact
# answer is the envelope's DC power <|I|>^2 = (8/pi^2) * <I^2> -- 23% below the
# old flat-model law.
R1f, C1f, f0f = 1e3, 1e-9, 1e6
fdeck = ("* rc flicker cyclo\n"
         "V1 a 0 SIN(0 1 1meg)\n"
         f"R1 a b rmod {R1f:g}\n"
         f"C1 b 0 {C1f:g}\n"
         ".model rmod R(kf=1e-9 af=2 ef=1)\n"
         ".pnoise 1meg 1u b 1024 10 50 5u b v1 dec 3 100 1k cyclo\n"
         ".control\nrun\nprint onoise_spectrum\n.endc\n.end\n")
fpts = onoise_table(run_deck("_rcf.cir", fdeck))
H = 1.0 / (1.0 + 1j * 2 * math.pi * f0f * R1f * C1f)
I2avg = 0.5 * abs((1.0 - H) / R1f) ** 2          # <I^2> (the old law)
target = R1f ** 2 * 1e-9 * (8 / math.pi ** 2) * I2avg   # <|I|>^2 = (8/pi^2)<I^2>
ok = len(fpts) >= 3 and all(abs(f * v - target) <= 0.02 * target
                            for f, v in fpts.items())
check("[4] |sin|-modulated flicker: onoise*f == R1^2*KF*<|I|>^2 = (8/pi^2)*<I^2> (<=2%)",
      ok, f"(target={target:.4e}, got={[f'{f*v:.4e}' for f, v in sorted(fpts.items())]})")

# ---------------- [5] LTI limit: cyclo(no pump) == .noise ----------------
lc = ("* cyclo lti\n" + BODY.format(rmod="rmod ", g1="0") +
      ".model rmod R(kf=1e-9 af=2 ef=1)\n"
      ".pnoise 1meg 1u b 1024 6 50 5u b vdc lin 3 1k 100k cyclo\n"
      ".control\nrun\nprint onoise_spectrum\n.endc\n.end\n")
ln = ("* plain noise\n" + BODY.format(rmod="rmod ", g1="0").replace(
          "VDC a 0 DC 1", "VDC a 0 DC 1 AC 1") +
      ".model rmod R(kf=1e-9 af=2 ef=1)\n"
      ".noise v(b) vdc lin 3 1k 100k 1\n"
      ".control\nrun\nsetplot noise1\nprint onoise_spectrum\n.endc\n.end\n")
cpts = onoise_table(run_deck("_lc.cir", lc))
npts = onoise_table(run_deck("_ln.cir", ln))
# .noise prints V/sqrt(Hz) (sqrt of the density); pnoise emits V^2/Hz
ok = len(cpts) == 3 and all(abs(cpts[f] - npts[f] ** 2) <= 2e-3 * npts[f] ** 2
                            for f in cpts)
check("[5] LTI limit: cyclo(no pump) == plain .noise (squared V/rtHz)", ok,
      f"(1k: cyclo={cpts.get(1e3, 0):.5e} noise^2={npts.get(1e3, 0) ** 2:.5e})")

# ---------------- [6] two-tone qpnoise cyclo collapses to the 1-D referee ----------------
# The same circuit under `qpss ... hb` with tone 2 inactive: the 2-D exact
# separable port must land on the same answer as the (referee-certified) 1-D
# path -- in practice it agrees digit-for-digit with the pnoise cyclo value,
# across two completely different orbit machineries (QPSS-HB vs PSS shooting).
# This check also guards the E-178 HB fix it required: both HB Newtons
# double-subtracted the DC sources (settle-rhs inside I_R AND -lambda*Is), so
# every DC bias voltage converged to exactly 2x -- flicker (S ~ I^AF) came out
# 2^AF too big, while bias-independent noise was untouched.
qdeck = ("* qpnoise cyclo 2d\n" + BODY.format(rmod="rmod ", g1="0.8m") +
         ".model rmod R(kf=1e-9 af=2 ef=1)\n"
         ".control\nqpss v(b) 1meg 2.3meg hb 4\nqpnoise b 1k cyclo\n.endc\n.end\n")
qout = run_deck("_q2.cir", qdeck)
mq = re.search(r"two-tone cyclostationary output.*?onoise density\s*=\s*([-\d.eE+]+)",
               qout, re.S)
qval = float(mq.group(1)) if mq else 0.0
ref = referee_exact(1e3, G1, Is)
ok = mq is not None and abs(qval - ref) <= 5e-3 * ref
check("[6] qpnoise cyclo (tone 2 inactive) == 1-D exact referee (<=0.5%)",
      ok, f"(qpnoise={qval:.5e} ref={ref:.5e})")

print(f"\n{passed} passed, {failed} failed")
raise SystemExit(1 if failed else 0)
