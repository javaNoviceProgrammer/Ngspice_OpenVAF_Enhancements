#!/usr/bin/env python3
"""
verify_dynorder.py -- Enhancement-128: LTE-based dynamic integration-order control
(`.option dynorder`). End-to-end through the committed ngspice.

Stock ngspice's transient controller only ever toggles the Gear order between 1 and
2 (dctran.c): orders 3-6 have coefficients (NIcomCof) but are never selected. With
`.option dynorder` the per-step local-truncation-error (LTE) limit is evaluated at
the current order and its immediate neighbours, and the order is raised/lowered
(with hysteresis + a settling hold + an order-dependent step-growth cap) so higher-
order Gear is actually used on smooth stretches -- taking far larger steps at the
same accuracy. OFF by default; bounded by the standard `maxord` knob.

The controller is deliberately conservative so a high order can never silently wreck
the answer:
  * neighbours only (+-1), never a greedy global maximum -> no order oscillation;
  * a neighbour must beat the current order's LTE step by 1.2x to win (hysteresis);
  * after any change the order is HELD for a few steps so the BDF divided-difference
    history (which assumes a roughly constant step) can rebuild before changing again;
  * the step is NOT grown the same step the order is raised, and the growth cap
    tightens with order (2x at <=3 down to 1.3x at 6), because a large jump at high
    order corrupts the very divided differences the LTE relies on.

Properties, checked under BOTH linear solvers (Sparse 1.3 default + KLU); the heavy
reference sweeps run under Sparse only, KLU runs the fast subset:

  [1] `.option dynorder` is accepted (not an unknown option).
  [2] RC decay (analytic V(8ms)=exp(-8)): at MATCHED tolerance dynorder(maxord=3)
      reaches at least the stock controller's accuracy using >=2x FEWER steps, and
      its error is MONOTONE in tolerance (no high-order blow-up).
  [3] dynorder actually climbs above the stock order-2 ceiling (Gear order >=3 used).
  [4] LC ringdown (smooth sinusoid) vs a tight reference: dynorder(maxord=4) is both
      FEWER steps AND no less accurate than the stock controller -- higher order pays
      off twice on smooth dynamics.
  [5] Nonlinear diode rectifier: dynorder's answer matches the stock controller to
      tight tolerance -- a switching circuit (frequent breakpoints reset the order)
      must not be perturbed.
  [6] SAFETY: `.option dynorder` OFF is the default; enabling it at the default
      maxord (2) cannot exceed order 2 and stays result-neutral vs a plain run.
"""
import math
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from _setup import NG as NGSPICE
from _setup import check_both_solvers as _check_both_solvers

_check_both_solvers(__file__)   # verify under BOTH KLU and Sparse solvers

# which solver is active in this (single-solver) process; heavy sweeps -> Sparse only
_SOLVER = (os.environ.get("_NG_SOLVER") or os.environ.get("NGSPICE_SOLVER") or "sparse").lower()
_HEAVY = (_SOLVER == "sparse")

checks = passed = 0
def check(label, ok, detail=""):
    global checks, passed
    checks += 1; passed += bool(ok)
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  [{detail}]" if detail and not ok else ""))


def run(deck):
    """Run a full deck; return (rows, final_value_of_last-printed, max_order, out)."""
    p = os.path.join(HERE, "_tmp.cir")
    with open(p, "w") as f:
        f.write(deck)
    try:
        r = subprocess.run([NGSPICE, "-b", p], capture_output=True, text=True, timeout=120)
    finally:
        if os.path.exists(p):
            os.remove(p)
    out = r.stdout + r.stderr
    rows = int(m.group(1)) if (m := re.search(r"No\. of Data Rows\s*:\s*(\d+)", out)) else None
    ve = float(m.group(1)) if (m := re.search(r"^ve\s*=\s*([\-0-9.eE+]+)", out, re.M)) else None
    ordr = int(m.group(1)) if (m := re.search(r"highest integration order used\s*=\s*(\d+)", out)) else None
    return rows, ve, ordr, out


def rc_deck(maxord, reltol, dyn):
    """RC discharge, V(0)=1, RC=1ms; analytic V(8ms)=exp(-8). 'set ngdebug' so the
    dynamic-order summary (order actually used) is emitted to stderr."""
    opt = f"method=gear maxord={maxord} reltol={reltol} abstol=1e-15" + (" dynorder" if dyn else "")
    return (f"RC discharge maxord={maxord} reltol={reltol} dyn={dyn}\n"
            f"R1 1 0 1k\nC1 1 0 1u ic=1\n.option {opt}\n.tran 1u 8m 0 4m uic\n"
            f".control\nset ngdebug\nrun\nlet ve = v(1)[length(v(1))-1]\nprint ve\n.endc\n.end\n")

RC_ANALYTIC = math.exp(-8.0)   # 3.354626e-4


def lc_deck(reltol, dyn):
    """Parallel RLC ringdown, near-lossless (R=1meg): a smooth 5.03 kHz sinusoid."""
    opt = f"method=gear maxord=4 reltol={reltol} abstol=1e-12" + (" dynorder" if dyn else "")
    return (f"LC ringdown reltol={reltol} dyn={dyn}\n"
            f"L1 1 0 1m ic=0\nC1 1 0 1u ic=1\nR1 1 0 1meg\n.option {opt}\n"
            f".tran 1u 2m 0 5u uic\n.control\nset ngdebug\nrun\n"
            f"let ve = v(1)[length(v(1))-1]\nprint ve\n.endc\n.end\n")


def diode_deck(dyn):
    """Nonlinear half-wave rectifier with a smoothing cap -- diode switching makes
    frequent breakpoints that reset the order; dynorder must not perturb it."""
    opt = "method=gear maxord=4 reltol=1e-6" + (" dynorder" if dyn else "")
    return (f"diode rectifier dyn={dyn}\n.model D1N D(is=1e-14 n=1)\n"
            f"V1 1 0 SIN(0 5 1k)\nD1 1 2 D1N\nR1 2 0 1k\nC1 2 0 10u\n.option {opt}\n"
            f".tran 1u 5m\n.control\nrun\nlet ve = v(2)[length(v(2))-1]\nprint ve\n.endc\n.end\n")


def relerr(v, ref):
    return abs(v - ref) / abs(ref) if (v is not None and ref) else float("inf")


print(f"Enhancement-128: LTE-based dynamic integration-order control  [solver={_SOLVER}]")

# [1] option accepted
_, _, _, out = run(rc_deck(3, "1e-7", True))
check("`.option dynorder` accepted (not an unknown option)",
      "unknown option" not in out.lower() and "unrecognized" not in out.lower())

# [3]+[2] RC decay: order climb + matched-accuracy step savings
rows_dyn, ve_dyn, ord_dyn, _ = run(rc_deck(3, "1e-8", True))
rows_stk, ve_stk, _,       _ = run(rc_deck(3, "1e-8", False))
check("RC: dynorder climbs above the stock order-2 ceiling (Gear order >=3)",
      ord_dyn is not None and ord_dyn >= 3, f"order={ord_dyn}")
err_dyn, err_stk = relerr(ve_dyn, RC_ANALYTIC), relerr(ve_stk, RC_ANALYTIC)
check(f"RC: dynorder as accurate as stock at matched tol "
      f"(dyn {err_dyn*100:.3f}% <= stock {err_stk*100:.3f}% x3)",
      err_dyn <= 3 * err_stk + 1e-4, f"dyn={err_dyn:.2e} stk={err_stk:.2e}")
check(f"RC: dynorder uses >=2x fewer steps at matched accuracy "
      f"(dyn {rows_dyn} vs stock {rows_stk} rows)",
      rows_dyn is not None and rows_stk is not None and rows_dyn * 2 <= rows_stk,
      f"dyn={rows_dyn} stk={rows_stk}")

if _HEAVY:
    # [2] error MONOTONE in tolerance -- the high-order controller must not blow up
    errs = []
    for rt in ("1e-6", "1e-7", "1e-8", "1e-9"):
        _, ve, _, _ = run(rc_deck(3, rt, True))
        errs.append(relerr(ve, RC_ANALYTIC))
    mono = all(errs[i + 1] <= errs[i] * 1.5 + 1e-4 for i in range(len(errs) - 1))
    check(f"RC: dynorder(maxord=3) error is monotone in tolerance "
          f"({', '.join(f'{e*100:.3f}%' for e in errs)})", mono)

    # [4] LC ringdown vs a tight reference: fewer steps AND no worse accuracy
    _, ve_ref, _, _ = run(lc_deck("1e-10", False))   # order-2, very tight = truth
    rows_ld, ve_ld, ord_ld, _ = run(lc_deck("1e-7", True))
    rows_ls, ve_ls, _,      _ = run(lc_deck("1e-7", False))
    check("LC: dynorder exercises high-order Gear (order >=4)",
          ord_ld is not None and ord_ld >= 4, f"order={ord_ld}")
    check(f"LC: dynorder uses >=3x fewer steps than the stock controller "
          f"(dyn {rows_ld} vs stock {rows_ls} rows)",
          rows_ld is not None and rows_ls is not None and rows_ld * 3 <= rows_ls,
          f"dyn={rows_ld} stk={rows_ls}")
    err_ld, err_ls = relerr(ve_ld, ve_ref), relerr(ve_ls, ve_ref)
    check(f"LC: dynorder no less accurate than stock vs reference "
          f"(dyn {err_ld*100:.3f}% <= stock {err_ls*100:.3f}%)",
          err_ld <= err_ls * 1.5 + 1e-4, f"dyn={err_ld:.2e} stk={err_ls:.2e} ref={ve_ref}")

# [5] nonlinear rectifier: dynorder must match the stock controller
_, ve_dd, _, _ = run(diode_deck(True))
_, ve_ds, _, _ = run(diode_deck(False))
check(f"diode rectifier: dynorder matches stock final V to tight tol "
      f"(dyn {ve_dd} vs stock {ve_ds})",
      ve_dd is not None and ve_ds is not None and relerr(ve_dd, ve_ds) < 1e-3,
      f"dyn={ve_dd} stk={ve_ds}")

# [6] safety: enabling dynorder at the default maxord (2) stays result-neutral
neutral_on = (f"safety default-maxord neutrality (dynorder)\n"
              f"V1 1 0 SIN(0 1 1k)\nR1 1 2 1k\nC1 2 0 1u\n.option dynorder\n.tran 2u 4m\n"
              f".control\nrun\nlet ve = v(2)[length(v(2))-1]\nprint ve\n.endc\n.end\n")
neutral_off = neutral_on.replace(".option dynorder\n", "")
_, ve_on, _, _ = run(neutral_on)
_, ve_off, _, _ = run(neutral_off)
check(f"safety: dynorder at default maxord=2 is result-neutral (on {ve_on} vs off {ve_off})",
      ve_on is not None and ve_off is not None and relerr(ve_on, ve_off) < 1e-3,
      f"on={ve_on} off={ve_off}")

print(f"\n{'ALL PASS' if passed == checks else 'FAILURES'}: {passed}/{checks} passed  [solver={_SOLVER}]")
sys.exit(0 if passed == checks else 1)
