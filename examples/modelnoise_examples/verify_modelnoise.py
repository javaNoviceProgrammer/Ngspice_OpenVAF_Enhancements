#!/usr/bin/env python3
"""
Enhancement-165: production compact-model NOISE validation.

Enhancements 159-161 validated a real compact model's DC, coverage and
small-signal (AC / C-V / fT) behavior; E-164 its large-signal RF. This one
exercises the remaining untested small-signal path -- OSDI's `.noise` stamping of
the models' own `white_noise` / `flicker_noise` sources -- on production models,
compiled in place from the OpenVAF integration-test sources.

Two device classes:

  * BSIM4 (MOSFET) is validated against ngspice's BUILT-IN BSIM4: the output-noise
    spectral density Sv(f) of a common-source amplifier is compared over the full
    band, covering both the low-frequency 1/f FLICKER region (Sv ~ 1/f) and the
    high-frequency flat THERMAL floor. The OSDI and native models agree to a few
    percent everywhere.

  * HICUM/L2 (SiGe HBT) has no ngspice built-in, so its noise is checked against
    physics. Its default noise is WHITE (shot + resistance thermal, no flicker by
    default) -- a flat spectrum, in contrast to the MOSFET's 1/f rise. With a small
    source resistance so the intrinsic device noise dominates, the output floor
    tracks the collector SHOT noise 2q*Ic*RC^2 and scales as sqrt(Ic).

Checks (each under BOTH the Sparse and KLU solvers -- `.noise` works under both
since Enhancement-113 fixed the KLU adjoint solve):
  [1] the OSDI BSIM4 output-noise spectrum matches built-in BSIM4 to <4% across the
      whole band.
  [2] BSIM4 shows the 1/f flicker region at low frequency (Sv(1Hz)/Sv(100Hz) ~ 100
      in power, i.e. the amplitude ratio ~ 10).
  [3] BSIM4 shows the flat thermal floor at high frequency.
  [4] HICUM noise is white (flat) at mid-band -- no flicker by default.
  [5] HICUM output-noise floor tracks the collector shot noise 2q*Ic*RC^2 and
      scales with sqrt(Ic).

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
SCRATCH = tempfile.mkdtemp(prefix="modelnoise_")
Q = 1.602176634e-19
passed = failed = 0


def check(name, ok, detail=""):
    global passed, failed
    if ok:
        passed += 1
        print(f"  PASS  {name} {detail}")
    else:
        failed += 1
        print(f"  FAIL  {name} {detail}")


def compile_model(m, va, out):
    subprocess.run([OPENVAF, va, "-o", os.path.join(SCRATCH, out)],
                   cwd=os.path.join(ITEST, m), capture_output=True, text=True, timeout=300)
    return os.path.exists(os.path.join(SCRATCH, out))


def run(name, deck):
    open(os.path.join(SCRATCH, name), "w").write(deck)
    r = subprocess.run([NGSPICE, "-b", name], capture_output=True, text=True,
                       timeout=120, cwd=SCRATCH)
    return r.stdout + r.stderr


def read2(fn):
    p = os.path.join(SCRATCH, fn)
    return [[float(x) for x in l.split()] for l in open(p)] if os.path.exists(p) else []


ok = compile_model("BSIM4", "bsim4.va", "bsim4.osdi") and \
     compile_model("HICUML2", "hicuml2.va", "hicuml2.osdi")
if not ok:
    check("models compile", False)
    raise SystemExit(1)

# ---- [1]-[3] BSIM4 output-noise spectrum: OSDI vs built-in -------------------
run("b4n.cir", """* bsim4 noise osdi vs builtin
.control
pre_osdi bsim4.osdi
.endc
Vdd ddb 0 dc 1.8
RDb ddb db 10k
Vgb gb 0 dc 0.8 ac 1
M1 db gb 0 0 nb W=10u L=1u
.model nb nmos level=54 version=4.8.2 rdsmod=1 rsh=1
Vddo ddo 0 dc 1.8
RDo ddo do 10k
Vgo go 0 dc 0.8 ac 1
N1 do go 0 0 no
.model no bsim4va w=10u l=1u rdsmod=1 rsh=1
.control
noise v(db) Vgb dec 10 1 1e9
setplot noise1
wrdata b4b.dat onoise_spectrum
noise v(do) Vgo dec 10 1 1e9
setplot noise3
wrdata b4o.dat onoise_spectrum
.endc
.end
""")
b = read2("b4b.dat")
o = read2("b4o.dat")
mx = max(abs(oo[1] - bb[1]) / bb[1] for bb, oo in zip(b, o) if bb[1] > 0)
check("[1] OSDI BSIM4 output-noise spectrum matches built-in BSIM4 to <4%",
      mx < 0.04, f"(max reldiff {mx*100:.2f}%)")

def sv(rows, ftarget):
    """noise amplitude density at the sampled frequency nearest ftarget."""
    return min(rows, key=lambda r: abs(math.log10(r[0]) - math.log10(ftarget)))[1]

# 1/f flicker: in the deep-flicker decade (1->10 Hz, thermal negligible) the
# amplitude density Sv ~ 1/sqrt(f), so Sv(1Hz)/Sv(10Hz) ~ sqrt(10) = 3.16
ratio_flick = sv(o, 1) / sv(o, 10)
check("[2] BSIM4 shows the 1/f flicker region at low frequency (Sv ~ 1/sqrt(f))",
      abs(ratio_flick - math.sqrt(10)) / math.sqrt(10) < 0.05,
      f"(Sv(1Hz)/Sv(10Hz) = {ratio_flick:.3f}, expect sqrt(10)=3.162)")

# flat thermal floor at high f
flat = sv(o, 1e8) / sv(o, 1e9)
check("[3] BSIM4 shows the flat thermal floor at high frequency",
      abs(flat - 1.0) < 0.1, f"(Sv(1e8)/Sv(1e9) = {flat:.3f})")

# ---- [4] HICUM noise is white (flat, no default flicker) ---------------------
run("hw.cir", """* hicum white noise
.control
pre_osdi hicuml2.osdi
.endc
Vcc cc 0 dc 3.0
RC cc c 400
Vsrc s 0 dc 0.77 ac 1
Rb s b 50
N1 c b 0 0 0 m
.model m hicumL2va t0=1e-11 cjei0=1f cjci0=1f cjep0=1f cjcx0=1f
.control
noise v(c) Vsrc dec 10 1 1e6
setplot noise1
wrdata hw.dat onoise_spectrum
.endc
.end
""")
hw = read2("hw.dat")
lo, hi = hw[0][1], hw[-1][1]      # 1 Hz and 1 MHz
check("[4] HICUM noise is white (flat) at mid-band -- no flicker by default",
      abs(hi - lo) / lo < 0.02, f"(Sv(1Hz)={lo:.3e}, Sv(1MHz)={hi:.3e})")

# ---- [5] HICUM output floor tracks collector shot noise 2q*Ic*RC^2 -----------
def hicum_shot(vbe):
    out = run("hs.cir", f"""* hicum shot
.control
pre_osdi hicuml2.osdi
.endc
Vcc cc 0 dc 3.0
RC cc c 400
Vsrc s 0 dc {vbe} ac 1
Rb s b 1
N1 c b 0 0 0 m
.model m hicumL2va t0=1e-11 cjei0=1f cjci0=1f cjep0=1f cjcx0=1f
.control
op
print abs(i(vcc))
noise v(c) Vsrc dec 4 1e4 1e6
setplot noise1
print onoise_spectrum[4]
.endc
.end
""")
    ic = float(re.search(r"i\(vcc\)\)\s*=\s*([-\d.eE+]+)", out).group(1))
    nf = float(re.search(r"onoise_spectrum\[4\]\s*=\s*([-\d.eE+]+)", out).group(1))
    return ic, nf

ic_lo, nf_lo = hicum_shot(0.74)
ic_hi, nf_hi = hicum_shot(0.80)
shot_hi = math.sqrt(2 * Q * ic_hi * 400 ** 2)
ratio = nf_hi / shot_hi
scale = nf_hi / nf_lo
scale_exp = math.sqrt(ic_hi / ic_lo)     # shot ~ sqrt(Ic)
check("[5] HICUM output floor tracks collector shot noise 2q*Ic*RC^2, scales sqrt(Ic)",
      0.9 < ratio < 1.4 and abs(scale - scale_exp) / scale_exp < 0.2,
      f"(floor/shot = {ratio:.2f}; scaling {scale:.2f} vs sqrt(Ic/Ic) {scale_exp:.2f})")

print(f"\n{passed} passed, {failed} failed")
raise SystemExit(1 if failed else 0)
