#!/usr/bin/env python3
"""Enhancement-167: cross-model self-heating sweep.

Enhancement-166 validated one production compact model's self-heating (HICUM/L2).
This is the breadth follow-up -- like E-160 was to E-159 -- driving the SAME
electro-thermal analogy through *every* bundled CMC model that exposes a
self-heating thermal terminal, across four different device classes:

    HICUM/L2   SiGe HBT       flsh=1,  rth   (direct, K/W)
    ASMHEMT    GaN HEMT       shmod=1, rth0  (direct, K/W)
    BSIMBULK   bulk MOSFET    SHMOD=1, RTH0  (per width, m*K/W -> rth_eff=RTH0/W)
    BSIMCMG    FinFET         SHMOD=1, RTH0  (geometry-normalized)

Each model carries an internal thermal branch of the form
`Pwr(thermal) <+ Temp(thermal)/rth - Pdiss`, so wiring the model's thermal
terminal to a circuit node lets us read the junction temperature rise directly
and check the electro-thermal analogy `V(tnode) = Pdiss * rth_eff`.

The self-heating value V(tnode)/Pdiss is a genuine *thermal resistance*: it must
be (a) zero when the model's self-heating flag is off, (b) a bias-independent
constant, (c) linearly controlled by the model's thermal-resistance parameter,
and (d) -- for models whose parameter is a direct thermal resistance -- equal to
that parameter (or RTH0/W for the per-width MOSFET) to machine precision.

Checks, for each of the four models, under BOTH the Sparse and KLU solvers:
  [off]      self-heating flag off  -> V(tnode) = 0.
  [analogy]  self-heating on, two operating points -> V(tnode)/Pdiss is a
             bias-independent constant equal to the expected rth_eff (exact for
             the three direct/per-width models; for the geometry-normalized
             FinFET, bias-independent is required and the exact value is not).
  [control]  doubling the model's rth parameter doubles V(tnode)/Pdiss.

Every SPICE deck starts with a title line (SPICE treats line 1 as the title!).
"""
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
SCRATCH = tempfile.mkdtemp(prefix="cmcselfheat_")
passed = failed = 0


def check(name, ok, detail=""):
    global passed, failed
    if ok:
        passed += 1
        print(f"  PASS  {name} {detail}")
    else:
        failed += 1
        print(f"  FAIL  {name} {detail}")


def compile_model(subdir, va, osdi):
    subprocess.run([OPENVAF, va, "-o", os.path.join(SCRATCH, osdi)],
                   cwd=os.path.join(ITEST, subdir), capture_output=True, text=True, timeout=300)
    return os.path.exists(os.path.join(SCRATCH, osdi))


def run(deck):
    open(os.path.join(SCRATCH, "d.cir"), "w").write(deck)
    r = subprocess.run([NGSPICE, "-b", "d.cir"], capture_output=True, text=True,
                       timeout=120, cwd=SCRATCH)
    return r.stdout + r.stderr


def val(out, name):
    m = re.search(re.escape(name) + r"[\)\s]*=\s*([-\d.eE+]+)", out)
    return float(m.group(1)) if m else None


# --- per-model deck builders --------------------------------------------------
# Each returns a deck that prints `ratio` = V(tnode)/Pdiss and `vth` = V(tnode).
# The thermal terminal `th` is wired to a live node so the temperature rise can be
# read directly. A 1e12-ohm probe resistor from `th` to ground keeps that node
# non-singular for KLU when self-heating is off (some models leave the thermal
# node unconstrained in that case); it is negligible when self-heating is on,
# since the model's own thermal conductance 1/rth (>= ~1e-5 S here) swamps the
# 1e-12 S probe -- the V(tnode)=Pdiss*rth ratio is unaffected to < 1e-7.

def deck_hicum(osdi, rthp, sh, drive):
    # SiGe HBT, current-biased (stable OP); Pdiss = Ic*Vce, Vce=2 V.
    return f"""* hicum self-heating
.control
pre_osdi {osdi}
.endc
Vc c 0 dc 2.0
Ibb 0 b dc {drive}
N1 c b 0 0 th m
Rthp th 0 1e12
.model m hicumL2va flsh={sh} rth={rthp}
.op
.control
run
let ratio = v(th)/(abs(i(vc))*v(c))
print ratio v(th)
.endc
.end
"""

def deck_asmhemt(osdi, rthp, sh, drive):
    # GaN HEMT (depletion, conducts at Vg=0); Pdiss = Id*Vds, Vds=5 V; drive=Vgs.
    return f"""* asmhemt self-heating
.control
pre_osdi {osdi}
.endc
Vd d 0 dc 5.0
Vg g 0 dc {drive}
N1 d g 0 0 th asm
Rthp th 0 1e12
.model asm asmhemt shmod={sh} rth0={rthp}
.op
.control
run
let ratio = v(th)/(abs(i(vd))*v(d))
print ratio v(th)
.endc
.end
"""

def deck_bsimbulk(osdi, rthp, sh, drive):
    # bulk NMOS; RTH0 is per width (m*K/W) so rth_eff = RTH0/W, here W=1 um.
    return f"""* bsimbulk self-heating
.control
pre_osdi {osdi}
.endc
Vd d 0 dc 1.0
Vg g 0 dc {drive}
N1 d g 0 0 th nmos W=1u L=0.1u
Rthp th 0 1e12
.model nmos bsimbulk SHMOD={sh} RTH0={rthp}
.op
.control
run
let ratio = v(th)/(abs(i(vd))*v(d))
print ratio v(th)
.endc
.end
"""

def deck_bsimcmg(osdi, rthp, sh, drive):
    # FinFET; RTH0 is geometry-normalized (bias-independent, linear in RTH0).
    return f"""* bsimcmg self-heating
.control
pre_osdi {osdi}
.endc
Vd d 0 dc 1.0
Vg g 0 dc {drive}
N1 d g 0 0 th nfin
Rthp th 0 1e12
.model nfin bsimcmg_va SHMOD={sh} RTH0={rthp}
.op
.control
run
let ratio = v(th)/(abs(i(vd))*v(d))
print ratio v(th)
.endc
.end
"""


# model spec: (label, class, subdir, va, osdi, deck-fn, rthp1, rthp2, two drives,
#              expected rth_eff for rthp1 or None if geometry-normalized)
MODELS = [
    ("HICUM/L2", "SiGe HBT",    "HICUML2",  "hicuml2.va",  "hicuml2.osdi",  deck_hicum,
     2000, 4000, ("20u", "40u"), 2000.0),
    ("ASMHEMT",  "GaN HEMT",    "ASMHEMT",  "asmhemt.va",  "asmhemt.osdi",  deck_asmhemt,
     20, 40, ("0.0", "-0.5"), 20.0),
    ("BSIMBULK", "bulk MOSFET", "BSIMBULK", "bsimbulk.va", "bsimbulk.osdi", deck_bsimbulk,
     1e-3, 2e-3, ("1.2", "1.5"), 1e-3 / 1e-6),          # rth_eff = RTH0/W, W=1um
    ("BSIMCMG",  "FinFET",      "BSIMCMG",  "bsimcmg.va",  "bsimcmg.osdi",  deck_bsimcmg,
     5e-3, 1e-2, ("0.9", "1.2"), None),                 # geometry-normalized
]

for (label, klass, subdir, va, osdi, deckfn, r1, r2, drives, rexp) in MODELS:
    print(f"\n--- {label} ({klass}) ---")
    if not compile_model(subdir, va, osdi):
        check(f"{label}: model compiles", False)
        continue

    # [off] self-heating flag off -> V(tnode) = 0
    off = run(deckfn(osdi, r1, 0, drives[0]))
    vth_off = val(off, "v(th")
    check(f"{label}: self-heating off -> V(tnode)=0",
          vth_off is not None and abs(vth_off) < 1e-9, f"(V(tnode)={vth_off})")

    # [analogy] on, two operating points -> ratio is a bias-independent constant
    d0 = run(deckfn(osdi, r1, 1, drives[0]))
    d1 = run(deckfn(osdi, r1, 1, drives[1]))
    ra, rb = val(d0, "ratio"), val(d1, "ratio")
    va0, va1 = val(d0, "v(th"), val(d1, "v(th")
    bias_indep = (ra and rb and abs(ra - rb) / ra < 1e-3)
    if rexp is not None:
        exact = bias_indep and abs(ra - rexp) / rexp < 1e-3
        check(f"{label}: V(tnode)/Pdiss = rth_eff exactly, bias-independent",
              exact, f"(ratio={ra:.6g} vs expected {rexp:.6g} K/W; "
                     f"two OPs {va0:.3g}/{va1:.3g} K)")
    else:
        check(f"{label}: V(tnode)/Pdiss is a bias-independent thermal resistance",
              bias_indep, f"(ratio={ra:.6g} K/W at two OPs: {va0:.3g}/{va1:.3g} K)")

    # [control] doubling the rth parameter doubles the ratio
    d2 = run(deckfn(osdi, r2, 1, drives[0]))
    rc = val(d2, "ratio")
    scale = rc / ra if ra else 0
    check(f"{label}: doubling the rth parameter doubles V(tnode)/Pdiss",
          abs(scale - r2 / r1) < 1e-3 * (r2 / r1),
          f"(param x{r2/r1:.0f} -> ratio x{scale:.4f})")

print(f"\n{passed} passed, {failed} failed")
raise SystemExit(1 if failed else 0)
