#!/usr/bin/env python3
"""Enhancement-168: RF noise figure of an LNA.

Enhancement-165 validated a production model's device NOISE (spectral density);
this one lifts that to a circuit-level figure of merit -- the NOISE FIGURE of a
low-noise amplifier -- and checks it against the textbook RF-noise results:
optimum source matching and the Friis cascade formula.

The LNA is a common-emitter stage built from the HICUM/L2 SiGe HBT (OSDI), AC-
coupled, with a source resistance Rs. From ngspice's `.noise` analysis the noise
figure is

    NF = 10*log10( inoise^2 / (4kT*Rs) )                          [T0 = 290 K]

where `inoise` is ngspice's input-referred noise density: the noise factor F is
the total input-referred noise power over the source-resistor thermal noise.

Checks (under BOTH the Sparse and KLU solvers -- `.noise` works under KLU since
Enhancement-113 fixed the KLU adjoint solve):

  [1] EXTRACTION -- NF(f) is a few dB, > 0 dB everywhere (physical), flat across
      the white mid-band, and rises at high frequency as the input capacitance
      rolls off the gain.
  [2] NOISE MATCH -- NF(Rs) is a U-curve with an interior minimum (an optimum
      source resistance): too small an Rs and the amplifier's voltage noise
      dominates, too large and its current noise does. The input current noise
      extracted from the high-Rs behaviour equals the base SHOT noise
      sqrt(2q*IB) -- the physical origin of the optimum.
  [3] FRIIS / first-stage dominance -- a two-stage cascade with a high-gain first
      stage has F_total essentially equal to F1 (the LNA principle: the first
      stage's gain suppresses the second stage's noise), and F_total matches the
      Friis prediction F1 + (F2-1)/G_av1 to a few percent.
  [4] FRIIS quantitative -- with a low-gain first stage the second stage
      contributes a clearly measurable amount, and F_total still matches Friis --
      validating the formula where its correction term actually matters.

Every SPICE deck starts with a title line (SPICE treats line 1 as the title!).
"""
import math
import os
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
SCRATCH = tempfile.mkdtemp(prefix="noisefigure_")
K = 1.380649e-23
Q = 1.602176634e-19
T0 = 290.0
FOURKT = 4 * K * T0
FMID = 1e8            # 100 MHz, in the white mid-band
IB = 20e-6           # base bias current
passed = failed = 0


def check(name, ok, detail=""):
    global passed, failed
    if ok:
        passed += 1
        print(f"  PASS  {name} {detail}")
    else:
        failed += 1
        print(f"  FAIL  {name} {detail}")


def run(deck):
    open(os.path.join(SCRATCH, "d.cir"), "w").write(deck)
    subprocess.run([NGSPICE, "-b", "d.cir"], capture_output=True, text=True,
                   timeout=120, cwd=SCRATCH)


def dat(fn):
    p = os.path.join(SCRATCH, fn)
    return [[float(x) for x in l.split()] for l in open(p)] if os.path.exists(p) else []


def at(rows, f):
    return min(rows, key=lambda r: abs(r[0] - f))[1] if rows else None


HEAD = """.options temp=16.85
.control
pre_osdi hicuml2.osdi
.endc
"""
MODEL = ".model m hicumL2va t0=1e-11 cjei0=1f cjci0=1f cjep0=1f cjcx0=1f\n"


def nf_single(Rs, RC, band=(8e7, 1.2e8), dec=3):
    """Noise figure [dB] of one common-emitter stage (source Rs, load RC)."""
    run(f"""* single-stage NF
{HEAD}Vsrc s 0 dc 0 ac 1
Rs s in {Rs}
Cin in b 1u
Ib 0 b dc {IB}
Vcc cc 0 dc 3.0
RC cc c {RC}
N1 c b 0 0 0 m
{MODEL}.noise v(c) Vsrc dec {dec} {band[0]} {band[1]}
.control
run
setplot noise1
wrdata n.dat inoise_spectrum
.endc
.end
""")
    ino = at(dat("n.dat"), FMID)
    return 10 * math.log10(ino ** 2 / (FOURKT * Rs)), ino


def gain_avail(Rs, RC):
    """Available power gain of one stage: G_av = |v_c|^2 * Rs / Rout, Rout~=RC."""
    run(f"""* stage available gain
{HEAD}Vsrc s 0 dc 0 ac 1
Rs s in {Rs}
Cin in b 1u
Ib 0 b dc {IB}
Vcc cc 0 dc 3.0
RC cc c {RC}
N1 c b 0 0 0 m
{MODEL}.ac dec 3 8e7 1.2e8
.control
run
wrdata g.dat vm(c)
.endc
.end
""")
    vc = at(dat("g.dat"), FMID)
    return vc ** 2 * Rs / RC


def nf_two(RC1, RC2=1000, Rs=200):
    """Noise figure [dB] of the two-stage cascade (stage-1 load RC1)."""
    run(f"""* two-stage LNA NF
{HEAD}Vsrc s 0 dc 0 ac 1
Rs s in {Rs}
Cin in b1 1u
Ib1 0 b1 dc {IB}
Vcc cc 0 dc 3.0
RC1 cc c1 {RC1}
N1 c1 b1 0 0 0 m
Cc c1 b2 1u
Ib2 0 b2 dc {IB}
RC2 cc c2 {RC2}
N2 c2 b2 0 0 0 m
{MODEL}.noise v(c2) Vsrc dec 5 1e7 1e9
.control
run
setplot noise1
wrdata t.dat inoise_spectrum
.endc
.end
""")
    ino = at(dat("t.dat"), FMID)
    return 10 * math.log10(ino ** 2 / (FOURKT * Rs))


# --- compile HICUM/L2 ---------------------------------------------------------
subprocess.run([OPENVAF, "hicuml2.va", "-o", os.path.join(SCRATCH, "hicuml2.osdi")],
               cwd=os.path.join(ITEST, "HICUML2"), capture_output=True, text=True, timeout=300)
if not os.path.exists(os.path.join(SCRATCH, "hicuml2.osdi")):
    check("HICUM/L2 compiles", False)
    print(f"\n{passed} passed, {failed} failed")
    raise SystemExit(1)

# ---- [1] EXTRACTION: NF(f) spectrum ------------------------------------------
run(f"""* NF spectrum
{HEAD}Vsrc s 0 dc 0 ac 1
Rs s in 200
Cin in b 1u
Ib 0 b dc {IB}
Vcc cc 0 dc 3.0
RC cc c 1k
N1 c b 0 0 0 m
{MODEL}.noise v(c) Vsrc dec 8 1e6 1e10
.control
run
setplot noise1
wrdata spec.dat inoise_spectrum
.endc
.end
""")
sp = dat("spec.dat")
nf = [(r[0], 10 * math.log10(r[1] ** 2 / (FOURKT * 200))) for r in sp]
nf_mid = [v for f, v in nf if 1e7 <= f <= 1e8]
mid = sum(nf_mid) / len(nf_mid)
flat = max(nf_mid) - min(nf_mid)
nf_hi = [v for f, v in nf if f >= 8e9][0]
allpos = all(v > 0 for _, v in nf)
check("[1] NF(f): > 0 dB everywhere, flat (<0.1 dB) across the white mid-band",
      allpos and flat < 0.1, f"(mid-band NF ~{mid:.2f} dB, spread {flat:.3f} dB)")
check("[1b] NF rises at high frequency as input capacitance rolls off gain",
      nf_hi > mid + 0.5, f"(NF(~10GHz)={nf_hi:.2f} vs mid ~{mid:.2f} dB)")

# ---- [2] NOISE MATCH: NF(Rs) U-curve; in = base shot noise -------------------
RSS = [100, 200, 500, 1000, 2000]
nfrs = [(rs, *nf_single(rs, 1000)) for rs in RSS]     # (Rs, NF_dB, inoise)
# U-curve: interior minimum (NF at 200 below both ends)
nfvals = {rs: nfdb for rs, nfdb, _ in nfrs}
u_shape = nfvals[200] < nfvals[100] and nfvals[200] < nfvals[2000]
# fit inoise^2 - 4kT*Rs = en^2 + in^2*Rs^2  (linear in Rs^2)
X = [rs ** 2 for rs, _, _ in nfrs]
Y = [ino ** 2 - FOURKT * rs for rs, _, ino in nfrs]
n = len(X); sx = sum(X); sy = sum(Y); sxx = sum(x * x for x in X); sxy = sum(x * y for x, y in zip(X, Y))
in2 = (n * sxy - sx * sy) / (n * sxx - sx * sx)
i_n = math.sqrt(in2)
shot = math.sqrt(2 * Q * IB)
check("[2] NF(Rs) is a U-curve with an interior optimum source resistance",
      u_shape, f"(NF: Rs=100 {nfvals[100]:.2f}, Rs=200 {nfvals[200]:.2f}, Rs=2k {nfvals[2000]:.2f} dB)")
check("[2b] input current noise (from high-Rs slope) = base shot noise sqrt(2q*IB)",
      abs(i_n - shot) / shot < 0.06,
      f"(extracted in={i_n:.3e}, shot sqrt(2q*IB)={shot:.3e} A/rtHz, {abs(i_n-shot)/shot*100:.1f}%)")

# ---- [3] FRIIS / first-stage dominance (high first-stage gain) ---------------
f1_hi, _ = nf_single(200, 1000)
f2_hi, _ = nf_single(1000, 1000)          # stage-2 source impedance ~= RC1 = 1k
g1_hi = gain_avail(200, 1000)
ftot_hi = nf_two(1000)
F1, F2 = 10 ** (f1_hi / 10), 10 ** (f2_hi / 10)
pred_hi = 10 * math.log10(F1 + (F2 - 1) / g1_hi)
check("[3] Friis + first-stage dominance (high G1): F_total ~ F1, matches F1+(F2-1)/G_av1",
      abs(ftot_hi - pred_hi) < 0.03 and abs(ftot_hi - f1_hi) < 0.05,
      f"(F_total={ftot_hi:.3f} dB, Friis pred={pred_hi:.3f}, F1={f1_hi:.3f}, G_av1={g1_hi:.0f})")

# ---- [4] FRIIS quantitative (low first-stage gain) ---------------------------
f1_lo, _ = nf_single(200, 100)
f2_lo, _ = nf_single(100, 1000)           # stage-2 source impedance ~= RC1 = 100
g1_lo = gain_avail(200, 100)
ftot_lo = nf_two(100)
F1l, F2l = 10 ** (f1_lo / 10), 10 ** (f2_lo / 10)
pred_lo = 10 * math.log10(F1l + (F2l - 1) / g1_lo)
check("[4] Friis quantitative (low G1): 2nd stage contributes measurably, F_total matches Friis",
      abs(ftot_lo - pred_lo) < 0.03 and (ftot_lo - f1_lo) > 0.03,
      f"(F_total={ftot_lo:.3f} dB, Friis pred={pred_lo:.3f}, F1={f1_lo:.3f}, "
      f"2nd-stage adds {ftot_lo-f1_lo:.3f} dB, G_av1={g1_lo:.0f})")

print(f"\n{passed} passed, {failed} failed")
raise SystemExit(1 if failed else 0)
