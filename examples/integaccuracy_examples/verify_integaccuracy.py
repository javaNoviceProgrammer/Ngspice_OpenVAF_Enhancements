#!/usr/bin/env python3
"""Enhancement-259: transient integration accuracy proof (oracle-based).

A permanent regression guard for ngspice's transient integration engine, in the
E-251 (Harmonic-Balance) / E-255 (.disto) mold: rather than checking one waveform,
it proves the integrator's mathematical *properties* against closed-form analytics
and self-convergence. A wrong integration coefficient (NIcomCof), a broken order,
or a spurious trapezoidal-ringing damp would violate one of these.

Checks (both solvers -- the integrator is solver-independent, so Sparse == KLU):
 [1] ORDER OF ACCURACY on an RC decay v(t)=exp(-t/RC): the global error vs the
     closed form scales as dt^p with the theoretical p -- TRAP p~2, Gear2 p~2,
     Backward-Euler (Gear order 1) p~1.
 [2] ENERGY SIGNATURE on an LC oscillator v(t)=cos(w t): TRAP is marginally stable
     (amplitude PRESERVED over 30 periods -- energy-conserving, and the
     trapezoidal-ringing BE-switch is NOT firing spuriously); Backward-Euler is
     dissipative (amplitude decays strongly).
 [3] BREAKPOINT handling: a PULSE edge into an RC matches the piecewise-analytic
     charge response exactly, with the pre-edge value pinned at 0.
 [4] RLC damped sinusoid: the transient matches the closed-form
     exp(-alpha t)(cos wd t + (alpha/wd) sin wd t) -- correct damped frequency and
     envelope.
 [5] NONLINEAR charge: a diode + junction-capacitance rectifier converges under
     Richardson (TRAP, dt -> dt/2) at order ~2 -- the nonlinear device charge
     integration is 2nd order too.
 [6] LTE STEP CONTROLLER (Enhancement-260): on a stiff circuit (fast + slow modes
     1000x apart) the adaptive local-truncation-error step controller delivers an
     accuracy that TRACKS reltol -- the error vs the closed form shrinks monotonically
     as reltol tightens (a broken LTE estimate would plateau or mis-size the steps).

Line 1 of every deck is the title (ignored).
"""
import math
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from _setup import NG as NGSPICE  # noqa: E402
from _setup import check_both_solvers as _check_both_solvers  # noqa: E402
_check_both_solvers(__file__)

passed = failed = 0


def check(label, ok, detail=""):
    global passed, failed
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  {detail}" if detail else ""))
    passed += 1 if ok else 0
    failed += 0 if ok else 1


def tran(body, node, ctrl_opts=""):
    """Run a .tran deck, return {t: value} for `node` (wrdata columns t val)."""
    deck = f"* integ\n{body}\n.control\nrun\nwrdata {HERE}/_ia.dat {node}\n.endc\n.end\n"
    open(os.path.join(HERE, "_ia.cir"), "w").write(deck)
    subprocess.run([NGSPICE, "-b", "_ia.cir"], capture_output=True, text=True,
                   cwd=HERE, timeout=120)
    out = {}
    try:
        for ln in open(os.path.join(HERE, "_ia.dat")):
            s = ln.split()
            if len(s) >= 2:
                out[float(s[0])] = float(s[1])
    except OSError:
        pass
    return out


RC = 1e-3
FIX = "trtol=1e11 reltol=1e-11 abstol=1e-16"      # freeze LTE -> uniform steps for the order test


def rc_err(method, maxord, dt):
    mo = f" maxord={maxord}" if maxord else ""
    d = tran(f".ic v(c)=1\nR1 c 0 1k\nC1 c 0 1u\n"
             f".options {FIX} method={method}{mo}\n.tran {dt} 5m 0 {dt} uic", "v(c)")
    return max((abs(v - math.exp(-t / RC)) for t, v in d.items() if t > 0), default=1.0)


# ---------------- [1] order of accuracy vs closed-form RC decay ----------------
DTS = [200e-6, 100e-6, 50e-6, 25e-6]
results = {}
for label, method, mo, lo, hi in [("TRAP", "trap", None, 1.7, 2.3),
                                  ("Gear2", "gear", 2, 1.7, 2.3),
                                  ("BE", "gear", 1, 0.7, 1.3)]:
    errs = [rc_err(method, mo, d) for d in DTS]
    p = math.log2(errs[-2] / errs[-1])           # order from the two finest steps
    results[label] = p
    check(f"[1] {label}: order of accuracy p = {p:.2f} (theory {'2' if hi > 1.5 else '1'})",
          lo <= p <= hi, f"(errs {errs[0]:.1e}->{errs[-1]:.1e})")

# ---------------- [2] LC energy signature ----------------
L, C = 1e-3, 1e-6
w = 1.0 / math.sqrt(L * C)
T = 2 * math.pi / w
dt = T / 200


def lc_ratio(method, maxord):
    mo = f" maxord={maxord}" if maxord else ""
    d = tran(f".ic v(c)=1\nL1 c 0 {L}\nC1 c 0 {C}\n"
             f".options {FIX} method={method}{mo}\n.tran {dt} {30*T} 0 {dt} uic", "v(c)")
    first = max((abs(v) for t, v in d.items() if t <= T), default=0)
    last = max((abs(v) for t, v in d.items() if t >= 29 * T), default=0)
    return last / first if first else 0


rt = lc_ratio("trap", None)
rb = lc_ratio("gear", 1)
check("[2] TRAP conserves LC energy (amplitude preserved, no spurious ringing-damp)",
      rt > 0.98, f"(peak ratio over 30 periods = {rt:.4f}; >0.98)")
check("[2] Backward-Euler is dissipative on the LC (amplitude decays)",
      rb < 0.5, f"(peak ratio = {rb:.4f}; <0.5)")

# ---------------- [3] breakpoint (PULSE edge into RC) ----------------
d = tran("V1 in 0 PULSE(0 1 1m 1n 1n 5m 20m)\nR1 in c 1k\nC1 c 0 1u\n.tran 5u 3m", "v(c)")
be = lambda t: 0.0 if t < 1e-3 else 1 - math.exp(-(t - 1e-3) / RC)
err_bp = max((abs(v - be(t)) for t, v in d.items()), default=1.0)
pre = max((v for t, v in d.items() if 0.9e-3 < t < 1.0e-3), default=1.0)
check("[3] breakpoint: PULSE edge into RC matches piecewise-analytic, pre-edge pinned at 0",
      err_bp < 1e-5 and pre < 1e-6, f"(max err {err_bp:.2e}, pre-edge {pre:.1e})")

# ---------------- [4] RLC damped sinusoid ----------------
wn = 1 / math.sqrt(1e-3 * 1e-6)
alpha = 20 / (2e-3)
wd = math.sqrt(wn ** 2 - alpha ** 2)
d = tran(".ic v(c)=1\nR1 c a 20\nL1 a 0 1m\nC1 c 0 1u\n.options reltol=1e-9\n.tran 2u 4m uic", "v(c)")
ana = lambda t: math.exp(-alpha * t) * (math.cos(wd * t) + (alpha / wd) * math.sin(wd * t))
err_rlc = max((abs(v - ana(t)) for t, v in d.items()), default=1.0)
check("[4] RLC damped sinusoid matches closed form (damped freq + envelope)",
      err_rlc < 1e-4, f"(fd={wd/2/math.pi:.0f}Hz, max err {err_rlc:.2e})")

# ---------------- [5] nonlinear charge: diode+CJO Richardson order ----------------
def rect(dt):
    return tran(f"V1 in 0 SIN(0 1 2k)\nD1 in o DMOD\nR1 o 0 1k\nC1 o 0 100n\n"
                f".model DMOD D(IS=1e-14 N=1 CJO=5p)\n.options {FIX} method=trap\n"
                f".tran {dt} 1m 0 {dt} uic", "v(o)")


def dnorm(a, b):
    ks = set(a) & set(b)
    return max((abs(a[k] - b[k]) for k in ks), default=1.0)


sols = [rect(d) for d in (200e-9, 100e-9, 50e-9)]
d1, d2 = dnorm(sols[0], sols[1]), dnorm(sols[1], sols[2])
p_nl = math.log2(d1 / d2) if d2 > 0 else 0
check("[5] nonlinear (diode+CJO rectifier) TRAP Richardson order p ~ 2",
      1.7 <= p_nl <= 2.3, f"(p = {p_nl:.2f})")

# ---------------- [6] LTE step-controller: delivered accuracy tracks reltol ----------------
# Enhancement-260: on a STIFF circuit (fast + slow modes, 1000x apart) the adaptive
# LTE step controller must resolve the fast decay then coarsen. The DELIVERED error
# vs the closed form must shrink as reltol tightens (a broken LTE estimate would
# plateau or mis-size the steps). tau_fast=1us, tau_slow=1ms.
TFa, TSl = 1e-6, 1e-3


def stiff_err(reltol):
    d_all = {}
    deck = (f".ic v(f)=1 v(s)=1\nRf f 0 1k\nCf f 0 1n\nRs s 0 1meg\nCs s 0 1n\n"
            f".options reltol={reltol}\n.tran 0.2u 5m 0 5u uic")
    # wrdata writes two vectors -> columns t vf t vs
    open(os.path.join(HERE, "_ia.cir"), "w").write(
        f"* stiff\n{deck}\n.control\nrun\nwrdata {HERE}/_ia.dat v(f)\n.endc\n.end\n")
    subprocess.run([NGSPICE, "-b", "_ia.cir"], capture_output=True, text=True,
                   cwd=HERE, timeout=120)
    out = {}
    for ln in open(os.path.join(HERE, "_ia.dat")):
        s = ln.split()
        if len(s) >= 2:
            out[float(s[0])] = float(s[1])
    return max((abs(v - math.exp(-t / TFa)) for t, v in out.items() if t > 0), default=1.0)


e_loose = stiff_err(1e-3)
e_mid = stiff_err(1e-5)
e_tight = stiff_err(1e-7)
check("[6] LTE controller: delivered error on a stiff circuit tracks reltol (monotone, no plateau)",
      e_tight < e_mid < e_loose and e_tight < e_loose / 10.0,
      f"(err @reltol 1e-3/1e-5/1e-7 = {e_loose:.1e}/{e_mid:.1e}/{e_tight:.1e}; "
      f"improved {e_loose/e_tight:.0f}x)")

for f in ("_ia.cir", "_ia.dat"):
    p = os.path.join(HERE, f)
    if os.path.exists(p):
        os.remove(p)
print(f"\n{passed} passed, {failed} failed")
raise SystemExit(1 if failed else 0)
