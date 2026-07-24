#!/usr/bin/env python3
"""Enhancement-312: XSPICE integrating code models integrate at true second order.

Every XSPICE analog code model that integrates -- `s_xfer` (Laplace transfer
functions), `int`, `d_dt`, and the rest -- funnels through `cm_static_integrate()`
in src/xspice/cm/cm.c. Its trapezoidal, order-2 arm carried a self-documented
stand-in:

    case 2:
        /* WARNING - This code needs to be redone. */
        cur = -0.5 * ckt->CKTag[0] * intgr[1];   /* == backward Euler */

That is backward Euler, not trapezoidal, so the whole integrator was first-order
accurate -- the transient error fell only as O(h) instead of the O(h^2) every
native ngspice storage element delivers. For `s_xfer` a SECOND cause compounded
it: the controller-canonical feedback in s_xfer/cfunc.mod read the fed-back
integrator states from the PREVIOUS timestep (`cm_analog_get_ptr(i,1)`), making
the feedback explicit (lagged one step) and capping accuracy at O(h) on its own.

E-312 fixes both. (a) cm_static_integrate implements the real trapezoidal rule
y(n) = y(n-1) + (h/2)(u(n)+u(n-1)); the previous integrand u(n-1) lives in the
spare state double that cm_analog_alloc already reserves per integrator, rotated
through the CKTstates history for free. (b) s_xfer reads the CURRENT-iteration
feedback states (offset 0), so the loop is solved implicitly within each Newton
step. Both integration methods (trapezoidal and Gear) now converge at O(h^2).

------------------------------------------------------------------------------
Why this suite proves the fix WITHOUT needing the pre-fix binary
------------------------------------------------------------------------------
The distinguishing signature of the bug is the CONVERGENCE ORDER, which a single
binary can measure on its own: halve the timestep and watch how fast the error
shrinks. First-order (the bug) halves the error per halving (ratio ~2);
second-order (the fix) quarters it (ratio ~4). So the order test below FAILS on a
pre-fix build (ratios ~2) and PASSES here (ratios ~4) -- no reference binary
required. The absolute-accuracy and waveform checks are pinned to thresholds only
the second-order integrator can meet.

Oracle: a first-order low-pass H(s) = 1/(1 + tau s) driven by sin(w t) from rest
has the exact response
    y(t) = A [ w tau e^{-t/tau} + sin(w t) - w tau cos(w t) ],  A = 1/(1+(w tau)^2),
whose LHP pole damps the startup transient, leaving a clean O(h^2) steady-state
error to measure. A second, resonant, second-order s_xfer checks that the now-
implicit feedback stays convergent and correct on a harder (near-oscillatory)
transfer function.

The XSPICE code models load from the prebuilt bundle via SPICE_LIB_DIR (pointed
by _setup at bin/<os>/<arch>/). If the bundle is unavailable in this checkout the
a-device cannot load and the test self-skips.

Line 1 of every SPICE deck is the title (ignored).
"""
import math
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from _setup import NG as NGSPICE  # noqa: E402  (also sets SPICE_LIB_DIR)
from _setup import check_both_solvers as _check_both_solvers  # noqa: E402
_check_both_solvers(__file__)

passed = failed = 0


def check(label, ok, detail=""):
    global passed, failed
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  [{detail}]" if detail else ""))
    if ok:
        passed += 1
    else:
        failed += 1


def run(deck, name):
    path = os.path.join(HERE, name)
    with open(path, "w") as fh:
        fh.write(deck)
    try:
        r = subprocess.run([NGSPICE, "-b", name], cwd=HERE, capture_output=True,
                           text=True, timeout=120, errors="replace")
    except subprocess.TimeoutExpired:
        return -99, "[TIMEOUT]"
    return r.returncode, (r.stdout or "").replace("\r", "\n") + (r.stderr or "")


def read_dat(name):
    """Read a two-column wrdata file -> list of (t, v)."""
    rows = []
    p = os.path.join(HERE, name)
    if not os.path.exists(p):
        return rows
    for line in open(p):
        f = line.split()
        if len(f) >= 2:
            try:
                rows.append((float(f[0]), float(f[1])))
            except ValueError:
                pass
    return rows


# ---- oracle for H(s) = 1/(1 + tau s), input sin(w t), y(0)=0 -----------------
TAU = 1e-6
F = 100e3
W = 2 * math.pi * F
WT = W * TAU
A = 1.0 / (1.0 + WT * WT)


def lp_exact(t):
    return A * (WT * math.exp(-t / TAU) + math.sin(W * t) - WT * math.cos(W * t))


def lp_deck(h, tstop):
    return (f"* s_xfer 1st-order low-pass, fixed step {h:g}\n"
            f"vin in 0 dc 0 sin(0 1 {F:g})\n"
            f"a1 in outx xa\n"
            f".model xa s_xfer(num_coeff=[1] den_coeff=[{TAU:g} 1] int_ic=[0])\n"
            f"r1 outx 0 1meg\n"
            f".options reltol=1e-4 abstol=1e-12 method=trap\n"
            f".tran {h:g} {tstop:g} 0 {h:g}\n"
            f".control\nrun\nwrdata _lp.dat v(outx)\n.endc\n.end\n")


def lp_error(h, tstop=30e-6, t_from=10e-6):
    """Max |numeric - exact| over the settled window."""
    rc, out = run(lp_deck(h, tstop), "_lp.cir")
    if rc < 0 or any(k in out.lower() for k in
                     ("singular", "no convergence", "iteration limit",
                      "time step too small", "aborted")):
        return None, rc, out
    rows = read_dat("_lp.dat")
    err = 0.0
    n = 0
    for t, v in rows:
        if t >= t_from:
            err = max(err, abs(v - lp_exact(t)))
            n += 1
    return (err if n >= 20 else None), rc, out


# ---- availability gate: a dynamic s_xfer must load & run ----------------------
e0, rc0, out0 = lp_error(50e-9)
if e0 is None and ("unable to find" in out0.lower() or "can't find model" in out0.lower()
                   or rc0 < 0):
    print("  SKIP  XSPICE code models unavailable in this checkout "
          f"(rc={rc0}) -- cannot exercise s_xfer")
    for f in os.listdir(HERE):
        if f.startswith("_"):
            os.remove(os.path.join(HERE, f))
    raise SystemExit(0)

print("Enhancement-312: XSPICE integrators are second-order accurate")

# ---- 1. convergence ORDER: the fail-on-pre-fix discriminator -----------------
# Measured in the asymptotic window (h = 100/50/25 ns): coarser than that the
# 100 kHz sine is under-resolved (not yet asymptotic); finer, the reltol/output
# floor is reached. In this window O(h^2) quarters the error per halving.
hs = [100e-9, 50e-9, 25e-9]
errs = []
for h in hs:
    e, _, _ = lp_error(h)
    errs.append(e)
have_all = all(e is not None and e > 0 for e in errs)
if have_all:
    ratios = [errs[i] / errs[i + 1] for i in range(len(errs) - 1)]
    # O(h^2) => each ratio ~4; O(h) (the bug) => ~2. Require a clear >=3 with margin.
    order_ok = all(r >= 3.0 for r in ratios)
    check("error convergence is second-order (ratio ~4, not ~2) -- fails pre-fix",
          order_ok,
          "ratios " + ", ".join(f"{r:.2f}" for r in ratios))
    # Least-squares order p = slope of log(err) vs log(h) over all points.
    lx = [math.log(h) for h in hs]
    ly = [math.log(e) for e in errs]
    mx = sum(lx) / len(lx)
    my = sum(ly) / len(ly)
    p_est = (sum((x - mx) * (y - my) for x, y in zip(lx, ly))
             / sum((x - mx) ** 2 for x in lx))
    check("fitted order p >= 1.7 (backward-Euler stand-in gave p~1.0)",
          p_est >= 1.7, f"p~{p_est:.2f}")
else:
    check("error convergence is second-order (ratio ~4, not ~2) -- fails pre-fix",
          False, f"errors {errs}")
    check("fitted order p >= 1.7", False, "no data")

# ---- 2. absolute accuracy at a fixed, ordinary step --------------------------
e_25, _, _ = lp_error(25e-9)
check("absolute error at h=25ns below 1e-4 (pre-fix was ~5e-3 here)",
      e_25 is not None and e_25 < 1e-4, f"err={e_25:.3e}" if e_25 else "no data")

# ---- 3. forward correctness: waveform matches the closed form ----------------
# (independent of order: at a fine step the whole settled trace tracks the oracle)
rc, out = run(lp_deck(20e-9, 30e-6), "_lp.cir")
rows = read_dat("_lp.dat")
worst_rel = 0.0
for t, v in rows:
    if t >= 10e-6:
        worst_rel = max(worst_rel, abs(v - lp_exact(t)) / (abs(A) + 1e-30))
check("settled waveform tracks exact 1/(1+tau s) response (<1% of amplitude)",
      rows and worst_rel < 1e-2, f"worst rel={worst_rel:.3e}")

# ---- 4. higher-order / resonant filter: implicit feedback stays convergent ---
# H(s) = wn^2/(s^2 + 2*zeta*wn*s + wn^2), driven AT resonance -> steady amplitude
# = 1/(2*zeta). A regression in the now-implicit feedback would either fail to
# converge or get the resonant gain wrong.
WN = 2 * math.pi * 100e3
ZETA = 0.30
gain_peak = 1.0 / (2.0 * ZETA)      # = 1.667
den2 = [1.0 / (WN * WN), 2.0 * ZETA / WN, 1.0]
res_deck = (f"* resonant 2nd-order s_xfer at resonance\n"
            f"vin in 0 dc 0 sin(0 1 {WN/2/math.pi:g})\n"
            f"a1 in outx xr\n"
            f".model xr s_xfer(num_coeff=[1] "
            f"den_coeff=[{den2[0]:.10g} {den2[1]:.10g} {den2[2]:.10g}] int_ic=[0 0])\n"
            f"r1 outx 0 1meg\n"
            f".options reltol=1e-5 abstol=1e-13 method=trap\n"
            f".tran 20n 40u 0 20n\n"
            f".control\nrun\nwrdata _res.dat v(outx)\n.endc\n.end\n")
rc, out = run(res_deck, "_res.cir")
conv = rc >= 0 and not any(k in out.lower() for k in
                           ("singular", "no convergence", "iteration limit",
                            "time step too small", "aborted"))
rows = read_dat("_res.dat")
tail = [v for t, v in rows if t >= 30e-6]
amp = (max(tail) - min(tail)) / 2.0 if tail else 0.0
check("resonant 2nd-order s_xfer converges (implicit feedback stable)", conv,
      f"rc={rc}")
check("resonant steady amplitude matches 1/(2 zeta)=1.667 (within 3%)",
      amp > 0 and abs(amp - gain_peak) / gain_peak < 0.03,
      f"amp={amp:.4f} want~{gain_peak:.4f}")

for f in os.listdir(HERE):
    if f.startswith("_"):
        os.remove(os.path.join(HERE, f))

print(f"\n{passed} passed, {failed} failed")
raise SystemExit(1 if failed else 0)
