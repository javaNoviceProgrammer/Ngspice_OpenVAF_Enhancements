#!/usr/bin/env python3
"""
verify_yield.py -- verifies Enhancement-151: native process/mismatch
correlations (`mccorr` + `mvnorm`) and the packaged Monte Carlo yield command
(`montecarlo`), end-to-end through the committed ngspice.

Correlations. `mccorr <k> <matrix...>` registers a k x k correlation matrix
(Cholesky-factored); `mvnorm(i)` in a `.param` returns the i-th component of one
correlated standard-normal draw per Monte Carlo sample. So a shared process
factor plus independent local mismatch -- or an arbitrary correlation matrix --
becomes expressible natively:

    .param vth1 = 0.5 + 0.03*mvnorm(1)      ; correlation between vth1 and vth2
    .param vth2 = 0.5 + 0.03*mvnorm(2)      ; is set by the mccorr matrix

Yield. `montecarlo <N> [-lhs] -spec <metric> [-max <hi>] [-min <lo>] ...` runs N
samples, passes a sample only if every spec is within its limits, and reports the
yield with a Wilson 95% confidence interval and a per-spec violation count.

Ground truth: one Gaussian `.param` R ~ N(mu, sigma) with a two-sided spec
[mu - k*sigma, mu + k*sigma] has yield P(|Z| < k); two independent such specs
multiply; a bivariate normal with correlation rho has a known joint-pass
probability that the correlated draws must reproduce.

Checks (heavy deck -- thousands of re-sources -- and a front-end feature, so
Sparse-only per _setup.SPARSE_ONLY):

  [1] correlation: an mccorr rho=0.7 matrix yields empirical corr ~ 0.7, with the
      right means and sigmas; a rho=-0.6 matrix yields ~ -0.6.
  [2] mvnorm without mccorr draws independently (corr ~ 0).
  [3] a non-positive-definite matrix is rejected.
  [4] yield of a single two-sided spec matches P(|Z| < k).
  [5] yield of two independent specs multiplies.
  [6] -lhs gives the same yield as random (unbiased), lower variance over trials.
  [7] positive parameter correlation raises the joint yield vs independent.

Every SPICE deck starts with a title line (SPICE treats line 1 as the title!).
"""
import math
import os
import re
import statistics
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from _setup import NG as NGSPICE
from _setup import check_both_solvers as _check_both_solvers
_check_both_solvers(__file__)   # Sparse-only (heavy deck)

SCRATCH = tempfile.mkdtemp(prefix="yield_verify_")

try:
    from statistics import NormalDist
    Phi = NormalDist().cdf
except Exception:                       # pragma: no cover
    Phi = lambda x: 0.5 * math.erfc(-x / math.sqrt(2))

_fail = 0


def check(label, ok, detail=""):
    global _fail
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}" + (f" -- {detail}" if detail else ""))
    if not ok:
        _fail += 1


def run(deck):
    with open(os.path.join(SCRATCH, "_y.cir"), "w") as f:
        f.write(deck)
    r = subprocess.run([NGSPICE, "-b", "_y.cir"], capture_output=True, text=True,
                       timeout=1200, cwd=SCRATCH)
    return r.stdout + r.stderr


def grab(log, name):
    m = re.search(rf"{re.escape(name)}\s*=\s*(-?[0-9.]+(?:[eE][-+]?[0-9]+)?)", log)
    return float(m.group(1)) if m else float("nan")


def read_cols(fname, ncol):
    cols = [[] for _ in range(ncol)]
    for ln in open(os.path.join(SCRATCH, fname)):
        p = ln.split()
        # `print a b > file` writes a table: Index  a  b  (one index column)
        if len(p) >= 1 + ncol and p[0].isdigit():
            try:
                for k in range(ncol):
                    cols[k].append(float(p[1 + k]))
            except ValueError:
                pass
    return cols


def corr_deck(n, matrix_row_major, k=2):
    mat = " ".join(f"{v:g}" for v in matrix_row_major)
    return f"""* correlated draws
.param a = 10 + 2*mvnorm(1)
.param b = 20 + 3*mvnorm(2)
V1 x 0 DC 1
Ra x 0 {{a}}
V2 y 0 DC 1
Rb y 0 {{b}}
.control
  set numdgt=10
  mccorr {k} {mat}
  setseed 1
  let n = {n}
  let av = unitvec(n)
  let bv = unitvec(n)
  let run = 0
  dowhile run < n
    reset
    op
    let av[run] = -1/i(v1)
    let bv[run] = -1/i(v2)
    let run = run + 1
  end
  print av bv > corr.txt
.endc
.end
"""


print("Enhancement-151: process/mismatch correlations + Monte Carlo yield\n")

# --- [1] correlation matches the mccorr rho ------------------------------
print("[1] mccorr rho = +0.7 and -0.6 reproduce the target correlation")
for rho in (0.7, -0.6):
    run(corr_deck(3000, [1, rho, rho, 1]))
    av, bv = read_cols("corr.txt", 2)
    n = len(av)
    ma, mb = statistics.mean(av), statistics.mean(bv)
    sa, sb = statistics.pstdev(av), statistics.pstdev(bv)
    cov = sum((x - ma) * (y - mb) for x, y in zip(av, bv)) / n
    emp = cov / (sa * sb)
    check(f"empirical corr ~ {rho:+.2f}", abs(emp - rho) < 0.06, f"got {emp:+.3f}")
    if rho == 0.7:
        check("means ~ (10, 20)", abs(ma - 10) < 0.2 and abs(mb - 20) < 0.3,
              f"({ma:.2f}, {mb:.2f})")
        check("sigmas ~ (2, 3)", abs(sa - 2) < 0.2 and abs(sb - 3) < 0.3,
              f"({sa:.2f}, {sb:.2f})")

# --- [2] mvnorm without mccorr is independent ----------------------------
print("[2] mvnorm without a registered matrix draws independently")
d = corr_deck(3000, [1, 0, 0, 1]).replace("mccorr 2 1 0 0 1", "mccorr off")
run(d)
av, bv = read_cols("corr.txt", 2)
n = len(av)
ma, mb = statistics.mean(av), statistics.mean(bv)
sa, sb = statistics.pstdev(av), statistics.pstdev(bv)
cov = sum((x - ma) * (y - mb) for x, y in zip(av, bv)) / n
emp = cov / (sa * sb)
check("uncorrelated (|corr| < 0.06)", abs(emp) < 0.06, f"got {emp:+.3f}")

# --- [3] a non-positive-definite matrix is rejected ----------------------
print("[3] a non-positive-definite matrix is rejected")
log = run("""* bad matrix
.param a = mvnorm(1)
R1 a 0 1k
.control
  mccorr 2 1 1.5 1.5 1
.endc
.end
""")
check("mccorr rejects a non-PD matrix", "not positive-definite" in log)

# --- yield decks ---------------------------------------------------------
MU, AV, S = 1000.0, 100.0, 3.0
SIG = AV / S


def yield_deck(n, kspec, lhs=False, seed=1):
    hi, lo = MU + kspec * SIG, MU - kspec * SIG
    return f"""* single-spec yield
.param rr = agauss({MU:g}, {AV:g}, {S:g})
V1 a 0 DC 1
R1 a 0 {{rr}}
.control
  montecarlo {n} {"-lhs " if lhs else ""}-seed {seed} -analysis op -spec -1/i(v1) -max {hi:.4f} -min {lo:.4f}
  print montecarlo_yield
.endc
.end
"""


# --- [4] single-spec yield ----------------------------------------------
print("[4] single two-sided spec yield ~ P(|Z| < k)")
k = 1.5
y = grab(run(yield_deck(4000, k)), "montecarlo_yield")
true_y = Phi(k) - Phi(-k)
check(f"yield ~ P(|Z|<{k}) = {true_y:.4f}", abs(y - true_y) < 0.02, f"got {y:.4f}")

# --- [5] two independent specs multiply ----------------------------------
print("[5] two independent specs -> yields multiply")
k = 1.5
log = run(f"""* two independent specs
.param r1 = agauss({MU:g}, {AV:g}, {S:g})
.param r2 = agauss(2000, {AV:g}, {S:g})
V1 a 0 DC 1
Ra a 0 {{r1}}
V2 b 0 DC 1
Rb b 0 {{r2}}
.control
  montecarlo 4000 -seed 5 -analysis op -spec -1/i(v1) -max {MU + k*SIG:.4f} -min {MU - k*SIG:.4f} -spec -1/i(v2) -max {2000 + k*SIG:.4f} -min {2000 - k*SIG:.4f}
  print montecarlo_yield
.endc
.end
""")
y = grab(log, "montecarlo_yield")
true_y = (Phi(k) - Phi(-k)) ** 2
check(f"yield ~ P(|Z|<{k})^2 = {true_y:.4f}", abs(y - true_y) < 0.025, f"got {y:.4f}")

# --- [6] -lhs is unbiased and lower-variance -----------------------------
print("[6] -lhs: same yield (unbiased), lower variance over trials")
true_y = Phi(1.5) - Phi(-1.5)
rnd = [grab(run(yield_deck(1500, 1.5, lhs=False, seed=s)), "montecarlo_yield") for s in range(1, 9)]
lhs = [grab(run(yield_deck(1500, 1.5, lhs=True, seed=s)), "montecarlo_yield") for s in range(1, 9)]
vr, vl = statistics.pvariance(rnd), statistics.pvariance(lhs)
check("random yield mean ~ analytic", abs(statistics.mean(rnd) - true_y) < 0.02,
      f"{statistics.mean(rnd):.4f}")
check("LHS yield mean ~ analytic", abs(statistics.mean(lhs) - true_y) < 0.02,
      f"{statistics.mean(lhs):.4f}")
check("LHS variance <= random variance", vl <= vr * 1.1,
      f"Var(rnd)={vr:.2e}, Var(lhs)={vl:.2e}")

# --- [7] positive correlation raises the joint yield ---------------------
print("[7] positive parameter correlation raises the joint yield")
def two_param_yield(rho):
    return grab(run(f"""* correlated two-spec yield
.param a = 1000 + {SIG:g}*mvnorm(1)
.param b = 1000 + {SIG:g}*mvnorm(2)
V1 x 0 DC 1
Ra x 0 {{a}}
V2 y 0 DC 1
Rb y 0 {{b}}
.control
  mccorr 2 1 {rho:g} {rho:g} 1
  montecarlo 5000 -seed 7 -analysis op -spec -1/i(v1) -max {1000 + 1.5*SIG:.4f} -min {1000 - 1.5*SIG:.4f} -spec -1/i(v2) -max {1000 + 1.5*SIG:.4f} -min {1000 - 1.5*SIG:.4f}
  print montecarlo_yield
.endc
.end
"""), "montecarlo_yield")
y_indep = two_param_yield(0.0)
y_corr = two_param_yield(0.9)
check("corr=0.9 yield > independent yield (same-direction specs)",
      y_corr > y_indep + 0.02, f"indep={y_indep:.4f}, corr={y_corr:.4f}")

# --- MC hunt F4 (2026-09-04): an index the matrix does not have is refused --
# mvnorm(3) against a 2x2 matrix, or mvnorm(0), used to fall through to an
# independent standard normal without a word, so the correlation the deck
# asked for was simply absent; a fractional index was rounded in silence.
# With a matrix registered both are now .param errors. Without one the
# independent draw stands (E-151's design, and check [2] above) -- which is
# every deck's state at LOAD, before its .control block has run mccorr; so
# mccorr itself now reports an index the deck has already used beyond it.
print("[F4] mvnorm outside the registered matrix is a deck error, not a silent draw")
BAD = """* mvnorm beyond the registered matrix
.param a = 10 + 2*mvnorm(%s)
V1 x 0 DC {a}
R1 x 0 1k
.control
mccorr 2 1 0.9 0.9 1
%s
op
print v(x)
.endc
.end
"""
log = run(BAD % ("3", "reset"))
check("mvnorm(3) against a 2x2 matrix: the reset refuses it, naming the range",
      "so only mvnorm(1..2) exist" in log and "v(x) = " not in log,
      "refused" if "so only mvnorm(1..2) exist" in log else "NOT refused")
log = run(BAD % ("1.5", "reset"))
check("mvnorm(1.5) is refused as a non-integer index",
      "index must be a whole number" in log and "v(x) = " not in log, "")
log = run(BAD % ("2", "reset"))
check("mvnorm(2) against a 2x2 matrix still draws, with no error",
      "v(x) = " in log and "Error in netlist" not in log, "")
log = run(BAD % ("3", ""))
check("without a reset, mccorr says the deck already used mvnorm(3) beyond it",
      "already evaluated mvnorm(3), which this 2 x 2 matrix does not have" in log
      and "v(x) = " in log, "the load-time draw was independent, and it says so")

import shutil
shutil.rmtree(SCRATCH, ignore_errors=True)

print()
if _fail:
    print(f"RESULT: {_fail} check(s) FAILED")
    sys.exit(1)
print("RESULT: all checks passed")
