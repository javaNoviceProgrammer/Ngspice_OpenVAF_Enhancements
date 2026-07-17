#!/usr/bin/env python3
"""
verify_pareto.py -- Enhancement-216: NSGA-II multi-objective / Pareto optimization.

`optimize -method nsga2` trades competing objectives and returns a Pareto FRONT of
non-dominated designs (rather than the single optimum the scalar methods -- E-130
Nelder-Mead, E-194 PSO, E-195 DE, E-196 SA -- return). It is the multi-objective
generalization of E-206 design centering.

`pareto_demo.cir` is the Schaffer-1 benchmark: over a knob px in [-1, 3], minimize
f1 = px^2 and f2 = (px-2)^2 at once. These conflict, so the answer is not a point
but a curve -- the Pareto set is exactly px in [0, 2], and in objective space the
front is f2 = (sqrt(f1) - 2)^2. NSGA-II must discover that [0, 2] sub-range and
spread points along the trade-off.

Checks (parsing the printed front):
  1. the run produces a front of a reasonable number of points;
  2. every point is genuinely NON-DOMINATED (no point beats another on both
     objectives);
  3. every point lies on the ANALYTIC front to machine precision
     (f1 == px^2, f2 == (px-2)^2, and f2 == (sqrt(f1)-2)^2);
  4. the front SPANS the trade-off -- px reaches near 0 (min-f1 end) and near 2
     (min-f2 end).

Every SPICE deck starts with a title line (SPICE treats line 1 as the title!).
"""
import math
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))          # the examples/ dir (holds _setup.py)
from _setup import NG as NGSPICE
from _setup import check_both_solvers as _check_both_solvers; _check_both_solvers(__file__)  # both solvers

checks = passed = 0


def check(label, ok, detail=""):
    global checks, passed
    checks += 1
    passed += bool(ok)
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"   [{detail}]" if detail else ""))


def run_front():
    """Run the deck; return (front, fronterr) where front is the printed
    [(f1, f2, px), ...] and fronterr is the full-precision max deviation of the
    published pareto1/pareto2 vectors from the analytic curve."""
    out = subprocess.run([NGSPICE, "-b", "pareto_demo.cir"], cwd=HERE,
                         capture_output=True, text=True, timeout=300).stdout
    front, in_front = [], False
    for line in out.splitlines():
        if "Pareto front" in line:
            in_front = True
            continue
        if in_front:
            # data rows look like:  <f1> <f2> | <px>
            m = re.match(r"\s+([-\d.eE+]+)\s+([-\d.eE+]+)\s+\|\s+([-\d.eE+]+)\s*$", line)
            if m:
                front.append(tuple(float(x) for x in m.groups()))
            elif front:            # a non-data line after the front ends the block
                in_front = False
    m = re.search(r"fronterr\s*=\s*([-\d.eE+]+)", out)
    fronterr = float(m.group(1)) if m else None
    return front, fronterr


def main():
    front, fronterr = run_front()
    print(f"[1] NSGA-II returns a Pareto front ({len(front)} points)")
    check("front has a reasonable number of non-dominated points",
          len(front) >= 8, f"{len(front)} points")
    if len(front) < 3:
        print("\nSOME FAILED")
        sys.exit(1)

    print("[2] every point is genuinely non-dominated")
    dominated = 0
    for a in front:
        for b in front:
            if a is b:
                continue
            # b dominates a if b<=a on both objectives and b<a on at least one
            if b[0] <= a[0] and b[1] <= a[1] and (b[0] < a[0] or b[1] < a[1]):
                dominated += 1
                break
    check("no point is dominated by another", dominated == 0,
          f"{dominated} dominated")

    print("[3] every point lies on the analytic front")
    # full-precision: the published vectors vs the analytic curve (computed in the
    # deck, so it is not limited by the 6-sig-fig printed front)
    check("published front == (sqrt(f1)-2)^2 to machine precision",
          fronterr is not None and fronterr < 1e-9,
          f"max deviation {fronterr:.2e}" if fronterr is not None else "no fronterr")
    # printed front: f1==px^2 and f2==(px-2)^2 at display precision (~6 sig figs)
    worst = 0.0
    for f1, f2, px in front:
        rel = max(abs(f1 - px * px), abs(f2 - (px - 2) ** 2)) / (1.0 + abs(f2))
        worst = max(worst, rel)
    check("printed f1==px^2, f2==(px-2)^2 (6 sig figs)", worst < 1e-4,
          f"worst relative deviation {worst:.2e}")

    print("[4] the front spans the trade-off (px from ~0 to ~2)")
    pxs = [p[2] for p in front]
    check("min-f1 end reaches px ~ 0", min(pxs) < 0.1, f"px_min = {min(pxs):.4g}")
    check("min-f2 end reaches px ~ 2", max(pxs) > 1.9, f"px_max = {max(pxs):.4g}")

    print(f"\n{passed}/{checks} checks passed")
    print("ALL PASS" if passed == checks else "SOME FAILED")
    sys.exit(0 if passed == checks else 1)


if __name__ == "__main__":
    main()
