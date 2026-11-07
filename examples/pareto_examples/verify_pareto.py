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
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))          # the examples/ dir (holds _setup.py)
from _setup import NG as NGSPICE, VAF as OPENVAF
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


# Enhancement-918: designs that did not solve, or cannot be read. The output of
# `out` flips against v(x), so there is no solution for 0 < Vx < 1.
NO_SOLUTION = """* no solution for 0 < vx < 1
Vx x 0 2
B1 y 0 V = v(out) > v(x) ? 0 : 1
R1 y out 1
R2 out 0 1meg
.control
optimize -param Vx 2 -1 3 -analysis op {objectives} -method nsga2 -maxiter 6 -swarmsize 12 -seed 1
echo status $optimize_status
quit
.endc
.end
"""
# log of a negative: the first objective cannot be read for R1 > 1.5k.
UNREADABLE = """* an objective that cannot be read for r1 above 1.5k
V1 in 0 1
R1 in out 1k
R2 out 0 1k
.control
optimize -param R1 1k 100 10k -analysis op {objectives} -method nsga2 -maxiter 8 -swarmsize 16 -seed 1
echo status $optimize_status
quit
.endc
.end
"""


# Its conductance is refused at g <= 0.
REFUSED = """* a conductance the model refuses at or below 0
.control
pre_osdi OSDI
.endc
V1 in 0 1
R1 in out 1k
N1 out 0 gm
.model gm optguard
.control
optimize -param @n1[g] 1m -2m 5m -analysis op {objectives} -method nsga2 -maxiter 5 -swarmsize 8 -seed 1
quit
.endc
.end
"""


def run_deck(deck, objectives):
    """(front rows [(f1, f2, knob)], the whole output) of a deck."""
    with tempfile.TemporaryDirectory() as folder:
        path = os.path.join(folder, "deck.cir")
        with open(path, "w") as f:
            f.write(deck.format(objectives=objectives))
        r = subprocess.run([NGSPICE, "-b", path], cwd=folder, capture_output=True, text=True, timeout=300)
    out = r.stdout + r.stderr
    rows = []
    for line in out.splitlines():
        m = re.match(r"^\s*(\S+)\s+(\S+)\s+\|\s+(\S+)\s*$", line)
        if m:
            try:
                rows.append(tuple(float(g) for g in m.groups()))
            except ValueError:
                pass
    return rows, out


def failed_designs():
    # The same objectives written as a maximum and as a minimum: no failure may
    # be on either front, and the two fronts' designs come from one search.
    for name, objectives in (("-maximize", "-maximize v(x) -minimize v(x)+v(out)"),
                             ("-minimize", "-minimize 0-v(x) -minimize v(x)+v(out)")):
        rows, out = run_deck(NO_SOLUTION, objectives)
        check(f"no solution, {name}: a front", len(rows) >= 4, f"{len(rows)} rows")
        check(f"no solution, {name}: none in the range with no solution",
              not [r for r in rows if 0 < r[2] < 1], f"{[r[2] for r in rows if 0 < r[2] < 1]}")
        check(f"no solution, {name}: nothing reads as a failure",
              not [r for r in rows if abs(r[0]) >= 1e15 or abs(r[1]) >= 1e15])
        check(f"no solution, {name}: the failed solves are said", "did not solve" in out)
        check(f"no solution, {name}: status completed", "status completed" in out)
    # An objective that cannot be read, the other fine and best just there: not
    # on the front under -minimize either.
    for name, objectives in (("-maximize", "-maximize log(v(out)-0.4) -minimize abs(i(v1))"),
                             ("-minimize", "-minimize 0-log(v(out)-0.4) -minimize abs(i(v1))")):
        rows, out = run_deck(UNREADABLE, objectives)
        check(f"unreadable, {name}: a front", len(rows) >= 4, f"{len(rows)} rows")
        check(f"unreadable, {name}: every design can be read (R1 <= 1.5k)",
              rows and max(r[2] for r in rows) <= 1500.5, f"largest {max([r[2] for r in rows], default=0):g}")
    # The two signs of the same objective give the same front.
    up, _ = run_deck(UNREADABLE, "-maximize log(v(out)-0.4) -minimize abs(i(v1))")
    down, _ = run_deck(UNREADABLE, "-minimize 0-log(v(out)-0.4) -minimize abs(i(v1))")
    same = len(up) == len(down) and all(abs(a[2] - b[2]) <= 1e-3 * abs(b[2]) for a, b in zip(sorted(up, key=lambda r: r[2]), sorted(down, key=lambda r: r[2])))
    check("a maximum and a minimum of its negative: one front", same, f"{len(up)} and {len(down)} rows")
    # A value the model refuses: the analysis fails and leaves the plot of the last
    # design standing, so its objectives read as that design's (F5 of the
    # 2026-09-29 hunt; a compiled model, for the refusal).
    with tempfile.TemporaryDirectory() as folder:
        va = os.path.join(os.path.dirname(HERE), "optmethods_examples", "optguard.va")
        built = subprocess.run([OPENVAF, va, "-o", os.path.join(folder, "optguard.osdi")],
                               capture_output=True, text=True, timeout=300)
        check("refused: the model compiles", built.returncode == 0, built.stderr[:200])
        rows, out = run_deck(REFUSED.replace("OSDI", os.path.join(folder, "optguard.osdi")),
                             "-minimize (v(out)-0.5)^2 -maximize v(out)")
    check("refused: a front", len(rows) >= 2, f"{len(rows)} rows")
    check("refused: no design the model refuses (g < 0)", not [r for r in rows if r[2] <= 0],
          f"{[r[2] for r in rows if r[2] <= 0]}")
    check("refused: the failed solves are said", "did not solve" in out)
    # Every design failing: no front, said, and nothing published to read wrongly.
    rows, out = run_deck(UNREADABLE, "-maximize log(v(out)-2) -minimize abs(i(v1))")
    check("nothing readable: no front", not rows and "0 non-dominated designs" in out, f"{len(rows)} rows")
    check("nothing readable: status nosolve", "status nosolve" in out)
    # Only maxima.
    rows, out = run_deck(UNREADABLE, "-maximize v(out) -maximize 1-v(out)")
    check("only -maximize: not refused", "usage:" not in out and "Pareto front" in out)
    check("only -maximize: a front at the printed sign",
          len(rows) >= 4 and all(abs(r[0] + r[1] - 1) < 1e-4 for r in rows), f"{len(rows)} rows")
    # One -maximize with a scalar method is still no objective for it.
    _, out = run_deck(UNREADABLE.replace("-method nsga2 ", ""), "-maximize v(out)")
    check("one -maximize, no nsga2: still refused", "usage:" in out)


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

    print("[5] designs that failed are no part of a front (E-918)")
    failed_designs()

    print(f"\n{passed}/{checks} checks passed")
    print("ALL PASS" if passed == checks else "SOME FAILED")
    sys.exit(0 if passed == checks else 1)


if __name__ == "__main__":
    main()
