#!/usr/bin/env python3
"""Enhancement-166: electro-thermal / self-heating validation.

Enhancements 159-165 validated a real compact model's DC, coverage, small-signal,
large-signal and noise behavior with the device treated as ISOTHERMAL. This one
exercises the remaining untested path -- a model's own internal SELF-HEATING node,
stamped by OSDI as an extra (thermal) terminal whose "voltage" is the temperature
rise and whose "current" is the dissipated power.

HICUM/L2 (SiGe HBT) carries a full electro-thermal network gated by its `flsh`
flag: an internal thermal branch `I(br_sht) <+ V(tnode)/rth - Pdiss` with model
parameters `rth` (thermal resistance, K/W) and `cth` (thermal capacitance, J/K).
Exposing the thermal node as a 5th terminal lets us probe the temperature rise
directly and check it against the textbook electro-thermal analogy:

    voltage  <->  temperature rise      current  <->  dissipated power
    resistor <->  thermal resistance    capacitor <-> thermal capacitance

so at DC   V(tnode) = Pdiss * rth   and the thermal node settles with a single
time constant  tau = rth * cth.

Checks (each under BOTH the Sparse and KLU solvers):
  [1] self-heating OFF (flsh=0) -> V(tnode)=0 : an isothermal baseline.
  [2] STATIC analogy: with the device current-biased (a stable operating point),
      V(tnode) = Pdiss*rth to machine precision, over a decade of power and for
      two different rth.
  [3] FEEDBACK: at a fixed collector current, self-heating lowers Vbe by a
      consistent, physical temperature coefficient (~ -1.5 mV/K), and more so for
      larger rth (more heating) -- the model's parameters really feed the junction.
  [4] DYNAMIC: after a power step the thermal node rises as a single pole, its
      value at one time constant reaching ~63.2% of the final rise, with
      tau = rth*cth.
  [5] tau scales with cth: doubling cth doubles the thermal time constant.
  [6] RUNAWAY: under a fixed Vbe (voltage drive) self-heating is positive
      feedback -- the self-heated collector current runs far above the isothermal
      current at high bias -- the classic reason real bias networks use current
      or emitter degeneration. (Physics demonstration, no golden number.)

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
SCRATCH = tempfile.mkdtemp(prefix="electrothermal_")
passed = failed = 0


def check(name, ok, detail=""):
    global passed, failed
    if ok:
        passed += 1
        print(f"  PASS  {name} {detail}")
    else:
        failed += 1
        print(f"  FAIL  {name} {detail}")


def run(name, deck):
    open(os.path.join(SCRATCH, name), "w").write(deck)
    r = subprocess.run([NGSPICE, "-b", name], capture_output=True, text=True,
                       timeout=180, cwd=SCRATCH)
    return r.stdout + r.stderr


def dat(fn):
    p = os.path.join(SCRATCH, fn)
    return [[float(x) for x in l.split()] for l in open(p)] if os.path.exists(p) else []


def op_val(out, name):
    m = re.search(re.escape(name) + r"[\)\s]*=\s*([-\d.eE+]+)", out)
    return float(m.group(1)) if m else None


# --- compile HICUM/L2 in place from the OpenVAF integration-test source --------
subprocess.run([OPENVAF, "hicuml2.va", "-o", os.path.join(SCRATCH, "hicuml2.osdi")],
               cwd=os.path.join(ITEST, "HICUML2"), capture_output=True, text=True, timeout=300)
if not os.path.exists(os.path.join(SCRATCH, "hicuml2.osdi")):
    check("HICUM/L2 compiles", False)
    print(f"\n{passed} passed, {failed} failed")
    raise SystemExit(1)

# A current-biased common-emitter stage: forcing the base current gives a stable
# operating point (no thermal runaway), so the self-heating checks are well posed.
# Terminals of the OSDI HICUM device: (c, b, e, s, tnode).
CURRENT_BIASED = """* hicum self-heating (current-biased, stable)
.control
pre_osdi hicuml2.osdi
.endc
Vc c 0 dc 2.0
Ibb 0 b dc {ib}
N1 c b 0 0 th m
.model m hicumL2va {mp}
.op
.control
run
set numdgt=10
print abs(i(vc)) v(b) v(th)
.endc
.end
"""

# ---- [1] self-heating OFF -> V(tnode)=0 --------------------------------------
out = run("iso.cir", CURRENT_BIASED.format(ib="20u", mp="flsh=0 rth=2000"))
vth0 = op_val(out, "v(th")
check("[1] self-heating off (flsh=0) -> V(tnode)=0 (isothermal baseline)",
      vth0 is not None and abs(vth0) < 1e-9, f"(V(tnode)={vth0:.3e})")

# ---- [2] STATIC: V(tnode) = Pdiss*rth to machine precision, two rth -----------
def static_worst(rth):
    run("pa.cir", """* Vtnode vs power
.control
pre_osdi hicuml2.osdi
.endc
Vc c 0 dc 2.0
Ibb 0 b dc 5u
N1 c b 0 0 th m
.model m hicumL2va flsh=1 rth=%d
.dc Ibb 2u 40u 2u
.control
run
let pdiss = abs(i(vc))*2.0
wrdata pa.dat pdiss v(th)
.endc
.end
""" % rth)
    rows = dat("pa.dat")            # cols: Ibb, pdiss, Ibb, v(th)
    return max(abs(r[3] - r[1] * rth) / (r[1] * rth) for r in rows if r[1] > 0)

w1, w2 = static_worst(1500), static_worst(3000)
check("[2] static analogy V(tnode)=Pdiss*rth exact over a decade of power, two rth",
      w1 < 1e-4 and w2 < 1e-4,
      f"(max reldiff: rth=1500 {w1*100:.4f}%, rth=3000 {w2*100:.4f}%)")

# ---- [3] FEEDBACK: self-heating lowers Vbe at fixed Ic, physical TC -----------
# fixed base current -> nearly fixed Ic; compare isothermal Vbe with self-heated.
iso = run("f0.cir", CURRENT_BIASED.format(ib="20u", mp="flsh=0 rth=0"))
vbe_iso = op_val(iso, "v(b")
tc = []
for rth in (2000, 6000):
    sh = run("f1.cir", CURRENT_BIASED.format(ib="20u", mp=f"flsh=1 rth={rth}"))
    vbe, dt = op_val(sh, "v(b"), op_val(sh, "v(th")
    tc.append((rth, vbe, dt, (vbe - vbe_iso) / dt * 1e3))   # mV/K
# Vbe drops (negative TC), the TC is physical (-1..-2.5 mV/K), consistent across
# rth, and larger rth -> more heating -> larger Vbe drop.
tc_ok = (all(-2.5 < t[3] < -1.0 for t in tc)
         and abs(tc[0][3] - tc[1][3]) < 0.15               # consistent TC
         and tc[1][1] < tc[0][1] < vbe_iso)                # monotone drop
check("[3] self-heating lowers Vbe at fixed Ic (consistent physical TC ~ -1.5 mV/K)",
      tc_ok,
      f"(Vbe iso={vbe_iso:.4f}; "
      + ", ".join(f"rth={t[0]}: dT={t[2]:.1f}K Vbe={t[1]:.4f} TC={t[3]:.2f}mV/K" for t in tc) + ")")

# ---- [4]/[5] DYNAMIC: thermal transient tau = rth*cth ------------------------
def thermal_transient(rth, cth):
    """rise fraction at one nominal time constant after a collector-voltage
    (power) step; the device stays biased ON throughout, so the step is a
    power-level change, not a turn-on discontinuity."""
    tau = rth * cth
    run("tt.cir", """* thermal transient (power step)
.control
pre_osdi hicuml2.osdi
.endc
Vc c 0 dc 2.0 pwl(0 2.0 0.9999m 2.0 1.0m 3.5 {tstop} 3.5)
Ibb 0 b dc 20u
N1 c b 0 0 th m
.model m hicumL2va flsh=1 rth={rth} cth={cth}
.tran {tstep} {tstop}
.control
run
wrdata tt.dat v(th)
.endc
.end
""".format(rth=rth, cth=cth, tstep=tau / 50, tstop=10 * tau + 1e-3))
    rows = dat("tt.dat")
    t = [r[0] for r in rows]
    v = [r[1] for r in rows]
    at = lambda tt: v[min(range(len(t)), key=lambda k: abs(t[k] - tt))]
    v0, vfin = at(0.95e-3), at(9 * tau + 1e-3)
    return (at(1e-3 + tau) - v0) / (vfin - v0), tau

f2, tau2 = thermal_transient(2000, 1e-6)          # tau = 2 ms
f4, tau4 = thermal_transient(2000, 2e-6)          # tau = 4 ms
check("[4] thermal transient is single-pole: value at one tau ~ 63.2% of rise",
      abs(f2 - 0.632) < 0.02, f"(rise@1tau={f2:.3f}, expect 0.632; tau=rth*cth={tau2*1e3:.1f}ms)")
check("[5] thermal tau scales with cth (double cth -> double tau)",
      abs(f4 - 0.632) < 0.02 and abs(tau4 / tau2 - 2.0) < 1e-9,
      f"(rise@1tau={f4:.3f} at tau={tau4*1e3:.1f}ms)")

# ---- [6] RUNAWAY: fixed-Vbe self-heating is positive feedback -----------------
def gummel_ic(mp, vb, tnode):
    # tnode='0' ties the thermal node to ground (pure isothermal reference, no
    # thermal branch); tnode='th' exposes it so self-heating feeds back.
    out = run("gm.cir", """* gummel point
.control
pre_osdi hicuml2.osdi
.endc
Vc c 0 dc 2.0
Vb b 0 dc {vb}
N1 c b 0 0 {tn} m
.model m hicumL2va {mp}
.op
.control
run
print abs(i(vc))
.endc
.end
""".format(mp=mp, vb=vb, tn=tnode))
    return op_val(out, "i(vc")

ic_iso = gummel_ic("flsh=0", 0.82, "0")
ic_sh = gummel_ic("flsh=1 rth=1500", 0.82, "th")
check("[6] fixed-Vbe self-heating is positive feedback (runaway: Ic_sh >> Ic_iso)",
      ic_sh > 10 * ic_iso,
      f"(at Vbe=0.82V: isothermal Ic={ic_iso:.3e}A, self-heated Ic={ic_sh:.3e}A)")

print(f"\n{passed} passed, {failed} failed")
raise SystemExit(1 if failed else 0)
