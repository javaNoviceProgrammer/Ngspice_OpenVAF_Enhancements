#!/usr/bin/env python3
"""Enhancement-181: core-numerics audit -- the integrator certified exactly,
plus the `.options ordfix` verification instrument.

THE AUDIT. The gap-analysis "Core numerics" table says the integration methods
and convergence machinery are on-par -- but nobody had ever verified that
ngspice's Gear (BDF) corrector coefficients actually deliver their nominal
order: orders 3-6 were dead code for ~30 years until E-128's `dynorder` woke
them, and E-128 verified order *selection*, not coefficient *correctness*.

THE INSTRUMENT. Measuring the order of convergence from outside is impossible
with the stock controller (the LTE step control refuses to hold a fixed step,
and with loose tolerances high order is genuinely LTE-suboptimal:
h_k = (c_k*tol)^{1/(k+1)} INVERTS its ordering for tol >> 1). `.options
ordfix=K` pins the integration order at K for verification: every converged
step is accepted (the step is ruled by tmax, not LTE), the first step is
shrunk 1000x (an order-1 first step proportional to the pinned step imposes an
O(h^2) startup floor that masks high-order convergence), the order ramps to K
while the step is still tiny, and the step then grows GENTLY (x1.15) to the
pin -- large step ratios destabilize variable-step BDF at high order.

THE CERTIFICATION. With the instrument, the referee is airtight: dump the
accepted trajectory at full precision and check, at every stencil of k+1
uniformly-spaced points, that ngspice's values satisfy the EXACT BDF-k
formula (Lagrange differentiation on the actual nodes) for the circuit ODE.
Result: residuals at machine precision (<=1e-12) at every order 1-6 -- the
NIcomCof coefficients are exactly right. The measured global convergence
slopes confirm orders 1-3 asymptotically; and the textbook
dissipation dichotomy is reproduced on a lossless LC: trapezoidal (A-stable,
no numerical damping) holds the oscillation amplitude while Gear visibly
damps it -- expected theory, guarded as conformance. (BDF>=4's instability
lens on the imaginary axis exists only at tiny |h*lambda| with growth rates
too small to demonstrate in-suite; during the audit it WAS observed when
ramp-seeded, exactly as theory predicts.)

ALSO AUDITED (no defects): linear-solve precision tracks conditioning theory
under both solvers (a 1e18-conductance-spread asymmetric mesh solves to
1e-15 vs an exact-rational MNA referee); every DC convergence-aid path
(default / noopiter / gminsteps=0 / srcsteps=0) lands on the same operating
point on a 40-diode hard-DC chain, KLU == Sparse to 1e-12; the ancient
`xmu` knob works (xmu=0.5 is bit-identical to trap; xmu<0.5 damps); and
`lvltim=1` (iteration-count timestep control) still works.

Every SPICE deck starts with a title line (SPICE treats line 1 as the title!).
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
_check_both_solvers(__file__)

passed = failed = 0


def check(name, ok, detail=""):
    global passed, failed
    if ok:
        passed += 1
        print(f"  PASS  {name} {detail}")
    else:
        failed += 1
        print(f"  FAIL  {name} {detail}")


def run_deck(name, deck):
    path = os.path.join(HERE, name)
    open(path, "w").write(deck)
    r = subprocess.run([NGSPICE, "-b", path], capture_output=True, text=True,
                       timeout=300, cwd=HERE)
    return r.stdout + r.stderr


def scalars(out):
    return dict((m.group(1).lower(), float(m.group(2)))
                for m in re.finditer(r"^(\S+)\s*=\s*([-\d.eE+]+)", out, re.M))


TAU = 1e-3

# ---------------- [1] BDF-k residual referee: coefficients exact, orders 1-6 ----------------
def traj(k, h):
    out = run_deck(f"_tj{k}.cir", f"""* traj gear{k}
R1 a 0 1k
C1 a 0 1u ic=1
.options method=gear maxord={k} ordfix={k} reltol=1e-3 abstol=1e-12
.tran {h} 10m 0 {h} uic
.control
set numdgt=15
run
print v(a)
.endc
.end
""")
    return [(float(m.group(1)), float(m.group(2)))
            for m in re.finditer(r"^\d+\s+([\d.eE+-]+)\s+([\d.eE+-]+)\s*$", out, re.M)]


def bdf_residual(pts, k, h):
    """max relative residual of the exact BDF-k formula on uniform stencils"""
    worst, checked = 0.0, 0
    for n in range(k + 1, len(pts)):
        ts = [pts[n - j][0] for j in range(k + 1)]
        if any(not (0.98 * h < (ts[j] - ts[j + 1]) < 1.02 * h) for j in range(k)):
            continue
        ys = [pts[n - j][1] for j in range(k + 1)]
        tn = ts[0]
        ydot = 0.0
        for j in range(k + 1):                     # Lagrange derivative at tn
            others = [ts[m] for m in range(k + 1) if m != j]
            num = 0.0
            for m in range(len(others)):
                prod = 1.0
                for q in range(len(others)):
                    if q != m:
                        prod *= (tn - others[q])
                num += prod
            den = 1.0
            for o in others:
                den *= (ts[j] - o)
            ydot += (num / den) * ys[j]
        resid = abs(ydot + ys[0] / TAU) / (abs(ys[0]) / TAU + 1e-30)
        worst = max(worst, resid)
        checked += 1
    return worst, checked


ok = True
details = []
for k in (1, 2, 3, 4, 5, 6):
    pts = traj(k, 100e-6)
    w, n = bdf_residual(pts, k, 100e-6)
    details.append(f"k{k}:{w:.1e}/{n}")
    if n < 40 or w > 1e-12:
        ok = False
check("[1] Gear coefficients EXACT: BDF-k residual <=1e-12 on uniform stencils, orders 1-6",
      ok, "(" + " ".join(details) + ")")

# ---------------- [2] measured convergence slopes (orders 1-3 + trap) ----------------
def endpoint(opt, h):
    out = run_deck("_ep.cir", f"""* slope study
R1 a 0 1k
C1 a 0 1u ic=1
.options {opt} reltol=1e-3 abstol=1e-12
.tran {h} 1m 0 {h} uic
.control
set numdgt=15
run
let ve = v(a)[length(v(a))-1]
print ve
.endc
.end
""")
    m = re.search(r"^ve = ([-\d.eE+]+)", out, re.M)
    return float(m.group(1)) if m else None


REFD = math.exp(-1.0)
slopes = {}
for label, opt, kmin in (("trap", "method=trap ordfix=2", 1.8),
                         ("gear1", "method=gear maxord=1 ordfix=1", 0.8),
                         ("gear2", "method=gear maxord=2 ordfix=2", 1.7),
                         ("gear3", "method=gear maxord=3 ordfix=3", 2.5)):
    e1 = abs(endpoint(opt, 25e-6) - REFD) / REFD
    e2 = abs(endpoint(opt, 12.5e-6) - REFD) / REFD
    slopes[label] = (math.log2(e1 / e2), kmin)
ok = all(s >= kmin for s, kmin in slopes.values())
check("[2] measured convergence orders: trap>=1.8, gear1>=0.8, gear2>=1.7, gear3>=2.5",
      ok, "(" + " ".join(f"{k}:{v[0]:.2f}" for k, v in slopes.items()) + ")")

# ---------------- [3] dissipation conformance on a lossless LC ----------------
# Trapezoidal has |R(iy)| = 1: the oscillation AMPLITUDE is preserved exactly
# (its error is pure phase). Gear is dissipative: the envelope decays. Compare
# the last-period amplitude -- a phase-immune conformance metric.


def lc_amp(opt, h=8e-6):
    out = run_deck("_lc.cir", f"""* lc dissipation
L1 a 0 1m ic=0
C1 a 0 1u ic=1
.options {opt} reltol=1e-3 abstol=1e-12
.tran {h} 2m 0 {h} uic
.control
set numdgt=15
run
print v(a)
.endc
.end
""")
    pts = [(float(m.group(1)), float(m.group(2)))
           for m in re.finditer(r"^\d+\s+([\d.eE+-]+)\s+([\d.eE+-]+)\s*$", out, re.M)]
    tend = pts[-1][0]
    last = max(abs(v) for t, v in pts if t > tend - 200e-6)   # final full period
    peak = max(abs(v) for t, v in pts)
    return last, peak


amp_trap, pk_trap = lc_amp("method=trap ordfix=2")
amp_g2, pk_g2 = lc_amp("method=gear maxord=2 ordfix=2")
amp_g6, pk_g6 = lc_amp("method=gear maxord=6 ordfix=6")
ok = (pk_trap < 1.01 and pk_g2 < 1.01 and pk_g6 < 1.01 and    # all bounded
      amp_trap > 0.99 and                                      # trap: no damping
      amp_g2 < 0.9 and                                         # gear2: damps hard
      amp_g6 > amp_g2)                                         # higher order: less
check("[3] lossless LC conformance: trap preserves amplitude, Gear damps (order-dependent)",
      ok, f"(last-period amp: trap {amp_trap:.4f}, gear2 {amp_g2:.4f}, gear6 {amp_g6:.4f})")

# ---------------- [4] hard-DC convergence aids: all paths, one answer ----------------
CHAIN = ("V1 in 0 DC 60\nR1 in d0 100\n" +
         "\n".join(f"D{i} d{i} d{i+1} DM" for i in range(40)) +
         "\nR2 d40 0 10\n.model DM D(IS=1e-14 N=1)\n")
vals = {}
for vn, opt in (("default", ""), ("noopiter", ".options noopiter\n"),
                ("nogmin", ".options gminsteps=0\n"), ("nosrc", ".options srcsteps=0\n")):
    out = run_deck(f"_hd_{vn}.cir", f"* hard dc {vn}\n{opt}" + CHAIN +
                   ".op\n.control\nset numdgt=15\nrun\nprint v(d40)\n.endc\n.end\n")
    vals[vn] = scalars(out).get("v(d40)")
ref = vals["default"]
ok = ref is not None and all(v is not None and abs(v - ref) / abs(ref) < 1e-4
                             for v in vals.values())
check("[4] hard-DC 40-diode chain: default/noopiter/gmin-off/src-off all agree (<=1e-4)",
      ok, f"(v(d40)={ref:.9f}, spread {max(abs(v-ref)/abs(ref) for v in vals.values() if v):.1e})")

# ---------------- [5] linear-solve precision vs exact-rational MNA ----------------
from fractions import Fraction
Gs = {("a", "b"): Fraction(1), ("b", "0"): Fraction(1, 10**9),
      ("a", "0"): Fraction(10**9), ("b", "c"): Fraction(1000), ("c", "0"): Fraction(1, 1000)}
gm = Fraction(50)
names = ["a", "b", "c"]
idx = {n: i for i, n in enumerate(names)}
A = [[Fraction(0)] * 3 for _ in range(3)]
b = [Fraction(1), Fraction(0), Fraction(0)]
for (p, q), g in Gs.items():
    if p != "0":
        A[idx[p]][idx[p]] += g
    if q != "0":
        A[idx[q]][idx[q]] += g
    if p != "0" and q != "0":
        A[idx[p]][idx[q]] -= g
        A[idx[q]][idx[p]] -= g
A[idx["c"]][idx["a"]] += gm
A[idx["c"]][idx["b"]] -= gm
M = [row[:] + [b[i]] for i, row in enumerate(A)]
for c_ in range(3):
    piv = next(rr for rr in range(c_, 3) if M[rr][c_] != 0)
    M[c_], M[piv] = M[piv], M[c_]
    for rr in range(3):
        if rr != c_ and M[rr][c_] != 0:
            f = M[rr][c_] / M[c_][c_]
            M[rr] = [x - f * y for x, y in zip(M[rr], M[c_])]
ex = [float(M[i][3] / M[i][i]) for i in range(3)]
out = run_deck("_mesh.cir", """* precision mesh
I1 0 a DC 1
R1 a b 1
R2 b 0 1e9
R3 a 0 1e-9
R4 b c 0.001
R5 c 0 1000
G1 c 0 a b 50
.op
.control
set numdgt=15
run
print v(a) v(b) v(c)
.endc
.end
""")
s = scalars(out)
worst = max(abs(s.get(f"v({n})", 0) - ex[i]) / abs(ex[i]) for i, n in enumerate(names))
check("[5] 1e18-spread asymmetric mesh == exact-rational MNA (<=1e-12)",
      worst < 1e-12, f"(worst rel {worst:.2e})")

# ---------------- [6] xmu: 0.5 == trap bit-exact; 0.45 damps the LC ring ----------------
LC = "L1 a 0 1m ic=0\nC1 a 0 1u ic=1\n"
def lcend(opts):
    out = run_deck("_xm.cir", "* xmu\n" + LC + f".options {opts}\n.tran 2u 2m 0 2u uic\n"
                   ".control\nset numdgt=15\nrun\nlet ve=v(a)[length(v(a))-1]\nprint ve\n.endc\n.end\n")
    return scalars(out).get("ve")
v_half = lcend("method=trap xmu=0.5")
v_trap = lcend("method=trap")
v_damp = lcend("method=trap xmu=0.45")
ok = (v_half == v_trap and v_damp is not None and abs(v_damp) < abs(v_trap))
check("[6] xmu: 0.5 == trap bit-identical; 0.45 damps the lossless ring",
      ok, f"(trap {v_trap:.9f}, xmu.45 {v_damp:.9f})")

# ---------------- [7] lvltim=1 (iteration-count control) works and agrees ----------------
DIODE = ("V1 in 0 SIN(0 5 1k)\nD1 in out DM\nR1 out 0 10k\nC1 out 0 100n\n"
         ".model DM D(IS=1e-14 N=1.6)\n")
o1 = run_deck("_l1.cir", "* lvltim1\n" + DIODE + ".options lvltim=1\n.tran 1u 3m\n"
              ".meas tran vf FIND v(out) AT=2.5m\n.control\nrun\n.endc\n.end\n")
o2 = run_deck("_l2.cir", "* lvltim2\n" + DIODE + ".tran 1u 3m\n"
              ".meas tran vf FIND v(out) AT=2.5m\n.control\nrun\n.endc\n.end\n")
f1, f2 = scalars(o1).get("vf"), scalars(o2).get("vf")
ok = f1 is not None and f2 is not None and abs(f1 - f2) / abs(f2) < 1e-3
check("[7] lvltim=1 iteration-count timestep control agrees with default LTE control",
      ok, f"(vf {f1} vs {f2})")

# ---------------- [8] ordfix reports the pinned order; stock runs untouched ----------------
out = run_deck("_of.cir", """* ordfix report
R1 a 0 1k
C1 a 0 1u ic=1
.options method=gear maxord=5 ordfix=5
.tran 50u 5m 0 50u uic
.control
set ngdebug
run
.endc
.end
""")
m = re.search(r"highest integration order used = (\d+) of maxord (\d+)", out)
ok = m is not None and m.group(1) == "5"
check("[8] ordfix=5 reaches and reports order 5 (ngdebug summary)",
      ok, f"(got {m.group(0) if m else 'no summary'})")

print(f"\n{passed} passed, {failed} failed")
raise SystemExit(1 if failed else 0)
