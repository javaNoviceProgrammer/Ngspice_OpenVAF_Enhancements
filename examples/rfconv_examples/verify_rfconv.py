#!/usr/bin/env python3
"""Enhancement-175: LPTV conversion-matrix frequency fix (RF-suite audit).

THE BUG. Every periodic small-signal analysis (pac/psp/pnoise/pxf and the
two-tone qpac/qpnoise/qpxf, plus the phasenoise adjoint) built its conversion
matrix with the reactive term scaled by the COLUMN (input-sideband) frequency:

    H_{nm} = G_{n-m} + j*omega_m * C_{n-m}          (wrong for small-signal)

For a small signal riding a periodic orbit the capacitance waveform C(t) is
FROZEN, so di = d/dt[C(t) dv] = Cdot*dv + C*dv_dot -- and the product rule
gives the ROW (output-sideband) frequency:

    H_{nm} = G_{n-m} + j*omega_n * C_{n-m}          (correct)

Using omega_m silently drops the parametric-pumping term Cdot*dv -- the very
term that makes a pumped varactor convert. Every conversion sideband through a
time-varying capacitance came out scaled by exactly omega_m/omega_n: on the
audit circuit the (f_in +- k*f0) sidebands were 3x / 5x / 7x / 9x too small.
LTI circuits (constant C -- which is what the whole prior regression used)
have C_{n-m} = 0 off the diagonal where omega_n = omega_m, so every existing
check passed: the E-171 "accidental correctness in the untested region"
pattern again.

THE SUBTLETY. The harmonic-balance residual uses the SAME builder but must
KEEP the column frequency: its reactive current is the exact chain rule
d/dt Q(v(t)) = C(v(t))*vdot(t), whose n-th harmonic is sum_m C_{n-m}*(j*w_m*V_m).
That is why HB and QPSS-HB always matched transient ground truth while the
small-signal analyses did not. The fix is a mode flag on the two builders
(pac_build_matrix / qp_build_matrix) + the two inline copies (pac adjoint,
phasenoise adjoint): smallsig=1 -> row frequency, smallsig=0 (HB/QPSS-HB
residual+Jacobian) -> chain-rule column frequency, unchanged.

GROUND TRUTH here is a plain transient + one-beat Fourier projection -- the
time-domain integrator is independent of all conversion-matrix machinery.
Circuit: R (1k) driving an OSDI varactor (C(v) = c0*(1+alpha*v), c0=1n,
alpha=0.5) pumped hard by 1 V @ 1 MHz, probed by a 1 mV small tone at 250 kHz.

Checks:
  [1] transient truth vs QPSS-HB (chain-rule path UNCHANGED by the fix)
  [2] transient truth vs qpac (the FIXED small-signal path; pre-fix this was
      1/3, 1/5, 1/7, 1/9 of the true value at lsb1/usb1/lsb2/usb2)
  [3] the pre-fix omega-ratio signature is GONE (usb1 not ~5x small)
  [4] HB analytic anchor: cubic-resistive branch current exact to 6 digits
      (fund a1*A + (3/4)*a3*A^3, third harmonic (1/4)*a3*A^3)
  [5] QPSS-HB analytic anchor: two-tone IM3 (2f1-f2) = (3/4)*a3*A^3 exact

The dual-solver harness runs this under Sparse AND KLU.

Every SPICE deck starts with a title line (SPICE treats line 1 as the title!).
"""
import math
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from _setup import VAF as OPENVAF, NG as NGSPICE
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
    with open(path, "w") as f:
        f.write(deck)
    r = subprocess.run([NGSPICE, "-b", path], capture_output=True, text=True,
                       timeout=300, cwd=HERE)
    return r.stdout + r.stderr


# compile the varactor
subprocess.run([OPENVAF, os.path.join(HERE, "varcap.va"),
                "-o", os.path.join(HERE, "varcap.osdi")], check=True, cwd=HERE)

VC_BODY = """.control
pre_osdi varcap.osdi
.endc
V1 x 0 SIN(0 1 1meg) AC 1
V2 a x SIN(0 {a2} 250k)
R1 a b 1k
N1 b 0 vc
.model vc varcap c0=1n alpha=0.5
"""

# ---------- ground truth: transient + one-beat Fourier projection ----------
deck = "* transient truth\n" + VC_BODY.format(a2="1m") + \
       ".tran 0.5n 60u 56u 0.5n\n.option reltol=1e-5\n.control\nrun\nwrdata rfconv_tr.csv v(b)\n.endc\n.end\n"
run_deck("_tr.cir", deck)
d = [tuple(map(float, l.split())) for l in open(os.path.join(HERE, "rfconv_tr.csv"))
     if l.strip()]
t = [x[0] for x in d]
v = [x[1] for x in d]
Tb = 4e-6                      # exact beat period of (1meg, 250k)
tend = t[-1]
NS = 8192
tu = [tend - Tb + Tb * i / NS for i in range(NS)]


def interp(tq):
    import bisect
    i = bisect.bisect_left(t, tq)
    if i <= 0:
        return v[0]
    if i >= len(t):
        return v[-1]
    f = (tq - t[i-1]) / (t[i] - t[i-1])
    return v[i-1] + f * (v[i] - v[i-1])


vu = [interp(x) for x in tu]


def comp(f):
    re_ = sum(vu[i] * math.cos(2*math.pi*f*tu[i]) for i in range(NS)) * 2.0 / NS
    im_ = -sum(vu[i] * math.sin(2*math.pi*f*tu[i]) for i in range(NS)) * 2.0 / NS
    return math.hypot(re_, im_)


truth = {          # |V| per 1 V of stimulus (tone is 1 mV)
    "sb0":  comp(250e3) * 1e3,
    "lsb1": comp(750e3) * 1e3,
    "usb1": comp(1.25e6) * 1e3,
    "lsb2": comp(1.75e6) * 1e3,
    "usb2": comp(2.25e6) * 1e3,
}

# ---------- [1] QPSS-HB (chain rule; must be unchanged and match truth) -----
deck = "* qpss-hb vs truth\n" + VC_BODY.format(a2="1m") + \
       ".control\nqpss v(b) 1meg 250k hb 6 1\n.endc\n.end\n"
out = run_deck("_qphb.cir", deck)
qp = {}
for m in re.finditer(r"^  b\s+\(\s*(-?\d+),\s*(-?\d+)\)\s+\S+\s+(\S+)", out, re.M):
    qp[(int(m.group(1)), int(m.group(2)))] = float(m.group(3))
m1 = {"sb0": (0, 1), "lsb1": (1, -1), "usb1": (1, 1)}
ok = all(abs(qp[k2] * 1e3 - truth[k]) <= 0.02 * truth[k] for k, k2 in m1.items())
check("[1] QPSS-HB (chain-rule path) matches transient truth (sb0/lsb1/usb1 within 2%)",
      ok, f"(qpss-hb usb1={qp[(1,1)]*1e3:.5g} truth={truth['usb1']:.5g})")

# ---------- [2] qpac (the FIXED small-signal conversion matrix) -------------
deck = "* qpac small-signal\n" + VC_BODY.format(a2="0") + \
       ".control\nqpss v(b) 1meg 3.1meg hb 6 1\nqpac 250k\n.endc\n.end\n"
out = run_deck("_qpac.cir", deck)
# qpac rows: "  b   ( k, 0)   <freq>   |value|  phase" in the qpac section
# (negative frequency rows carry the lower sidebands)
qa = {}
sec = out[out.find("QPAC"):] if "QPAC" in out else out
for m in re.finditer(r"^  b\s+\(\s*(-?\d+),\s*0\)\s+(-?\S+)\s+(\S+)", sec, re.M):
    qa[int(m.group(1))] = float(m.group(3))
m2 = {"sb0": 0, "lsb1": -1, "usb1": 1, "lsb2": -2, "usb2": 2}
ok = all(k2 in qa and abs(qa[k2] - truth[k]) <= 0.02 * truth[k] for k, k2 in m2.items())
check("[2] qpac (fixed small-signal path) matches transient truth (all 5 sidebands within 2%)",
      ok, f"(qpac usb1={qa.get(1, 0):.5g} truth={truth['usb1']:.5g})")

# ---------- [3] the pre-fix signature is gone --------------------------------
# pre-fix, usb1 came out scaled by omega_in/omega_usb1 = 250k/1.25M = 1/5
prefix_usb1 = truth["usb1"] / 5.0
check("[3] pre-fix omega-ratio signature absent (usb1 is NOT ~1/5 of truth)",
      1 in qa and abs(qa[1] - prefix_usb1) > 0.5 * prefix_usb1,
      f"(qpac usb1={qa.get(1, 0):.5g}, broken value would be {prefix_usb1:.5g})")

# ---------- [4] HB analytic anchor (residual chain rule untouched) -----------
deck = ("* hb cubic anchor\nV1 n 0 SIN(0 0.5 100meg)\n"
        "B1 n 0 I=1m*v(n)+2m*v(n)*v(n)*v(n)\n"
        ".control\nhb 100meg 8\n.endc\n.end\n")
out = run_deck("_hb.cir", deck)
hb = {}
for m in re.finditer(r"^  v1#branch\s+(\d+)\s+\S+\s+(\S+)", out, re.M):
    hb[int(m.group(1))] = float(m.group(2))
ok = (abs(hb.get(1, 0) - 6.875e-4) < 1e-9 and abs(hb.get(3, 0) - 6.25e-5) < 1e-9
      and hb.get(2, 1) < 1e-12)
check("[4] HB analytic: fund a1*A+(3/4)a3*A^3 = 687.5uA, H3 = 62.5uA exact",
      ok, f"(H1={hb.get(1, 0):.6e} H3={hb.get(3, 0):.6e})")

# ---------- [5] QPSS-HB analytic IM3 anchor ----------------------------------
deck = ("* qpss im3 anchor\nV1 a 0 SIN(0 0.5 1.0g)\nV2 n a SIN(0 0.5 1.3g)\n"
        "B1 n 0 I=1m*v(n)+2m*v(n)*v(n)*v(n)\n"
        ".control\nqpss v1#branch 1.0G 1.3G hb 3 3\n.endc\n.end\n")
out = run_deck("_im3.cir", deck)
im = {}
for m in re.finditer(r"^  v1#branch\s+\(\s*(-?\d+),\s*(-?\d+)\)\s+\S+\s+(\S+)", out, re.M):
    im[(int(m.group(1)), int(m.group(2)))] = float(m.group(3))
ok = (abs(im.get((1, 0), 0) - 1.0625e-3) < 1e-8            # a1*A + (9/4)*a3*A^3
      and abs(im.get((2, -1), 0) - 1.875e-4) < 1e-8)       # (3/4)*a3*A^3
check("[5] QPSS-HB analytic: fundamental 1.0625mA, IM3 (2f1-f2) 187.5uA exact",
      ok, f"(fund={im.get((1,0),0):.6e} im3={im.get((2,-1),0):.6e})")

print(f"\n{passed} passed, {failed} failed")
raise SystemExit(1 if failed else 0)
