#!/usr/bin/env python3
"""Sparse 1.3 vs KLU differential campaign -- 37 checks on circuits where the
linear solve is actually hard.

DELIBERATELY NOT PART OF THE REGRESSION SUITE. `run_regression.py` discovers
`examples/*_examples/verify_*.py`; this driver is named `run_solverdiff.py` so
the routine sweep never picks it up. Run it by hand:

    python3 run_solverdiff.py            # both phases
    python3 run_solverdiff.py 1          # only phase 1

WHY IT EXISTS. Other suites run both solvers and require them to agree, but on
small well-conditioned circuits -- where agreement proves very little. This one
targets ILL-CONDITIONED and STIFF circuits: the regime where Sparse re-pivots
(measured at ~12-15 forced reorders per Monte Carlo sample) and where KLU behaves
differently because its symbolic ordering is computed once.

THE METHOD, which is the point. A solver-vs-solver diff says they DIFFER; it
cannot say which is WRONG. So:

  * PHASE 1 (linear) -- the nodal system IS the MNA matrix, so numpy solves the
    same system independently and becomes the third opinion. Every deck reports
    its CONDITION NUMBER, and the tolerance is eps*cond: a disagreement is read
    against how hard the problem actually is, not guessed at. Decks whose cond
    exceeds what float64 can deliver are REPORTED, never asserted -- a tolerance
    that grows without limit is a rubber stamp, not a test.
  * PHASE 2 (nonlinear/stiff) -- no closed form for most, so the references are
    solver-vs-solver at tight tolerance, a TIGHTENED-reltol run (which separates
    a linear-solve difference from mere convergence slack), and closed form for
    the single diode.

RESULT WHEN LAST RUN (2026-07-27): 37/37, no solver defect. Worst
Sparse-vs-KLU disagreement anywhere was 7.06e-06, on cond 2.4e12 where eps*cond
is 5e-4 -- comfortably inside what float64 permits. Both solvers track the exact
solution IN STEP with conditioning and TRADE PLACES (Sparse better on
ladder_ratio, KLU better on star(9)), so neither shows systematic bias.

HARNESS TRAPS -- every one of these produced a false green or a false red before
being caught, and they are why this file is written the way it is:

  1. The first version reported 25/25 and meant NOTHING: `star` had cond = 1.0
     (the hub was the only unknown, a 1x1 matrix) and `tol = 5e-16*cond`
     ballooned to 1.3e+03, auto-passing anything.
  2. Normalising error by max|exact| ACROSS nodes hides a large relative error on
     a small node. Use per-node relative error with an absolute floor.
  3. A crude `eps*span` bound UNDERESTIMATED true cond by ~450x, because diode
     small-signal conductance dominates the matrix. Compute cond of the
     LINEARISED system at the operating point instead.
  4. The closed-form diode oracle needs ngspice's OWN thermal voltage,
     0.0258649170072 (measured from its I-V curve; the OSDI campaign found the
     same value to 12 digits) -- not CONSTboltz/CHARGE, which is 0.24 ppm away
     and shows up as a 7.6e-4 current error.
  5. `pz` prints a COMPLEX pair `re,im`; a regex requiring end-of-line after the
     first number silently yields "no result". Also `pz` does not converge on a
     120-node ladder -- identically on BOTH solvers, so that is a pz scale limit,
     not a differential finding.
"""
import math
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from _setup import NG as NGSPICE  # noqa: E402

try:
    import numpy as np
except ImportError:                                     # pragma: no cover
    np = None

# ngspice's built-in diode uses its own thermal-voltage constant (trap 4)
VT = 0.0258649170072
results = []


def rec(label, ok, detail=""):
    results.append((label, bool(ok)))
    print("  %-50s %s  %s" % (label, "PASS" if ok else "FAIL", detail))


def run(name, deck, solver, timeout=900):
    opt = ".option klu\n" if solver == "klu" else ""
    p = os.path.join(HERE, "_%s_%s.cir" % (re.sub(r"\W+", "_", name), solver))
    with open(p, "w") as f:
        f.write("solverdiff %s\n%s%s" % (name, opt, deck))
    try:
        r = subprocess.run([NGSPICE, "-b", os.path.basename(p)], cwd=HERE,
                           capture_output=True, text=True, timeout=timeout,
                           errors="replace")
    except subprocess.TimeoutExpired:
        return None
    finally:
        if os.path.exists(p):
            os.remove(p)
    return r.stdout + r.stderr


def values(out):
    """floats from `tag = value` lines; a COMPLEX result is `re,im` (trap 5)"""
    if out is None:
        return None
    vals = []
    for m in re.finditer(
            r"^\s*\S+\s*=\s*([-\d.]+e?[-+]?\d*)(?:\s*,\s*([-\d.]+e?[-+]?\d*))?\s*$",
            out, re.M):
        vals.append(float(m.group(1)))
        if m.group(2) is not None:
            vals.append(float(m.group(2)))
    return vals or None


def relerr(a, b, floor=1e-14):
    if a is None or b is None or len(a) != len(b) or not a:
        return None
    return max(abs(x - y) / max(floor, abs(y)) for x, y in zip(a, b))


# ---------------------------------------------------------------- phase 1
def nodes_of(out):
    if out is None:
        return None
    v = {int(m.group(1)): float(m.group(2)) for m in re.finditer(
        r"^v\(n(\d+)\)\s*=\s*([-\d.]+e?[-+]?\d*)\s*$", out, re.M | re.I)}
    return v or None


def build(edges, nnode, src, src_val=1.0):
    """returns (deck, exact solution, condition number)"""
    lines = ["V1 n%d 0 dc %g" % (src, src_val)]
    for k, (i, j, g) in enumerate(edges):
        lines.append("R%d %s %s %.17g" % (k + 1, "n%d" % i if i else "0",
                                          "n%d" % j if j else "0", 1.0 / g))
    probes = " ".join("v(n%d)" % n for n in range(1, nnode + 1))
    deck = ("\n".join(lines) + "\n.control\nset numdgt=16\noption noacct\nop\n"
            "print %s\n.endc\n.end\n" % probes)

    unknown = [n for n in range(1, nnode + 1) if n != src]
    idx = {n: k for k, n in enumerate(unknown)}
    G = np.zeros((len(unknown), len(unknown)))
    rhs = np.zeros(len(unknown))
    for i, j, g in edges:
        for a, b in ((i, j), (j, i)):
            if a in idx:
                G[idx[a], idx[a]] += g
                if b in idx:
                    G[idx[a], idx[b]] -= g
                elif b == src:
                    rhs[idx[a]] += g * src_val
    sol = np.linalg.solve(G, rhs)
    exact = {n: sol[idx[n]] for n in unknown}
    exact[src] = src_val
    return deck, exact, np.linalg.cond(G)


def ladder_ratio(k, n=40):
    e = []
    for i in range(1, n + 1):
        e += [(i, i + 1, 1.0), (i + 1, 0, 10.0 ** (-k))]
    return e, n + 1, 1


def star(k, n=60):
    """hub with n spoke NODES -- a dense matrix row (trap 1: the hub must be an
    unknown with real fan-out, or the system is 1x1 and cond is 1.0)"""
    e = [(1, 2, 1.0)]
    for i in range(n):
        g = 10.0 ** (-k + 2.0 * k * i / max(1, n - 1))
        e += [(2, 3 + i, g), (3 + i, 0, 1.0)]
    return e, 2 + n, 1


def weak_couple(k):
    e = [(i, i + 1, 1e3) for i in (1, 2, 3)]
    e.append((4, 5, 10.0 ** (-k) * 1e-3))
    e += [(i, i + 1, 1e3) for i in (5, 6, 7)]
    e.append((8, 0, 1e3))
    return e, 8, 1


def near_float(k, n=20):
    e = [(i, i + 1, 1.0) for i in range(1, n + 1)]
    e.append((n + 1, 0, 10.0 ** (-k)))
    return e, n + 1, 1


def wide_range(k, n=50):
    e = []
    for i in range(1, n + 1):
        e.append((i, i + 1, 10.0 ** (-k + 2.0 * k * ((i * 7) % n) / max(1, n - 1))))
        e.append((i + 1, 0, 10.0 ** (k - 2.0 * k * ((i * 3) % n) / max(1, n - 1))))
    return e, n + 1, 1


FAMILIES = {"ladder_ratio": ladder_ratio, "star": star, "weak_couple": weak_couple,
            "near_float": near_float, "wide_range": wide_range}


def phase1():
    print("\nPHASE 1 -- ill-conditioned linear networks vs a numpy EXACT oracle\n")
    if np is None:
        print("  numpy not available; phase 1 needs it for the third opinion. Skipped.")
        return
    print("  %-22s %10s %10s %10s %10s" %
          ("family(decades)", "cond", "sparse err", "klu err", "s-vs-k"))
    worst = 0.0
    for fam, fn in FAMILIES.items():
        for k in (0, 3, 6, 9, 12):
            edges, nnode, src = fn(k)
            deck, exact, cond = build(edges, nnode, src)
            vs = nodes_of(run("%s%d" % (fam, k), deck, "sparse"))
            vk = nodes_of(run("%s%d" % (fam, k), deck, "klu"))
            if not vs or not vk:
                rec("%s k=%d" % (fam, k), False, "no result")
                continue
            common = sorted(set(vs) & set(vk) & set(exact))
            FLOOR = 1e-12          # trap 2: per-node relative error, with a floor

            def err(v):
                return max(abs(v[n] - exact[n]) / max(FLOOR, abs(exact[n]))
                           for n in common)
            es, ek = err(vs), err(vk)
            d = max(abs(vs[n] - vk[n]) / max(FLOOR, abs(exact[n])) for n in common)
            worst = max(worst, d)
            print("  %-22s %10.2e %10.2e %10.2e %10.2e"
                  % ("%s(%d)" % (fam, k), cond, es, ek, d))
            if cond > 1e12:
                print("      (cond %.1e beyond float64 -- reported, not asserted; "
                      "s-vs-k %.1e)" % (cond, d))
                continue
            tol = min(1e-6, max(1e-13, 5e-16 * cond))
            rec("%s k=%-2d  both within eps*cond, and agree" % (fam, k),
                es <= tol and ek <= tol and d <= tol,
                "sparse %.1e klu %.1e s-k %.1e tol %.1e" % (es, ek, d, tol))
    print("\n  worst Sparse-vs-KLU disagreement in phase 1: %.2e" % worst)


# ---------------------------------------------------------------- phase 2
def diode_ladder(n, bias):
    L = ["V1 x0 0 dc %g" % bias]
    for i in range(n):
        L += ["R%d x%d x%d 100" % (i + 1, i, i + 1), "D%d x%d 0 dm" % (i + 1, i + 1)]
    L.append(".model dm d(is=1e-14 n=1 rs=0 cjo=0 tt=0)")
    return "\n".join(L) + "\n"


def mos_chain(n):
    L = ["V1 n0 0 dc 2", "Vg g 0 dc 1.2"]
    for i in range(n):
        L += ["R%d n%d n%d 1k" % (i + 1, i, i + 1),
              "M%d n%d g 0 0 nm w=2u l=0.5u" % (i + 1, i + 1)]
    L.append(".model nm nmos level=1 vto=0.7 kp=1e-4")
    return "\n".join(L) + "\n"


def wide_r_diode(n, dec):
    L = ["V1 x0 0 dc 1.5"]
    for i in range(n):
        g = 10.0 ** (-dec + 2.0 * dec * i / max(1, n - 1))
        L += ["R%d x%d x%d %.17g" % (i + 1, i, i + 1, 1.0 / g),
              "D%d x%d 0 dm" % (i + 1, i + 1)]
    L.append(".model dm d(is=1e-14 n=1 rs=0 cjo=0 tt=0)")
    return "\n".join(L) + "\n"


def both(name, net, ctl, opts=""):
    d = lambda s: net + ".control\nset numdgt=16\noption noacct\n%s\n.endc\n.end\n" % ctl
    a = values(run(name, opts + d("sparse"), "sparse"))
    b = values(run(name, opts + d("klu"), "klu"))
    return a, b, relerr(a, b)


def phase2():
    print("\nPHASE 2 -- nonlinear / stiff, where Sparse actually re-pivots\n")

    net = "V1 a 0 dc 0.7\nD1 a 0 dm\n.model dm d(is=1e-14 n=1 rs=0 cjo=0 tt=0)\n"
    a, b, _ = both("diode1", net, "op\nprint -i(v1)")
    want = 1e-14 * (math.exp(0.7 / VT) - 1.0)
    rec("single diode == closed form, both solvers",
        a and b and abs(a[0] - want) / want < 1e-6 and abs(b[0] - want) / want < 1e-6,
        "sparse %.10g klu %.10g want %.10g" % (a[0], b[0], want) if a and b else "no result")

    for n, bias in ((40, 0.8), (200, 0.8), (200, 5.0), (600, 5.0)):
        _, _, e = both("dl%d_%g" % (n, bias), diode_ladder(n, bias),
                       "op\nprint v(x%d) v(x%d) -i(v1)" % (n // 2, n))
        rec("diode ladder n=%-3d bias=%.1f: solvers agree" % (n, bias),
            e is not None and e < 1e-9, "rel diff %.2e" % e if e is not None else "no result")

    _, _, e = both("dltight", diode_ladder(200, 5.0),
                   "op\nprint v(x100) v(x200) -i(v1)",
                   ".options reltol=1e-10 abstol=1e-15 vntol=1e-12\n")
    rec("diode ladder at reltol=1e-10: solvers agree", e is not None and e < 1e-10,
        "rel diff %.2e" % e if e is not None else "no result")

    for n in (50, 300):
        _, _, e = both("mos%d" % n, mos_chain(n),
                       "op\nprint v(n%d) v(n%d) -i(v1)" % (n // 2, n))
        rec("MOSFET chain n=%-3d: solvers agree" % n, e is not None and e < 1e-9,
            "rel diff %.2e" % e if e is not None else "no result")

    # trap 3: cond of the LINEARISED system at the operating point, measured
    # separately. A crude eps*span bound underestimates it by ~450x.
    for dec, cond in ((3, 4.506e8), (6, 1.826e14), (9, 2.627e18)):
        _, _, e = both("wd%d" % dec, wide_r_diode(120, dec),
                       "op\nprint v(x60) v(x120) -i(v1)")
        bound = 2.2e-16 * cond
        if bound > 1e-3:
            print("      (span 10^%d, cond %.2e: eps*cond = %.1e, beyond float64 "
                  "-- reported, not asserted; s-vs-k %s)"
                  % (2 * dec, cond, bound, "%.2e" % e if e is not None else "?"))
            continue
        rec("diode + R span 10^%d: agree within eps*cond" % (2 * dec),
            e is not None and e <= max(1e-12, bound),
            "rel diff %.2e, cond %.1e, bound %.1e" % (e, cond, bound)
            if e is not None else "no result")

    net = diode_ladder(120, 0.8).replace("V1 x0 0 dc 0.8", "V1 x0 0 dc 0.8 ac 1")
    net += "".join("C%d x%d 0 10p\n" % (i, i) for i in range(1, 121))
    for tag, ctl, tol in (
        ("dc sweep", "dc V1 0.2 0.9 0.05\nprint v(x60)[7] v(x120)[14] -i(v1)[14]", 1e-9),
        ("ac", "ac dec 6 1 1e8\nprint mag(v(x60))[0] mag(v(x60))[24] ph(v(x120))[24]", 1e-8),
        ("tran", "tran 5n 2u\nmeas tran a FIND v(x60) AT=1u\n"
                 "meas tran b FIND v(x120) AT=1.5u", 1e-7),
        ("noise", "noise v(x120) V1 dec 4 10 1e5\nsetplot noise1\n"
                  "print onoise_spectrum[0] onoise_spectrum[8]", 1e-7),
        ("tf", "tf v(x120) V1\nprint transfer_function v1#input_impedance", 1e-9),
    ):
        _, _, e = both("an_%s" % tag, net, ctl)
        rec("%-9s on a 120-diode ladder: solvers agree" % tag,
            e is not None and e < tol,
            "rel diff %.2e (tol %.0e)" % (e, tol) if e is not None else "no result")

    # pz on a SMALL reactive ladder -- it does not converge at 120 nodes, on
    # EITHER solver, so that is a pz scale limit and not a differential finding
    small = ("V1 x0 0 dc 0.8 ac 1\n"
             + "".join("R%d x%d x%d 100\nD%d x%d 0 dm\nC%d x%d 0 10p\n"
                       % (i, i - 1, i, i, i, i, i) for i in range(1, 7))
             + ".model dm d(is=1e-14 n=1 rs=0 cjo=0 tt=0)\n")
    _, _, e = both("pzsmall", small, "pz x0 0 x6 0 vol pol\nprint pole(1)")
    rec("pz on a 6-stage reactive ladder: solvers agree",
        e is not None and e < 1e-6,
        "rel diff %.2e" % e if e is not None else "no result")


def main(argv):
    want = [a for a in argv[1:] if a in ("1", "2")] or ["1", "2"]
    print("Sparse 1.3 vs KLU -- differential campaign")
    if "1" in want:
        phase1()
    if "2" in want:
        phase2()
    for junk in os.listdir(HERE):
        if junk.startswith("_"):
            os.remove(os.path.join(HERE, junk))
    n = len(results)
    ok = sum(1 for _, k in results if k)
    print("\n%s: %d/%d checks passed" % ("ALL PASS" if ok == n else "FAILURES", ok, n))
    return 0 if ok == n else 1


sys.exit(main(sys.argv))
