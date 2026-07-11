#!/usr/bin/env python3
"""
verify_lhs.py -- verifies Enhancement-149: Latin-Hypercube (LHS) low-discrepancy
Monte Carlo sampling, end-to-end through the committed ngspice.

The `mcsample lhs <N> [seed <s>]` command puts ngspice's netlist stochastic
functions (agauss/gauss/aunif/unif/limit) into a stratified sampler: over the
next N reset-driven passes each random `.param` dimension's [0,1) range is split
into N equal strata and hit exactly once, instead of being drawn independently
from the PRNG. The payoff is much lower variance in the estimated mean / yield
for the same number of runs. `mcsample random` (or `off`) reverts to plain MC.

Checks (all against the committed ngspice, and -- via _setup -- under BOTH the
Sparse 1.3 and KLU solvers, since LHS is a front-end feature and must be
solver-independent):

  [1] stratification      -- N LHS samples of one Gaussian .param hit each of the
                             N probability strata exactly once (the defining LHS
                             property); plain random sampling does NOT.
  [2] multi-dimension     -- with two independent random params (agauss + aunif),
                             BOTH are stratified independently in the same run.
  [3] variance reduction  -- over many independent trials, Var(sample-mean) under
                             LHS is far smaller than under plain random MC.
  [4] reproducibility     -- same seed => identical samples; different seed
                             => different samples.
  [5] correctness         -- LHS sample mean/stddev match the analytic
                             distribution (agauss(nom,avar,sig) has sigma=avar/sig;
                             aunif(nom,avar) is uniform on [nom-avar, nom+avar]).

Every SPICE deck starts with a title line (SPICE treats line 1 as the title!).
"""
import math
import os
import statistics
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))              # the examples/ dir
from _setup import NG as NGSPICE
from _setup import check_both_solvers as _check_both_solvers
_check_both_solvers(__file__)   # re-run under BOTH KLU and Sparse solvers

# all scratch decks / dumps go in a private temp dir -- nothing is left behind
SCRATCH = tempfile.mkdtemp(prefix="lhs_verify_")

_fail = 0


def check(label, ok, detail=""):
    global _fail
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}" + (f" -- {detail}" if detail else ""))
    if not ok:
        _fail += 1


def run_deck(name, deck, timeout=600):
    with open(os.path.join(SCRATCH, name), "w") as f:
        f.write(deck)
    r = subprocess.run([NGSPICE, "-b", name], capture_output=True, text=True,
                       timeout=timeout, cwd=SCRATCH)
    return r.stdout + r.stderr


def read_col(fname, col=1):
    """Read the numeric `col`-th field of a `print vec > file` dump."""
    vals = []
    for ln in open(os.path.join(SCRATCH, fname)):
        p = ln.split()
        if len(p) > col and p[0][0].isdigit():
            try:
                vals.append(float(p[col]))
            except ValueError:
                pass
    return vals


def norm_cdf(x, mu, sd):
    return 0.5 * (1.0 + math.erf((x - mu) / (sd * math.sqrt(2.0))))


def strata_hit(values, cdf):
    """Map each value to its [0,N) stratum via `cdf`; return the sorted list."""
    n = len(values)
    s = sorted(min(max(int(cdf(v) * n), 0), n - 1) for v in values)
    return s


# distribution knobs shared across decks
NOM, AVAR, SIG = 1000.0, 100.0, 3.0
SD = AVAR / SIG                                        # agauss sigma = avar/sig


def sample_deck(method, seed, n, outfile):
    """One-parameter Gaussian resistor MC; dumps the N drawn R values."""
    cfg = (f"mcsample lhs {n} seed {seed}" if method == "lhs"
           else f"mcsample random\n  setseed {seed}")
    return f"""* LHS one-parameter sampling ({method})
.param rr = agauss({NOM:g}, {AVAR:g}, {SIG:g})
V1 a 0 DC 1
R1 a 0 {{rr}}
.control
  set numdgt=12
  {cfg}
  let n = {n}
  let rv = unitvec(n)
  let run = 0
  dowhile run < n
    reset
    op
    let rv[run] = -1/i(V1)
    let run = run + 1
  end
  print rv > {outfile}
.endc
.end
"""


print("Enhancement-149: Latin-Hypercube Monte Carlo sampling\n")

# --- [1] stratification -----------------------------------------------------
print("[1] stratification: each of N strata hit exactly once (LHS) vs random")
N1 = 48
run_deck("lhs1.cir", sample_deck("lhs", 7, N1, "s_lhs.txt"))
run_deck("rnd1.cir", sample_deck("random", 7, N1, "s_rnd.txt"))
lhs = read_col("s_lhs.txt")
rnd = read_col("s_rnd.txt")
cdfG = lambda v: norm_cdf(v, NOM, SD)
lhs_strata = strata_hit(lhs, cdfG)
rnd_strata = strata_hit(rnd, cdfG)
check(f"LHS ({N1} runs): every stratum occupied exactly once",
      lhs_strata == list(range(N1)),
      f"{len(set(lhs_strata))}/{N1} distinct strata")
# plain random almost surely leaves gaps / doubles up
check("random: leaves gaps (not a Latin hypercube)",
      rnd_strata != list(range(N1)),
      f"{len(set(rnd_strata))}/{N1} distinct strata")

# --- [2] multi-dimension ----------------------------------------------------
print("[2] multi-dimension: two independent params both stratified")
N2 = 40
CNOM, CAVAR = 2000.0, 200.0        # aunif on [1800, 2200]
run_deck("lhs2.cir", f"""* two-parameter LHS stratification
.param rr=agauss({NOM:g},{AVAR:g},{SIG:g}) cc=aunif({CNOM:g},{CAVAR:g})
V1 a 0 DC 1
R1 a 0 {{rr}}
V2 c 0 DC 1
R2 c 0 {{cc}}
.control
  set numdgt=12
  mcsample lhs {N2} seed 5
  let n = {N2}
  let rrv = unitvec(n)
  let ccv = unitvec(n)
  let run = 0
  dowhile run < n
    reset
    op
    let rrv[run] = -1/i(V1)
    let ccv[run] = -1/i(V2)
    let run = run + 1
  end
  print rrv > m_rr.txt
  print ccv > m_cc.txt
.endc
.end
""")
rr = read_col("m_rr.txt")
cc = read_col("m_cc.txt")
sR = strata_hit(rr, lambda v: norm_cdf(v, NOM, SD))
sC = strata_hit(cc, lambda v: (v - (CNOM - CAVAR)) / (2 * CAVAR))
check("param 1 (agauss) fully stratified", sR == list(range(N2)))
check("param 2 (aunif) fully stratified", sC == list(range(N2)))

# --- [3] variance reduction -------------------------------------------------
print("[3] variance reduction: Var(sample-mean) LHS << random, same N")
N3, M = 32, 40
def trial_mean(method, seed, n):
    cfg = (f"mcsample lhs {n} seed {seed}" if method == "lhs"
           else f"mcsample random\n  setseed {seed}")
    deck = f"""* mean estimator ({method})
.param rr = agauss({NOM:g}, {AVAR:g}, {SIG:g})
V1 a 0 DC 1
R1 a 0 {{rr}}
.control
  set numdgt=12
  {cfg}
  let n = {n}
  let iv = unitvec(n)
  let run = 0
  dowhile run < n
    reset
    op
    let iv[run] = i(V1)
    let run = run + 1
  end
  let mm = mean(iv)
  print mm
.endc
.end
"""
    log = run_deck(f"tm_{method}.cir", deck)
    for ln in log.splitlines():
        if ln.strip().startswith("mm ="):
            return float(ln.split("=")[1])
    return float("nan")

rnd_means = [trial_mean("random", s, N3) for s in range(1, M + 1)]
lhs_means = [trial_mean("lhs", s, N3) for s in range(1, M + 1)]
var_rnd = statistics.pvariance(rnd_means)
var_lhs = statistics.pvariance(lhs_means)
ratio = var_rnd / var_lhs if var_lhs > 0 else float("inf")
check(f"LHS variance < random variance (ratio {ratio:.0f}x lower)", ratio > 3.0,
      f"Var(random)={var_rnd:.2e}, Var(LHS)={var_lhs:.2e}")
check("both estimators converge to the same mean",
      abs(statistics.mean(rnd_means) - statistics.mean(lhs_means)) <
      3 * math.sqrt(var_rnd),
      f"E[random]={statistics.mean(rnd_means):.4e}, E[LHS]={statistics.mean(lhs_means):.4e}")

# --- [4] reproducibility ----------------------------------------------------
print("[4] reproducibility: same seed identical, different seed differs")
run_deck("rep_a.cir", sample_deck("lhs", 42, 24, "rep_a.txt"))
run_deck("rep_b.cir", sample_deck("lhs", 42, 24, "rep_b.txt"))
run_deck("rep_c.cir", sample_deck("lhs", 99, 24, "rep_c.txt"))
a, b, c = read_col("rep_a.txt"), read_col("rep_b.txt"), read_col("rep_c.txt")
check("seed 42 reproduces bit-for-bit", a == b and len(a) == 24)
check("seed 99 gives a different sample set", a != c)

# --- [5] correctness --------------------------------------------------------
print("[5] correctness: LHS mean/stddev match the analytic distribution")
big = read_col("s_lhs.txt")   # reuse the N1 Gaussian LHS draws
m, sd = statistics.mean(big), statistics.pstdev(big)
check("mean within 3*sigma/sqrt(N) of nominal",
      abs(m - NOM) < 3 * SD / math.sqrt(N1), f"mean={m:.3f} (nominal {NOM:g})")
# LHS makes the sample sd a very tight estimate of the true sigma
check("sample sigma within 15% of avar/sig",
      abs(sd - SD) < 0.15 * SD, f"sigma={sd:.3f} (true {SD:.3f})")

# drop the whole scratch dir -- nothing is left in the example directory
import shutil
shutil.rmtree(SCRATCH, ignore_errors=True)

print()
if _fail:
    print(f"RESULT: {_fail} check(s) FAILED")
    sys.exit(1)
print("RESULT: all checks passed")
