#!/usr/bin/env python3
"""
Enhancement-164: large-signal RF characterization of a real transistor.

Enhancements 159-161 validated a production compact model's DC, coverage and
small-signal (AC/C-V/fT) behavior. This one drives a real device HARD and extracts
the large-signal RF figures of merit -- gain compression (P1dB), harmonic
distortion, and third-order intermodulation (IP3) -- for a common-emitter
amplifier built from the bundled **HICUM/L2 SiGe HBT** (compiled in place from the
OpenVAF integration-test sources), with the dynamic parameters that give it a
finite fT (E-161: t0 = 10 ps, 1 fF junction caps).

Method note (a real finding): the frequency-domain harmonic-balance engines
(`hb`/`qpss`, E-134/136) do NOT converge on this stiff, many-internal-node
production model in an amplifier configuration -- `hb` returns error 103 at any
drive level, and the two-tone `qpss` is prohibitively slow. So the large-signal
characterization here uses **transient + Fourier/FFT**, which integrates reliably
on the heavy model. (See the README; this is why the RF suite's HB dot-cards, new
in E-162/163, are not used on this circuit.)

The amplifier: Vcc = 3 V, RC = 400 ohm collector load, base biased at 0.77 V
through a 50 ohm RF source resistance. Small-signal gain ~ 7.7 (17.8 dB).

Checks (each under BOTH the Sparse and KLU solvers -- transient works under both):
  [1] the transient small-signal gain matches the `.ac` gain (transient is the
      correct large-signal engine here).
  [2] the third harmonic grows with the textbook 3:1 slope (HD3 ~ A^3), the
      signature of a third-order nonlinearity.
  [3] IIP3 extracted from the single tone -- IIP3 = A / sqrt(3*HD3) -- is constant
      across drive level (validating the third-order model). This is the standard
      single-tone IP3 method (two-tone IM3 = 3 * single-tone HD3).
  [4] the amplifier compresses at high drive (gain falls below the small-signal
      value -- a P1dB exists).

Every SPICE deck starts with a title line (SPICE treats line 1 as the title!).
"""
import math
import os
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.dirname(HERE))
from _setup import VAF as OPENVAF, NG as NGSPICE
from _setup import check_both_solvers
check_both_solvers(__file__)

ITEST = os.path.join(ROOT, "OpenVAF-master-20260610", "integration_tests")
SCRATCH = tempfile.mkdtemp(prefix="rfpa_")
passed = failed = 0


def check(name, ok, detail=""):
    global passed, failed
    if ok:
        passed += 1
        print(f"  PASS  {name} {detail}")
    else:
        failed += 1
        print(f"  FAIL  {name} {detail}")


MODEL = (".model m hicumL2va t0=1e-11 cjei0=1f cjci0=1f cjep0=1f cjcx0=1f")
AMP = ("* HICUM common-emitter amp\n"
       ".control\npre_osdi hicuml2.osdi\n.endc\n"
       "Vcc cc 0 dc 3.0\nRC cc c 400\n"
       "Vsrc s 0 dc 0.77 ac 1 SIN(0.77 {amp} 1G)\nRb s b 50\n"
       "N1 c b 0 0 0 m\n" + MODEL + "\n")


def run(deck):
    open(os.path.join(SCRATCH, "d.cir"), "w").write(deck)
    r = subprocess.run([NGSPICE, "-b", "d.cir"], capture_output=True, text=True,
                       timeout=180, cwd=SCRATCH)
    return r.stdout + r.stderr


def fourier(amp):
    """single-tone transient+fourier -> (fund |V|, [norm mags h0..hN])."""
    out = run(AMP.format(amp=amp) +
              ".control\ntran 2p 80n 40n\nfourier 1G v(c)\n.endc\n.end\n")
    fund, norm = None, {}
    for m in re.finditer(r"^\s*(\d+)\s+[-\d.eE+]+\s+([-\d.eE+]+)\s+[-\d.eE+]+\s+([-\d.eE+]+)",
                         out, re.M):
        h = int(m.group(1))
        if h == 1:
            fund = float(m.group(2))
        norm[h] = float(m.group(3))
    return fund, norm


if not os.path.exists(os.path.join(SCRATCH, "hicuml2.osdi")):
    subprocess.run([OPENVAF, "hicuml2.va", "-o", os.path.join(SCRATCH, "hicuml2.osdi")],
                   cwd=os.path.join(ITEST, "HICUML2"), capture_output=True, text=True)

# ---- [1] transient small-signal gain vs .ac ----
f_ss, norm_ss = fourier(0.002)
g_tran = f_ss / 0.002
out_ac = run(AMP.format(amp=0.002) + ".control\nac lin 1 1G 1G\nprint vm(c)\n.endc\n.end\n")
m = re.search(r"vm\(c\)\s*=\s*([-\d.eE+]+)", out_ac)
g_ac = float(m.group(1)) if m else float("nan")
check("[1] transient small-signal gain matches .ac gain",
      abs(g_tran - g_ac) / g_ac < 0.02, f"(tran {g_tran:.3f}, ac {g_ac:.3f})")

# ---- [2]/[3] HD3 3:1 slope + IIP3 constant ----
levels = [0.005, 0.01, 0.02]
data = {a: fourier(a) for a in levels}
# absolute HD3 = norm_HD3 * fund ; 3:1 slope -> HD3_abs quadruples per 2x... actually 8x
hd3_abs = {a: data[a][1][3] * data[a][0] for a in levels}
slope = hd3_abs[0.02] / hd3_abs[0.005]     # (0.02/0.005)^3 = 64
check("[2] third harmonic follows the 3:1 slope (HD3 ~ A^3)",
      abs(slope - 64) / 64 < 0.15, f"(HD3(0.02)/HD3(0.005) = {slope:.1f}, expect 64)")

# IIP3 (input amplitude) = A / sqrt(3 * HD3_rel), HD3_rel = norm mag of h3
iip3 = {a: a / math.sqrt(3 * data[a][1][3]) for a in levels}
spread = (max(iip3.values()) - min(iip3.values())) / (sum(iip3.values()) / len(iip3))
check("[3] single-tone IIP3 = A/sqrt(3*HD3) is constant across drive (3rd-order)",
      spread < 0.05,
      f"(IIP3 = {', '.join(f'{iip3[a]:.4f}' for a in levels)} V, spread {spread*100:.1f}%)")

# ---- [4] gain compression at high drive ----
f_hi, _ = fourier(0.3)
g_hi = f_hi / 0.3
check("[4] amplifier compresses at high drive (P1dB exists)",
      g_hi < g_tran, f"(gain {g_tran:.2f} -> {g_hi:.2f} at 150x drive)")

print(f"\n{passed} passed, {failed} failed")
raise SystemExit(1 if failed else 0)
