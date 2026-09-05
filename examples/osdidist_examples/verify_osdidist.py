#!/usr/bin/env python3
"""Enhancement-554: lognormal and truncated-Gaussian parameter statistics.

`.option osdimc` (E-530) draws every Verilog-A parameter declared with
`(* std= *)` / `(* std_rel= *)` from a gauss or a uniform. A gauss has no
regard for a `from (0:inf)` range: a wide sigma fails trials at the bound,
and the ensemble is truncated by DROPPING them. Two shapes that cannot
violate a range, after Spectre's `lnorm` and the usual truncation:

  (* dist="lognormal" *)   alias lnorm: value = nominal * exp(s z), never
                           crossing zero; `std_rel` is the sigma of the
                           logarithm (about the relative sigma for small s),
                           an absolute `std` is converted at the nominal
  (* trunc=<sigmas> *)     the Gaussian coordinate is confined to |z| <= trunc
                           by deterministic rejection (a draw inside the
                           window is the draw the untruncated parameter would
                           have made); composes with gauss and lognormal;
                           `dist="tgauss"` is gauss with trunc 3
Both inflate under `highsigma -scale` with the matching importance weight
(the truncated normaliser joins the likelihood ratio) and take a `wcd` walk
coordinate (clamped at the truncation). The truncations ride a new optional
side-table symbol, OSDI_STAT_PARAM_TRUNCS; an object without it is read as
untruncated, a simulator without it draws untruncated.

Checks (both solvers, 300 draws each where measured):
  [1]  the clean model compiles with zero warnings; lnorm is an alias
  [2]  the object without a truncation exports no TRUNCS symbol; one with it does
  [3]  lognormal std_rel=0.2: every draw positive, ln(v/nom) has mean 0 and sd 0.2
  [4]  lognormal std=200 on nominal 1000: the same sd of the logarithm, 0.2
  [5]  lognormal std_rel=1.0 on from (0:inf): 300 trials, no range failure
  [6]  the gauss control with the same sigma on the same range fails trials
  [7]  gauss trunc=1: every draw within +-1 sigma, sd 0.54 sigma, none clamped
  [8]  tgauss without trunc is 3 sigma; verbose lines name the shape
  [9]  lognormal + trunc=2: every logarithm within +-2 s
  [10] a truncation changes only the draws that exceeded it (same seed, card, id)
  [11] draws are reproducible run to run
  [12] altermod recenters a lognormal
  [13] highsigma -scale on a truncated gauss estimates the truncated tail
  [14] ...and the untruncated control estimates the plain tail
  [15] diagnostics: trunc < 0 and trunc="abc" are located errors
  [16] diagnostics: trunc on a uniform and trunc without a sigma warn; unknown dist lists lognormal
  [17] a quoted trunc="2.5" is accepted
  [18] wcd: a boundary beyond the truncation is reported as unreachable, one inside is found
"""

import atexit
import math
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from _setup import NG as NGSPICE  # noqa: E402
from _setup import VAF as OPENVAF  # noqa: E402
from _setup import check_both_solvers  # noqa: E402

check_both_solvers(__file__)


def _cleanup():
    for junk in os.listdir(HERE):
        if junk.startswith("_dd_"):
            try:
                os.remove(os.path.join(HERE, junk))
            except OSError:
                pass


atexit.register(_cleanup)

checks = passed = 0


def check(label, ok, detail=""):
    global checks, passed
    checks += 1
    passed += bool(ok)
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  [{detail}]" if detail else ""))


HEAD = '`include "disciplines.vams"\nmodule %s(a,b); inout a,b; electrical a,b;\n'


def compile_va(name, params, body="analog I(a,b) <+ V(a,b)/r;"):
    va = os.path.join(HERE, f"_dd_{name}.va")
    osdi = os.path.join(HERE, f"_dd_{name}.osdi")
    with open(va, "w") as f:
        f.write(HEAD % name + params + "\n" + body + "\nendmodule\n")
    r = subprocess.run([OPENVAF, va, "-o", osdi], cwd=HERE, capture_output=True,
                       text=True, timeout=300)
    return r.returncode, r.stdout + r.stderr, osdi


def run_deck(module, body, tag, seed=7, timeout=600):
    p = os.path.join(HERE, f"_dd_{tag}.cir")
    with open(p, "w") as f:
        f.write(f"osdidist {tag}\nV1 a 0 1\nN1 a 0 mm\n.model mm {module}\n.control\n"
                f"pre_osdi _dd_{module}.osdi\nset osdimc\nset mcseed={seed}\n{body}\n.endc\n.end\n")
    try:
        r = subprocess.run([NGSPICE, "-b", os.path.basename(p)], cwd=HERE,
                           capture_output=True, text=True, timeout=timeout, errors="replace")
        return r.stdout + r.stderr
    except subprocess.TimeoutExpired:
        return "[TIMEOUT]"


def seq(out, name):
    vals = []
    for m in re.finditer(rf"^{re.escape(name)}\s*=\s*(\S+)", out, re.M):
        try:
            vals.append(float(m.group(1)))
        except ValueError:
            pass
    return vals


def draws(out, name):
    """the printed values after the nominal baseline run"""
    return seq(out, name)[1:]


def mean(xs):
    return sum(xs) / len(xs) if xs else float("nan")


def sd(xs):
    m = mean(xs)
    return math.sqrt(sum((x - m) ** 2 for x in xs) / (len(xs) - 1)) if len(xs) > 1 else float("nan")


def trials(prints, n=301):
    return f"repeat {n}\n  op\n  print {prints}\nend"


print("Enhancement-554: lognormal and truncated-Gaussian parameter statistics\n")

# ------------------------------------------------------------- models ---
rc, log, VLOG = compile_va("vlog",
    '(* dist="lognormal", std_rel=0.2 *) parameter real r = 1000.0 from (0:inf);\n'
    '(* dist="lnorm", std=200.0 *)       parameter real q = 1000.0 from (0:inf);\n'
    '(* dist="lognormal", std_rel=1.0 *) parameter real w = 1000.0 from (0:inf);',
    "analog I(a,b) <+ V(a,b)/r + V(a,b)/q + V(a,b)/w;")
check("[1] the lognormal model compiles with zero warnings (lnorm is an alias)",
      rc == 0 and "warning" not in log.lower(), log.strip()[-160:])
rc, log, VTR = compile_va("vtr",
    '(* std=25.0, trunc=1.0 *)                      parameter real r = 1000.0;\n'
    '(* dist="tgauss", std=25.0 *)                  parameter real s = 1000.0;\n'
    '(* dist="lognormal", std_rel=0.2, trunc=2.0 *) parameter real t = 1000.0 from (0:inf);',
    "analog I(a,b) <+ V(a,b)/r + V(a,b)/s + V(a,b)/t;")
rc2, log2, VG = compile_va("vg", '(* std=25.0 *) parameter real r = 1000.0;')
rc3, log3, VT2 = compile_va("vt2", '(* std=25.0, trunc=2.0 *) parameter real r = 1000.0;')
rc4, log4, VGW = compile_va("vgw", '(* std_rel=1.0 *) parameter real w = 1000.0 from (0:inf);',
                            "analog I(a,b) <+ V(a,b)/w;")
assert rc == rc2 == rc3 == rc4 == 0, (log, log2, log3, log4)
nm_log = subprocess.run(["nm", VLOG], capture_output=True, text=True).stdout
nm_tr = subprocess.run(["nm", VTR], capture_output=True, text=True).stdout
check("[2] the object without a truncation exports no TRUNCS symbol; one with it does",
      "OSDI_STAT_PARAM_INFOS" in nm_log and "OSDI_STAT_PARAM_TRUNCS" not in nm_log
      and "OSDI_STAT_PARAM_TRUNCS" in nm_tr)

# ----------------------------------------------------------- lognormal ---
out = run_deck("vlog", trials("@mm[r] @mm[q] @mm[w]"), "lognormal")
r, q, w = draws(out, "@mm[r]"), draws(out, "@mm[q]"), draws(out, "@mm[w]")
Lr = [math.log(v / 1000.0) for v in r if v > 0]
check("[3] lognormal std_rel=0.2: every draw positive, ln(v/nom) has mean 0 and sd 0.2",
      len(r) == 300 and all(v > 0 for v in r) and abs(mean(Lr)) < 0.04 and 0.17 < sd(Lr) < 0.23,
      f"n={len(r)} mean={mean(Lr):.4f} sd={sd(Lr):.4f}")
Lq = [math.log(v / 1000.0) for v in q if v > 0]
check("[4] lognormal std=200 on nominal 1000: the same sd of the logarithm, 0.2",
      len(q) == 300 and all(v > 0 for v in q) and 0.17 < sd(Lq) < 0.23, f"sd={sd(Lq):.4f}")
Lw = [math.log(v / 1000.0) for v in w if v > 0]
check("[5] lognormal std_rel=1.0 on from (0:inf): 300 trials, no range failure, sd 1.0",
      len(w) == 300 and all(v > 0 for v in w) and "out of bounds" not in out
      and 0.85 < sd(Lw) < 1.15, f"n={len(w)} sd={sd(Lw):.3f}")
outg = run_deck("vgw", trials("@mm[w]"), "gausswide")
nfail = outg.count("is out of bounds")
check("[6] the gauss control with the same sigma on the same range fails trials",
      nfail > 20 and "FAILED during setup" in outg, f"{nfail} of 300 out of bounds")

# ----------------------------------------------------------- truncated ---
out = run_deck("vtr", "set osdimc_verbose\n" + trials("@mm[r] @mm[s] @mm[t]"), "trunc")
r, s_, t = draws(out, "@mm[r]"), draws(out, "@mm[s]"), draws(out, "@mm[t]")
dev = [v - 1000.0 for v in r]
check("[7] gauss trunc=1: every draw within +-1 sigma, sd 0.54 sigma, none clamped",
      len(r) == 300 and max(abs(d) for d in dev) <= 25.0 + 1e-9
      and 11.5 < sd(dev) < 15.5 and all(abs(abs(d) - 25.0) > 1e-9 for d in dev),
      f"max|dev|={max(abs(d) for d in dev):.3f} sd={sd(dev):.3f}")
check("[8] tgauss without trunc is 3 sigma; the verbose lines name the shape",
      len(s_) == 300 and max(abs(v - 1000.0) for v in s_) <= 75.0 + 1e-9
      and re.search(r"mm:s = \S+ \(nominal 1000, trunc 3\)", out) is not None
      and re.search(r"mm:t = \S+ \(nominal 1000, lognormal, trunc 2\)", out) is not None
      and re.search(r"mm:r = \S+ \(nominal 1000, trunc 1\)", out) is not None,
      out[-300:].strip())
Lt = [math.log(v / 1000.0) for v in t if v > 0]
check("[9] lognormal + trunc=2: every logarithm within +-2 s",
      len(t) == 300 and all(v > 0 for v in t) and max(abs(x) for x in Lt) <= 0.4 + 1e-12,
      f"max|ln|={max(abs(x) for x in Lt):.4f}")

og = run_deck("vg", trials("@mm[r]"), "plain")
ot = run_deck("vt2", trials("@mm[r]"), "trunc2")
g, tt = draws(og, "@mm[r]"), draws(ot, "@mm[r]")
same = [i for i in range(300) if abs(g[i] - 1000.0) <= 50.0]
diff = [i for i in range(300) if abs(g[i] - 1000.0) > 50.0]
check("[10] a truncation changes only the draws that exceeded it (same seed, card, id)",
      len(g) == len(tt) == 300 and all(g[i] == tt[i] for i in same)
      and len(diff) >= 3 and all(abs(tt[i] - 1000.0) <= 50.0 and tt[i] != g[i] for i in diff),
      f"{len(same)} kept, {len(diff)} redrawn")
ot2 = run_deck("vt2", trials("@mm[r]"), "trunc2b")
check("[11] draws are reproducible run to run", draws(ot2, "@mm[r]") == tt)

out = run_deck("vlog", "altermod mm r=2000\n" + trials("@mm[r]"), "recenter")
r = draws(out, "@mm[r]")
L2 = [math.log(v / 2000.0) for v in r if v > 0]
check("[12] altermod recenters a lognormal", len(r) == 300 and abs(mean(L2)) < 0.04
      and 0.17 < sd(L2) < 0.23, f"mean={mean(L2):.4f} sd={sd(L2):.4f}")

# ------------------------------------------------------------ highsigma ---
HS = ("op\nhighsigma 4000 -scale 2 -seed 3 -analysis op -metric -1/i(v1) -max 1040\n"
      "echo pfail=$highsigma_pfail")
out = run_deck("vt2", HS, "hs_trunc")
p = seq(out, "pfail")
# true P(r > 1040 | |z| <= 2) = (Phi(2) - Phi(1.6)) / (2 Phi(2) - 1) = 0.0336;
# without the truncated normaliser in the weight it would read 0.024
check("[13] highsigma -scale on a truncated gauss estimates the truncated tail (0.0336)",
      len(p) == 1 and 0.027 < p[0] < 0.041, f"pfail={p}")
out = run_deck("vg", HS, "hs_plain")
p = seq(out, "pfail")
check("[14] ...and the untruncated control estimates the plain tail (0.0548)",
      len(p) == 1 and 0.044 < p[0] < 0.066, f"pfail={p}")

# ---------------------------------------------------------- diagnostics ---
rc1, l1, _ = compile_va("dneg", '(* std=25.0, trunc=-1.0 *) parameter real r = 1000.0;')
rc2, l2, _ = compile_va("dstr", '(* std=25.0, trunc="abc" *) parameter real r = 1000.0;')
check("[15] trunc < 0 and trunc=\"abc\" are located errors",
      rc1 != 0 and rc2 != 0 and "expected a positive real literal" in l1
      and "illegal expression supplied to 'trunc' attribute" in l1
      and "illegal expression supplied to 'trunc' attribute" in l2, (l1 + l2).strip()[-200:])
rc3, l3, _ = compile_va("duni", '(* dist="uniform", std=2.0, trunc=2.0 *) parameter real r = 1000.0;')
rc4, l4, _ = compile_va("dalone", '(* trunc=2.0 *) parameter real r = 1000.0;')
rc5, l5, _ = compile_va("dunk", '(* dist="foo", std=2.0 *) parameter real r = 1000.0;')
check("[16] trunc on a uniform and trunc without a sigma warn; an unknown dist lists lognormal",
      rc3 == rc4 == rc5 == 0
      and "'trunc' attribute has no effect on a uniform distribution" in l3
      and "'trunc' attribute has no effect without a 'std' or 'std_rel' attribute" in l4
      and '"lognormal"' in l5 and '"tgauss"' in l5, (l3 + l4 + l5).strip()[-240:])
rc6, l6, _ = compile_va("dquoted", '(* std=25.0, trunc="2.5" *) parameter real r = 1000.0;')
out = run_deck("dquoted", "set osdimc_verbose\n" + trials("@mm[r]", 3), "quoted")
check("[17] a quoted trunc=\"2.5\" is accepted", rc6 == 0 and "warning" not in l6.lower()
      and "trunc 2.5)" in out, out[-200:].strip())

# ------------------------------------------------------------------ wcd ---
rc7, l7, _ = compile_va("vt1", '(* std=25.0, trunc=1.0 *) parameter real r = 1000.0;')
out = run_deck("vt1", "op\nwcd -metric -1/i(v1) -max 1040 -analysis op -maxiter 8\necho ---\n"
               "wcd -metric -1/i(v1) -max 1020 -analysis op -maxiter 8", "wcd")
check("[18] wcd: a boundary beyond the truncation is reported as unreachable, one inside is found",
      rc7 == 0 and "held at the `trunc` truncation of 1 model-declared parameter" in out
      and "zero gradient" not in out and "beta = 0.8000 sigma" in out, out[-300:].strip())

print(f"\n{passed}/{checks} checks passed")
sys.exit(0 if passed == checks else 1)
