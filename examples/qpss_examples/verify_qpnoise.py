#!/usr/bin/env python3
"""
verify_qpnoise.py -- Enhancement-138: two-tone small-signal QPnoise.

`qpnoise <output_node> <f_in>` folds every device's noise through the ADJOINT of the
2-D conversion matrix around the QPSS operating point retained by a prior
`qpss <expr> <f1> <f2> hb`, summing the contribution of every sideband
f_in + k1*f1 + k2*f2 into the output noise at f_in -- the two-tone analogue of pnoise.

The anchor: with the pump driven to ~0 the conversion matrix is block-diagonal, so only
sideband (0,0) contributes and QPnoise reduces EXACTLY to ordinary `.noise`.

Checks (numpy-free, parsed from stdout):

  [1] reduce-to-noise    -- pump->0: QPnoise onoise == plain .noise onoise (exact)
  [2] thermal law        -- pump->0: onoise density = 4kTR of the 1k resistor
  [3] conversion active  -- with pump, the folded onoise differs from the no-pump value
  [4] inoise consistency -- inoise = onoise / gain^2
  [5] no op-point        -- qpnoise with no prior `qpss ... hb` errors cleanly
  [6] KLU vs Sparse      -- solver-independent (bit-identical)

Enhancement-139 adds cyclostationary device noise (`qpnoise ... cyclo`):

  [7] cyclo reduce-to-noise -- pump->0: cyclo == plain .noise (Parseval)
  [8] Parseval              -- bias-independent PSD -> cyclo == stationary under pump
  [9] cyclo diode           -- hard-pumped diode: cyclo differs markedly from stationary
  [10] cyclo KLU vs Sparse  -- solver-independent
"""
import math
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from _setup import NG as NGSPICE

checks = passed = 0
def check(label, ok, detail=""):
    global checks, passed
    checks += 1; passed += bool(ok)
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  [{detail}]" if detail and not ok else ""))


def run(deck, name="_qpn"):
    p = os.path.join(HERE, name + ".cir")
    with open(p, "w") as f:
        f.write(deck)
    try:
        r = subprocess.run([NGSPICE, "-b", p], capture_output=True, text=True, timeout=180)
    finally:
        if os.path.exists(p):
            os.remove(p)
    return r.stdout + r.stderr


def qpn(out):
    """parse the first QPnoise block -> dict(onoise, onoise_sqrt, inoise, gain2)."""
    d = {}
    m = re.search(r"onoise density\s*=\s*([-\d.eE+]+)\s*V\^2/Hz\s*\(([-\d.eE+]+)", out)
    if m:
        d["onoise"] = float(m.group(1)); d["onoise_sqrt"] = float(m.group(2))
    m = re.search(r"inoise density\s*=\s*([-\d.eE+]+)\s*\(gain\^2 =\s*([-\d.eE+]+)", out)
    if m:
        d["inoise"] = float(m.group(1)); d["gain2"] = float(m.group(2))
    return d

def qpn_mode(out, mode):
    """onoise density (V^2/Hz) from the `stationary` or `cyclostationary` block."""
    m = re.search(rf"two-tone {mode} output.*?onoise density\s*=\s*([-\d.eE+]+)", out, re.S)
    return float(m.group(1)) if m else None


def deck(Apump, f_in="0.3G", opt="", K="3 3"):
    return (f"* qpnoise\n"
            f"I1 0 n SIN(0 {Apump} 1.0G)\nI2 0 n SIN(0 {Apump} 1.1G)\n"
            f"R1 n 0 1k\nBnl n 0 I = 0.5e-3*V(n)*V(n)*V(n)\nIac 0 n AC 1\n{opt}"
            f".control\nqpss v(n) 1.0G 1.1G hb {K}\nqpnoise n {f_in}\n.endc\n.end\n")


print("Enhancement-138: two-tone small-signal QPnoise (quasi-periodic noise)")

# [1] reduce-to-noise: pump ~ 0 -> QPnoise onoise == plain .noise onoise at f_in.
qp0 = qpn(run(deck("1e-9")))
nref = run("* noise ref\nIac 0 n AC 1\nR1 n 0 1k\n.control\n"
           "noise v(n) Iac lin 1 0.3G 0.3G 1\nsetplot noise1\nprint onoise_spectrum\n.endc\n.end\n")
m = re.search(r"onoise_spectrum\s*=\s*([-\d.eE+]+)", nref)
noise_ref = float(m.group(1)) if m else None
qp_sqrt = qp0.get("onoise_sqrt")
check("reduce-to-noise: QPnoise onoise == plain .noise onoise (pump->0)",
      noise_ref and qp_sqrt and abs(qp_sqrt - noise_ref) < 1e-4 * noise_ref,
      f"qpnoise={qp_sqrt} noise={noise_ref}")

# [2] thermal law: onoise density = 4kTR of R1 (k=1.380649e-23, T=300.15 K default).
thermal = 4 * 1.380649e-23 * 300.15 * 1000.0
check("thermal law: onoise density = 4kTR (1k resistor)",
      qp0.get("onoise") and abs(qp0["onoise"] - thermal) < 1e-3 * thermal,
      f"onoise={qp0.get('onoise')} 4kTR={thermal:.4e}")

# [3] conversion active: with a real pump the folded onoise differs from the no-pump value
# (the conversion matrix is no longer block-diagonal, so sidebands contribute + load).
qpP = qpn(run(deck("0.6m")))
check("conversion active: folded onoise differs under pump",
      qpP.get("onoise") and abs(qpP["onoise"] - qp0["onoise"]) > 1e-2 * qp0["onoise"],
      f"pump={qpP.get('onoise')} nopump={qp0.get('onoise')}")

# [4] input-referred consistency: inoise = onoise / gain^2.
check("inoise = onoise / gain^2",
      qpP.get("inoise") and qpP.get("gain2")
      and abs(qpP["inoise"] - qpP["onoise"] / qpP["gain2"]) < 1e-6 * qpP["inoise"])

# [5] qpnoise without a prior qpss ... hb must error cleanly.
out = run("* no op\nR1 n 0 1k\nIac 0 n AC 1\n.control\nqpnoise n 0.3G\n.endc\n.end\n")
check("qpnoise with no QPSS operating point errors cleanly",
      "no QPSS operating point" in out and "QPnoise:" not in out)

# [6] SOLVER PARITY: KLU and Sparse give identical onoise.
ok = qpn(run(deck("0.5m", opt=".options klu\n"))).get("onoise")
os_ = qpn(run(deck("0.5m", opt=".options sparse\n"))).get("onoise")
check("QPnoise solver-independent: KLU vs Sparse identical",
      ok and os_ and abs(ok - os_) < 1e-9 * os_, f"klu={ok} sparse={os_}")

# ----- Enhancement-139: cyclostationary QPnoise (`qpnoise ... cyclo`) -----
# The device PSD S(t) swings over the two-tone period; instead of the frequency-domain
# fold (a single-bias PSD) the cyclo path IDFTs the adjoint transfers to the time domain
# and averages S(t_s)*|A_s|^2 over the P1xP2 phase grid. By Parseval it reduces to the
# stationary sum (and hence .noise) when S(t) is constant.

# [7] cyclo reduce-to-noise: pump->0, S constant -> cyclo == stationary == plain .noise.
both0 = run(deck("1e-9").replace("qpnoise n 0.3G\n", "qpnoise n 0.3G\nqpnoise n 0.3G cyclo\n"))
cyc0 = qpn_mode(both0, "cyclostationary")
check("cyclo reduce-to-noise: pump->0 cyclo == plain .noise",
      cyc0 and noise_ref and abs(math.sqrt(cyc0) - noise_ref) < 1e-4 * noise_ref,
      f"cyclo={math.sqrt(cyc0) if cyc0 else None} noise={noise_ref}")

# [8] Parseval with a bias-INDEPENDENT PSD: a thermal resistor's noise is constant even
# under a full pump, so cyclo must still equal stationary exactly.
bothR = run(deck("0.5m").replace("qpnoise n 0.3G\n", "qpnoise n 0.3G\nqpnoise n 0.3G cyclo\n"))
stR, cyR = qpn_mode(bothR, "stationary"), qpn_mode(bothR, "cyclostationary")
check("Parseval: thermal (bias-indep) PSD -> cyclo == stationary under pump",
      stR and cyR and abs(cyR - stR) < 1e-6 * stR, f"stat={stR} cyclo={cyR}")

# [9] a hard-pumped DIODE: bias-dependent shot noise (2qI_D swings as the junction
# switches). The circuit is purely RESISTIVE, so the network is memoryless and the
# exact cyclostationary answer has a CLOSED FORM: the torus average of the
# instantaneous identity, onoise = <2qI_D(th1,th2)*dA^2 + 4kT/Rn*psi_n^2 +
# 4kT/Rs*psi_a^2> with per-sample adjoints from the 2-node conductance matrix.
# (E-178 hardening: the previous ">2x stationary" expectation was an artifact --
# the diode's uninitialized sidewall summary slots fed stack garbage into the
# cyclo path, and the pre-E-178 HB DC double-subtraction doubled the bias. The
# true cyclo value is DOMINATED by Rn's own thermal noise: when the junction
# conducts hard its S rises but its transfer to the output collapses, so the
# shot term is small and cyclo lands close to, not far from, stationary.)
diode = ("Vb b 0 0.45\nRs b a 200\nI1 0 a SIN(0 2m 1.0G)\nI2 0 a SIN(0 2m 1.1G)\n"
         "D1 a n DMOD\nRn n 0 1k\nIac 0 n AC 1\n.model DMOD D(IS=1e-14 N=1.0)\n"
         ".control\nqpss v(n) 1.0G 1.1G hb 3 3\nqpnoise n 0.3G\nqpnoise n 0.3G cyclo\n.endc\n.end\n")
bothD = run("* diode cyclo\n" + diode)
stD, cyD = qpn_mode(bothD, "stationary"), qpn_mode(bothD, "cyclostationary")


def _diode_cyclo_referee(P1=48, P2=48):
    IS, VT = 1e-14, 0.025864                     # 300.15 K
    RS, RN, VB, IA = 200.0, 1000.0, 0.45, 2e-3
    q, kT4 = 1.602176634e-19, 4 * 1.380649e-23 * 300.15
    tot = 0.0
    for s1 in range(P1):
        for s2 in range(P2):
            isrc = IA * (math.sin(2*math.pi*s1/P1) + math.sin(2*math.pi*s2/P2))
            va, vn = 0.4, 0.01
            for _ in range(300):                 # damped Newton, 2-node algebra
                v = va - vn
                e = math.exp(min(v/VT, 60.0))
                idio, g = IS*(e-1.0), IS*e/VT
                f1 = (VB-va)/RS + isrc - idio
                f2 = idio - vn/RN
                a11, a12, a21, a22 = -1/RS-g, g, g, -g-1/RN
                det = a11*a22 - a12*a21
                dva = (-f1*a22 + f2*a12)/det
                dvn = (-a11*f2 + a21*f1)/det
                dv = dva - dvn
                if abs(dv) > 2*VT:
                    sc = 2*VT/abs(dv); dva *= sc; dvn *= sc
                va += dva; vn += dvn
                if abs(dva) < 1e-15 and abs(dvn) < 1e-15:
                    break
            v = va - vn
            e = math.exp(min(v/VT, 60.0))
            idio, g = IS*(e-1.0), IS*e/VT
            a11, a12, a22 = 1/RS+g, -g, g+1/RN   # symmetric G
            det = a11*a22 - a12*a12
            psi_a, psi_n = -a12/det, a11/det     # adjoint for output n
            dA = psi_a - psi_n
            tot += (2*q*max(idio, 0.0)*dA*dA + kT4/RN*psi_n*psi_n
                    + kT4/RS*psi_a*psi_a)
    return tot / (P1*P2)


refD = _diode_cyclo_referee()
check("cyclostationary diode noise == closed-form torus-average referee (<=10%)",
      stD and cyD and abs(cyD - refD) <= 0.10 * refD,
      f"stat={stD} cyclo={cyD} referee={refD:.4e}")

# [10] cyclo is solver-independent too.
ck = qpn_mode(run("* p\n" + diode.replace(".control", ".options klu\n.control")), "cyclostationary")
cs = qpn_mode(run("* p\n" + diode.replace(".control", ".options sparse\n.control")), "cyclostationary")
check("cyclo QPnoise solver-independent: KLU vs Sparse identical",
      ck and cs and abs(ck - cs) < 1e-9 * cs, f"klu={ck} sparse={cs}")

print(f"\n{'ALL PASS' if passed == checks else 'FAILURES'}: {passed}/{checks} passed")
sys.exit(0 if passed == checks else 1)
