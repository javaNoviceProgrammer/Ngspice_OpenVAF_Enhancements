#!/usr/bin/env python3
"""
verify_highsigma.py -- verifies Enhancement-150: rare-event (high-sigma)
failure-probability estimation with the `highsigma` command, end-to-end through
the committed ngspice.

`highsigma <N> [-scale <lambda>] -metric <expr> [-max <hi>] [-min <lo>]` estimates
the probability that a circuit metric violates a spec, using scaled-sigma
importance sampling: every Gaussian `.param`'s sigma is inflated by `lambda` so
the rare failure region is sampled often, and each sample is reweighted by the
likelihood ratio p_nominal/p_inflated to give an unbiased estimate. It reaches
4-6 sigma probabilities with a few thousand samples, where plain Monte Carlo
would need 1e5-1e9.

Ground truth: for one Gaussian `.param` R ~ N(mu, sigma) with `agauss(mu, av, s)`
(sigma = av/s), failure `R > mu + beta*sigma` has probability Phi(-beta) exactly,
so the reported P(fail) and the equivalent sigma-to-fail (= -Phi^-1(P)) can be
checked against the analytic value at each beta.

Checks (this is a heavy deck -- thousands of re-sources -- and a front-end,
solver-independent feature, so it is Sparse-only per _setup.SPARSE_ONLY):

  [1] accuracy vs analytic at beta = 2, 4 (moderate and rare)
  [2] deep tail at beta = 5  -- estimated where plain MC (this N) sees 0 failures
  [3] two-sided spec (-max and -min) doubles the tail probability
  [4] reproducibility -- same seed gives the identical estimate
  [5] multi-parameter -- two independent Gaussians combine as N(.,sqrt(s1^2+s2^2))

Every SPICE deck starts with a title line (SPICE treats line 1 as the title!).
"""
import math
import os
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from _setup import NG as NGSPICE
from _setup import check_both_solvers as _check_both_solvers
_check_both_solvers(__file__)   # Sparse-only (heavy deck; see SPARSE_ONLY)

SCRATCH = tempfile.mkdtemp(prefix="hs_verify_")   # nothing left in the example dir

try:
    from statistics import NormalDist
    _nd = NormalDist()
    Phi = _nd.cdf
    Phi_inv = _nd.inv_cdf
except Exception:                      # pragma: no cover
    Phi = lambda x: 0.5 * math.erfc(-x / math.sqrt(2))
    Phi_inv = None

_fail = 0


def check(label, ok, detail=""):
    global _fail
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}" + (f" -- {detail}" if detail else ""))
    if not ok:
        _fail += 1


def run(deck):
    with open(os.path.join(SCRATCH, "_hs.cir"), "w") as f:
        f.write(deck)
    r = subprocess.run([NGSPICE, "-b", "_hs.cir"], capture_output=True, text=True,
                       timeout=1200, cwd=SCRATCH)
    return r.stdout + r.stderr


def grab(log, name):
    m = re.search(rf"{re.escape(name)}\s*=\s*(-?[0-9.]+(?:[eE][-+]?[0-9]+)?)", log)
    return float(m.group(1)) if m else float("nan")


MU, AV, S = 1000.0, 100.0, 3.0
SIG = AV / S                                   # 33.333


def one_param_deck(n, lam, beta, seed=1, two_sided=False):
    hi = MU + beta * SIG
    lo = MU - beta * SIG
    spec = f"-max {hi:.6f}" + (f" -min {lo:.6f}" if two_sided else "")
    return f"""* high-sigma one-parameter, beta={beta}
.param rr = agauss({MU:g}, {AV:g}, {S:g})
V1 a 0 DC 1
R1 a 0 {{rr}}
.control
  highsigma {n} -scale {lam} -seed {seed} -analysis op -metric -1/i(v1) {spec}
  print highsigma_pfail highsigma_sigma highsigma_nfail
.endc
.end
"""


print("Enhancement-150: high-sigma rare-event probability (scaled-sigma IS)\n")

# --- [1] accuracy vs analytic --------------------------------------------
print("[1] accuracy vs analytic Phi(-beta), beta = 2 and 4")
for beta, n, lam in ((2.0, 3000, 1.6), (4.0, 4000, 2.5)):
    log = run(one_param_deck(n, lam, beta))
    p, sig = grab(log, "highsigma_pfail"), grab(log, "highsigma_sigma")
    true_p = Phi(-beta)
    check(f"beta={beta:g}: sigma-to-fail ~ {beta:g}",
          abs(sig - beta) < 0.2, f"got sigma={sig:.3f}")
    check(f"beta={beta:g}: P(fail) ~ Phi(-{beta:g})={true_p:.2e}",
          0.4 * true_p < p < 2.5 * true_p, f"got P={p:.2e}")

# --- [2] deep tail --------------------------------------------------------
print("[2] deep tail beta = 5 (Phi(-5)=2.87e-7; plain MC of this N sees ~0)")
N5 = 6000
log = run(one_param_deck(N5, 3.0, 5.0))
p, sig, nf = grab(log, "highsigma_pfail"), grab(log, "highsigma_sigma"), grab(log, "highsigma_nfail")
check("sigma-to-fail ~ 5.0", abs(sig - 5.0) < 0.25, f"got sigma={sig:.3f}")
check("P(fail) ~ 2.87e-7", 1e-7 < p < 6e-7, f"got P={p:.2e}")
check("enough failures sampled for a stable estimate (>50)", nf > 50, f"nfail={nf:.0f}")
check(f"plain MC of N={N5} would be hopeless here (N*P << 1)", N5 * Phi(-5.0) < 0.01,
      f"expected plain-MC failures = {N5 * Phi(-5.0):.1e}")

# --- [3] two-sided spec ---------------------------------------------------
print("[3] two-sided spec (-max and -min) ~ doubles the tail probability")
beta = 3.5
log = run(one_param_deck(4000, 2.5, beta, two_sided=True))
p, sig = grab(log, "highsigma_pfail"), grab(log, "highsigma_sigma")
true_p = 2.0 * Phi(-beta)
true_sig = -Phi_inv(true_p) if Phi_inv else beta
check("two-sided P ~ 2*Phi(-3.5)", 0.4 * true_p < p < 2.5 * true_p,
      f"got P={p:.2e}, expected {true_p:.2e}")
check(f"equivalent sigma ~ {true_sig:.2f} (< one-sided 3.5)", abs(sig - true_sig) < 0.25,
      f"got sigma={sig:.3f}")

# --- [4] reproducibility --------------------------------------------------
print("[4] reproducibility: same seed gives the identical estimate")
d = one_param_deck(2500, 2.5, 4.0, seed=11)
p1 = grab(run(d), "highsigma_pfail")
p2 = grab(run(d), "highsigma_pfail")
check("seed 11 reproduces P(fail) exactly", p1 == p2 and not math.isnan(p1),
      f"{p1:.6e} vs {p2:.6e}")

# --- [5] multi-parameter --------------------------------------------------
print("[5] multi-parameter: two independent Gaussians combine correctly")
beta = 4.0
sig_tot = math.sqrt(2.0) * SIG
thr = 2 * MU + beta * sig_tot
deck = f"""* high-sigma two-parameter (series resistors)
.param rr=agauss({MU:g},{AV:g},{S:g}) cc=agauss({MU:g},{AV:g},{S:g})
V1 a 0 DC 1
R1 a b {{rr}}
R2 b 0 {{cc}}
.control
  highsigma 5000 -scale 2.5 -seed 3 -analysis op -metric -1/i(v1) -max {thr:.6f}
  print highsigma_pfail highsigma_sigma
.endc
.end
"""
log = run(deck)
p, sig = grab(log, "highsigma_pfail"), grab(log, "highsigma_sigma")
check("combined sigma-to-fail ~ 4.0 (R_tot ~ N(2000, sqrt2*sig))",
      abs(sig - 4.0) < 0.25, f"got sigma={sig:.3f}")

import shutil
shutil.rmtree(SCRATCH, ignore_errors=True)

print()
if _fail:
    print(f"RESULT: {_fail} check(s) FAILED")
    sys.exit(1)
print("RESULT: all checks passed")
