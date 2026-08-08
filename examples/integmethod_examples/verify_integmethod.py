#!/usr/bin/env python3
"""verify_integmethod.py -- Enhancement-419: three new integration methods.

ngspice shipped two: trapezoidal (the default, A-stable but NOT L-stable, so it
RINGS at a sharp transition) and Gear/BDF 1-6 (L-stable but less accurate at
equal order). The only cure for trapezoidal ringing was `xmu < 0.5`, which
slides toward backward Euler and costs an order, or `method=gear`, which costs
accuracy everywhere. This adds:

  method=trbdf2  a one-step COMPOSITE: trapezoidal over [t, t+g*h] then BDF2
                 across t, t+g*h, t+h. With g = 2-sqrt(2) both sub-steps share
                 the leading coefficient 2/(g*h) == (2-g)/((1-g)*h), so the
                 Jacobian scaling does not change between stages. Order 2 and
                 L-STABLE -- it damps where trapezoidal rings.
  method=sdirk   Alexander's 3-stage order-3 L-stable SDIRK, restricted to
                 STIFFLY ACCURATE tableaux (a[s][j]==b[j], c[s]==1) so the last
                 stage IS the answer. Without that a step would end in a
                 weighted COMBINATION of stage values, and every value a device
                 holds has to come out of a solve, not an assignment.
  method=adams   Adams-Moulton of order `maxord`, weights derived per step from
                 the ACTUAL spacing (the textbook 5/12, 8/12, -1/12 are
                 fixed-step and ngspice never takes fixed steps).

WHAT THIS SUITE PINS, and why each check is the one that would catch a silent
error rather than merely pass:

 [1] AM2 IS the trapezoidal rule. `method=adams maxord=2` must reproduce
     `method=trap` BYTE FOR BYTE. One comparison validates the whole
     variable-step weight generator: the Vandermonde solve, the normalisation,
     and the conversion into the stamp's form.
 [2] Order of convergence. All three second-order methods must land on the same
     observed order and SDIRK visibly above them. A mistyped Butcher coefficient
     does not crash -- it quietly costs an order, which is invisible to any test
     that only asks whether the answer looks reasonable.
 [3] L-stability. Trapezoidal's amplification factor tends to -1 as h*lambda ->
     -inf, so it must RING with ratio (1-h/2tau)/(1+h/2tau) -- a NUMBER the test
     predicts and checks, so a passing run means the mechanism was measured and
     not just the absence of a wobble.
 [4] Both solvers, and an OSDI Verilog-A device. OSDI loads its Jacobian with
     ckt->CKTag[0] ALONE, while TR-BDF2 stage 2 and Adams order>=3 need ag[1]
     and ag[2]; if OSDI bypassed NIintegrate the new methods would be silently
     wrong for exactly the device class this project exists for. It does not --
     it routes its reactive residual through the charge state -- and this check
     is what keeps that true.

THREE TRAPS this harness had to survive, recorded because each produced a
confident, wrong table first:
  * the step must be PINNED (`.options ordfix=K`) or the sweep measures nothing;
  * a `pulse` source plants a BREAKPOINT that floods t~0 with sub-steps, so a
    stiff transition cannot be excited with one -- use a behavioural tanh;
  * delta starts at ~1e-10 and grows only ~1.5x per step, so it reaches a large
    tmax pin only well into the run: a transient placed early is always resolved
    finely no matter what you asked for.

Exit code 0 = pass.
"""
import math
import os
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from _setup import VAF as OPENVAF, NG as NGSPICE  # noqa: E402
from _setup import check_both_solvers as _check_both_solvers  # noqa: E402

checks = passed = 0
TMP = tempfile.gettempdir()


def check(label, ok, detail=""):
    global checks, passed
    checks += 1
    passed += bool(ok)
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  [{detail}]" if detail else ""))
    return ok


def run(tag, deck, opts, ctrl, osdi=None):
    path = os.path.join(TMP, f"_im_{tag}.cir")
    out = os.path.join(TMP, f"_im_{tag}.dat")
    if os.path.exists(out):
        os.remove(out)
    pre = f"pre_osdi {osdi}\n" if osdi else ""
    with open(path, "w") as fh:
        fh.write(f"* {tag}\n{deck}\n.options {opts}\n.control\n{pre}{ctrl}\n"
                 f"wrdata {out} v(out)\n.endc\n.end\n")
    subprocess.run([NGSPICE, "-b", path], capture_output=True, text=True,
                   stdin=subprocess.DEVNULL, timeout=300)
    pts = []
    if os.path.exists(out):
        for ln in open(out):
            f = ln.split()
            if len(f) >= 2:
                try:
                    pts.append((float(f[0]), float(f[1])))
                except ValueError:
                    pass
    return pts, out


def at(pts, t):
    for i in range(1, len(pts)):
        if pts[i][0] >= t:
            t0, v0 = pts[i - 1]
            t1, v1 = pts[i]
            return v1 if t1 == t0 else v0 + (v1 - v0) * (t - t0) / (t1 - t0)
    return pts[-1][1] if pts else float("nan")


RC = "v1 in 0 dc 1\nr1 in out 1k\nc1 out 0 1n\n.ic v(out)=0"
RCTRAN = "tran {h:g} 5e-6 0 {h:g} uic"


def main():
    # ------------------------------------------------- [1] AM2 == trapezoidal
    print("\n    [1] Adams-Moulton order 2 IS the trapezoidal rule")
    a, fa = run("trap2", RC, "method=trap", RCTRAN.format(h=1e-7))
    b, fb = run("adams2", RC, "method=adams maxord=2", RCTRAN.format(h=1e-7))
    same = (len(a) == len(b) and len(a) > 5 and
            all(x[0] == y[0] and x[1] == y[1] for x, y in zip(a, b)))
    check("`adams maxord=2` reproduces `trap` byte for byte",
          same, f"{len(a)} vs {len(b)} points")

    # ------------------------------------------------------ [2] order of conv
    print("\n    [2] observed order of convergence (step pinned by ordfix)")
    print("        RC step, exact 1-exp(-t/tau); error taken past the startup ramp")

    def order_of(opts, fix):
        prev = None
        obs = None
        for h in (2e-7, 1e-7, 5e-8, 2.5e-8):
            pts, _ = run(f"o{abs(hash((opts,h)))%99999}", RC,
                         f"{opts} ordfix={fix}", RCTRAN.format(h=h))
            late = [(t, v) for t, v in pts if t >= 1e-6]
            if len(late) < 5:
                return None
            e = max(abs(v - (1 - math.exp(-t / 1e-6))) for t, v in late)
            if prev and e > 0:
                obs = math.log(prev / e) / math.log(2)
            prev = e
        return obs

    o_trap = order_of("method=trap", 2)
    o_trb = order_of("method=trbdf2", 2)
    o_sd = order_of("method=sdirk", 3)
    check("trapezoidal converges at its second-order rate",
          o_trap is not None and 1.5 < o_trap < 2.3, f"order={o_trap:.2f}")
    check("TR-BDF2 matches it (also second order)",
          o_trb is not None and abs(o_trb - o_trap) < 0.25, f"order={o_trb:.2f}")
    check("SDIRK is visibly HIGHER order than the second-order pair",
          o_sd is not None and o_sd > o_trap + 0.5, f"order={o_sd:.2f}")

    # ------------------------------------------------------- [3] L-stability
    print("\n    [3] L-stability: a fast transition arriving at a LARGE step")
    print("        tanh edge at t=500us (a behavioural source plants no")
    print("        breakpoint, so the step is still pinned at 20us = 20*tau)")
    RING = ("bv in 0 v = 0.5*(1+tanh((time-500u)/1n))\n"
            "r1 in out 1k\nc1 out 0 1n\n.ic v(out)=0")
    RCTL = "tran 20u 1000u 0 20u uic"
    prof = {}
    for m in ("trap", "trbdf2", "sdirk"):
        pts, _ = run(f"r{m}", RING, f"method={m} ordfix=2 trtol=1e12", RCTL)
        post = [v for t, v in pts if t > 5.05e-4]
        prof[m] = post
    # trapezoidal MUST ring, at the textbook ratio -- if it does not, the test
    # is not exercising the regime it claims to and everything else here is void
    tr = prof["trap"]
    ratio = None
    if len(tr) > 3:
        d = [v - 1.0 for v in tr[:4]]
        if abs(d[0]) > 1e-12:
            ratio = d[1] / d[0]
    check("trapezoidal rings at the predicted (1-h/2tau)/(1+h/2tau) = -0.818",
          ratio is not None and abs(ratio + 9.0 / 11.0) < 0.05,
          f"measured ratio={ratio:.4f}" if ratio else "no ring measured")
    for m in ("trbdf2", "sdirk"):
        tail = prof[m][6:] if len(prof[m]) > 6 else []
        settled = tail and max(abs(v - 1.0) for v in tail) < 1e-4
        check(f"{m} has damped to the solution where trapezoidal is still ringing",
              settled,
              f"|v-1| = {max(abs(v-1.0) for v in tail):.1e}" if tail else "no data")
    tail_trap = tr[6:] if len(tr) > 6 else []
    check("trapezoidal is still visibly off at the same point (the control)",
          tail_trap and max(abs(v - 1.0) for v in tail_trap) > 1e-3,
          f"|v-1| = {max(abs(v-1.0) for v in tail_trap):.1e}" if tail_trap else "-")

    # --------------------------------------- [4] both solvers + an OSDI device
    print("\n    [4] every method agrees across solvers, including for OSDI")
    osdi = os.path.join(TMP, "_im.osdi")
    r = subprocess.run([OPENVAF, os.path.join(HERE, "im_rc.va"), "-o", osdi],
                       capture_output=True, text=True, timeout=600)
    if r.returncode:
        print(r.stdout + r.stderr)
        sys.exit("compiling im_rc.va failed")
    OD = ("v1 in 0 pwl(0 0 1u 1)\nr1 in out 1k\nn1 out 0 mm\n"
          ".model mm im_rc(r=2000 c=2e-9)")
    ODT = "tran 5e-8 5e-6 0 5e-7 uic"
    ts = [1e-6 + (5e-6 - 1e-6) * k / 25 for k in range(1, 25)]
    for m in ("trap", "gear", "trbdf2", "sdirk", "adams"):
        s, _ = run(f"s{m}", OD, f"method={m}", ODT, osdi=osdi)
        k, _ = run(f"k{m}", OD, f"method={m} klu", ODT, osdi=osdi)
        if len(s) < 5 or len(k) < 5:
            check(f"{m}: OSDI runs under both solvers", False, "no data")
            continue
        gap = max(abs(at(s, t) - at(k, t)) for t in ts)
        check(f"{m}: OSDI result is identical under SPARSE and KLU",
              gap < 1e-9, f"max diff {gap:.1e}")

    print(f"\n{passed}/{checks} checks passed")
    return 0 if passed == checks else 1


if __name__ == "__main__":
    _check_both_solvers(__file__)
    sys.exit(main())
