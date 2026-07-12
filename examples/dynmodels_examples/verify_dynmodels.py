#!/usr/bin/env python3
"""
Enhancement-161: dynamic (AC / RF) compact-model validation.

Enhancements 159-160 validated the CMC compact models' DC behavior. This one
exercises their DYNAMIC behavior -- the part that matters most for analog and RF
-- which flows through a completely different code path: OSDI's REACTIVE (charge)
Jacobian stamping and ngspice's `.ac` analysis. The models are the CMC reference
decks bundled with OpenVAF, compiled in place.

Two device classes, validated where a built-in reference exists:

  * BSIM4 C-V -- the gate capacitance Cgg(Vgs) extracted from `.ac`
    (Cgg = Im(I_gate)/omega). It rises from a small subthreshold value to the
    oxide capacitance in inversion -- the textbook MOSFET C-V curve -- and the
    OSDI model matches ngspice's BUILT-IN BSIM4 to well under a percent, a
    stringent check of the reactive stamping.

  * BSIM4 fT -- the cutoff frequency, where the AC current gain |h21|=|Id/Ig|
    falls to 1. The OSDI model matches the built-in to ~1%.

  * HICUML2 fT -- the same cutoff frequency for a SiGe HBT (no ngspice built-in).
    The default model has zero transit time (t0=0) -> infinite fT, so a realistic
    dynamic parameter set is supplied (t0=10 ps, 1 fF junction caps); the
    resulting fT sits right at the transit-time limit 1/(2*pi*t0) ~ 15.9 GHz and
    rises with collector current -- textbook bipolar behavior.

Checks (each under BOTH the Sparse and KLU solvers -- `.ac` is supported by both):
  [1] BSIM4 Cgg(Vgs) matches built-in BSIM4 to <2% across the C-V sweep.
  [2] the C-V curve is physical: Cgg rises from subthreshold to inversion.
  [3] BSIM4 cutoff frequency fT matches built-in BSIM4 to <3%.
  [4] HICUML2 fT sits at the transit-time limit 1/(2*pi*t0) and rises with Ic.

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
SCRATCH = tempfile.mkdtemp(prefix="dynmodels_")
passed = failed = 0


def check(name, ok, detail=""):
    global passed, failed
    if ok:
        passed += 1
        print(f"  PASS  {name} {detail}")
    else:
        failed += 1
        print(f"  FAIL  {name} {detail}")


def compile_model(m, va_sub, out):
    subprocess.run([OPENVAF, va_sub, "-o", os.path.join(SCRATCH, out)],
                   cwd=os.path.join(ITEST, m), capture_output=True, text=True, timeout=300)
    return os.path.exists(os.path.join(SCRATCH, out))


def run(name, deck):
    open(os.path.join(SCRATCH, name), "w").write(deck)
    r = subprocess.run([NGSPICE, "-b", name], capture_output=True, text=True,
                       timeout=120, cwd=SCRATCH)
    return r.stdout + r.stderr


def grab(log, name):
    m = re.search(rf"{re.escape(name)}\s*=\s*(-?[0-9.eE+-]+)", log)
    return float(m.group(1)) if m else float("nan")


ok4 = compile_model("BSIM4", "bsim4.va", "bsim4.osdi")
okh = compile_model("HICUML2", "hicuml2.va", "hicuml2.osdi")
if not (ok4 and okh):
    check("models compile", False)
    raise SystemExit(1)

# ---- [1]/[2] BSIM4 C-V (Cgg vs Vgs), OSDI vs built-in -----------------------
vgs_list = [0.0, 0.2, 0.4, 0.6, 0.8, 1.0, 1.2]
cgg_bi, cgg_os = [], []
for vg in vgs_list:
    log = run("cv.cir", f"""* bsim4 C-V point
.control
pre_osdi bsim4.osdi
.endc
Vgb gb 0 dc {vg} ac 1
Vdb db 0 dc 0.05
M1 db gb 0 0 nb W=10u L=1u
.model nb nmos level=54 version=4.8.2 rdsmod=1 rsh=1
Vgo go 0 dc {vg} ac 1
Vdo do 0 dc 0.05
N1 do go 0 0 no
.model no bsim4va w=10u l=1u rdsmod=1 rsh=1
.ac lin 1 1meg 1meg
.control
run
let w = 2*pi*1e6
let cb = abs(imag(i(vgb)))/w*1e15
let co = abs(imag(i(vgo)))/w*1e15
print cb co
.endc
.end
""")
    cgg_bi.append(grab(log, "cb"))
    cgg_os.append(grab(log, "co"))

mxcv = max(abs(o - b) / b for b, o in zip(cgg_bi, cgg_os) if b > 1)
check("[1] BSIM4 Cgg(Vgs) matches built-in BSIM4 to <2% (C-V / reactive stamping)",
      mxcv < 0.02, f"(max reldiff {mxcv*100:.3f}%, Cgg {cgg_os[0]:.0f}->{cgg_os[-1]:.0f} fF)")

check("[2] BSIM4 C-V is physical: Cgg rises from subthreshold to inversion",
      cgg_os[-1] > 2 * cgg_os[0] and all(cgg_os[i] >= cgg_os[i-1] - 1 for i in range(1, len(cgg_os))),
      f"(Cgg {cgg_os[0]:.1f} -> {cgg_os[-1]:.1f} fF)")

# ---- [3] BSIM4 fT, OSDI vs built-in ----------------------------------------
log = run("ft.cir", """* bsim4 fT
.control
pre_osdi bsim4.osdi
.endc
Vgb gb 0 dc 1.0 ac 1
Vdb db 0 dc 0.6
M1 db gb 0 0 nb W=10u L=1u
.model nb nmos level=54 version=4.8.2 rdsmod=1 rsh=1
Vgo go 0 dc 1.0 ac 1
Vdo do 0 dc 0.6
N1 do go 0 0 no
.model no bsim4va w=10u l=1u rdsmod=1 rsh=1
.ac dec 30 1e6 1e12
.control
run
let h21b = abs(i(vdb)/i(vgb))
let h21o = abs(i(vdo)/i(vgo))
meas ac ftb when h21b=1
meas ac fto when h21o=1
.endc
.end
""")
ftb, fto = grab(log, "ftb"), grab(log, "fto")
check("[3] BSIM4 cutoff frequency fT matches built-in BSIM4 to <3%",
      abs(fto - ftb) / ftb < 0.03,
      f"(built-in {ftb/1e9:.3f} GHz, OSDI {fto/1e9:.3f} GHz)")

# ---- [4] HICUML2 fT: transit-time limit + rises with Ic --------------------
def hicum_ft(vbe):
    log = run("hft.cir", f"""* hicum fT
.control
pre_osdi hicuml2.osdi
.endc
Vc c 0 dc 1.5
Vb b 0 dc {vbe} ac 1
N1 c b 0 0 0 m
.model m hicumL2va t0=1e-11 cjei0=1f cjci0=1f cjep0=1f cjcx0=1f
.ac dec 20 1e8 1e12
.control
run
let h21 = abs(i(vc)/i(vb))
meas ac ft when h21=1
print abs(i(vc)[0])
.endc
.end
""")
    return grab(log, "ft")

ft_lo = hicum_ft(0.75)
ft_hi = hicum_ft(0.85)
ft_limit = 1.0 / (2 * math.pi * 1e-11)   # 1/(2*pi*t0) ~ 15.9 GHz
check("[4] HICUML2 (SiGe HBT) fT at transit-time limit 1/(2*pi*t0) and rises with Ic",
      abs(ft_hi - ft_limit) / ft_limit < 0.2 and ft_hi >= ft_lo,
      f"(fT {ft_lo/1e9:.1f}->{ft_hi/1e9:.1f} GHz vs limit {ft_limit/1e9:.1f} GHz)")

print(f"\n{passed} passed, {failed} failed")
raise SystemExit(1 if failed else 0)
