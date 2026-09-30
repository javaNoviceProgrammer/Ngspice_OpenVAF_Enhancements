#!/usr/bin/env python3
"""
verify_optmethods.py -- the optimization methods added to `optimize` from the
2026-09-29 proposal "more optimizers for optimize" onward, one section group per
method. The `optimize` suite keeps the command's original coverage; this one
checks the methods' claims on standard test functions posed INSIDE ngspice: the
knobs are the dc values of independent sources and a behavioural source computes
the objective from them, so an evaluation is a single operating point and a
method's whole search takes milliseconds.

Enhancement-764: CMA-ES (`-method cmaes`), `-polish` and `-starts <k>`.
  [1] a rotated ellipsoid with a condition number of 1e6 in two knobs, started off
      the valley: CMA-ES reaches the optimum to 1e-12 where the swarm stalls three
      orders above 1e-3 at the same seed and budget (it learns the valley's
      orientation; the swarm clamps its velocities); the report names the method
      and its population (4 + floor(3 ln n) = 6, recombining 3).
  [2] Rosenbrock in four knobs (x = 3u - 1, optimum at u = 2/3): all four knobs
      to 1e-3, the objective below 1e-8.
  [3] hunt O1: the exact six-particle swarm that finished on the bound at 0.036
      still does (byte for byte); with `-polish` Nelder-Mead takes it from the
      swarm's best to below 1e-9 (R2 = 250 to 0.1) and the report says so in two
      lines; CMA-ES alone on the same deck reaches 250.
  [4] hunt F6: from a start the compiled model refuses (g = -1m in [-2m, 5m]),
      Nelder-Mead still reads NO SOLUTION after 3 evaluations; CMA-ES ranks the
      failures last and reaches g = 1m, with E-438's NOTE counting them; a box
      the model refuses entirely ends after three all-failed generations (13
      evaluations for a population of 4) as NO SOLUTION.
  [5] hunt O2 (a knob spanning nine decades, R2 in [1, 1e9], target v(out) = 0.9):
      LM's fixed finite-difference step leaves it at rms 2.5e-5; CMA-ES with
      `-tol 1e-10` reaches rms below 1e-6. The default -tol is a resolution of
      the box (1e-6 of nine decades is a kilo-ohm) and the report shows it: the
      limit is stated, not hidden.
  [6] reproducible: two runs at `-seed 1` are identical to the digit, `-seed 2`
      differs; `-maxiter 1` reads "stopped at -maxiter (1 iteration) -- NOT
      converged" with the NOTE and optimize_status = maxiter; `-verbose` prints
      one line per generation and the last one's count is the total less the
      final apply.
  [7] the arguments: `-swarmsize 2` is raised to 4 with a NOTE; `cma` is an alias;
      `-polish` under Nelder-Mead prints a NOTE and changes nothing (the same
      evaluation count as without it); `-polish` and `-starts` under nsga2, a
      bare `-starts`, `-starts 0` and `-starts abc` are refused with a message.
  [8] `-polish` on a -target fit uses Levenberg-Marquardt: CMA-ES to 1e-13 then
      LM to 1e-17 in three evaluations, R2 = 9000.
  [9] `-starts`: on a double well (global at 0.8, local at 0.2) Nelder-Mead from
      0.15 converges in the wrong basin; `-starts 4` runs five, prints each start's
      verdict and cost, names the winner, polishes it to 0.8 and publishes
      optimize_start; CMA-ES doubles its population per start (the IPOP rule) and
      the swarm gets its own seed per start; the banner states the budget split.
 [10] the E-762 variables for a CMA-ES run: optimize_status, optimize_converged,
      optimize_evals and optimize_cost agree with the report line.

Enhancement-765: Bayesian optimization (`-method bayes`).
 [11] the divider fit (R2 in [1, 100k], target v(out) = 0.9) at a budget of 25:
      the surrogate hands off within 16 evaluations ("surrogate converged after N
      evaluations (...); the budget's remaining M evaluations go to the local
      method", N + M = 25), Levenberg-Marquardt gets "up to M iterations (the
      remaining budget)" and converges to R2 = 9000 within 40 evaluations in all;
      seeds 1 to 5 all end at 9000.
 [12] a smooth bowl in two knobs: the surrogate reaches a cost below 1e-5 in at
      most 25 evaluations (the swarm needs more than 500 for its 2e-9); with a
      budget of 60 the hand-off polish converges below 1e-10 at (0.3, 0.7) in
      fewer evaluations than Nelder-Mead alone.
 [13] the budget is honoured: at 30 the polish runs out of its share and the line
      reads "stopped at -maxiter (N iterations) -- NOT converged" with the NOTE;
      at -maxiter 3 the design is truncated and the line counts "3 evaluations".
 [14] the surrogate's report: predicted cost with a one-sigma range, "fitted to log
      cost", one length scale per knob, and "(no dependence seen)" on exactly the
      knob the objective does not use.
 [15] hunt F6: a start the model refuses is imputed and left (g = 1m, E-438's NOTE
      a minority); a box refused entirely ends after three redrawn designs (13
      evaluations) as NO SOLUTION.
 [16] a knob the objective does not depend on: "unchanged -- nothing was
      optimised" and the length scale says why.
 [17] the arguments: -swarmsize is a NOTE and ignored, `bo` is an alias, two `-seed
      1` runs are identical and `-seed 2` differs, `-verbose` prints "(design)"
      lines then "max EI" lines, one per evaluation.
 [18] `-starts 1`: the banner says "evaluations each", two per-start lines, the
      winner polished.
 [19] optimize_status, optimize_converged and optimize_evals agree with the line.

It is a front-end command, independent of the linear solver, so it is checked once.
"""
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))  # the examples/ dir, for _setup.py
from _setup import NG as NGSPICE, VAF as OPENVAF

checks = passed = 0
AT = "@"   # spelled apart so the mention checker does not read a GitHub handle
def check(label, ok, detail=""):
    global checks, passed
    checks += 1; passed += bool(ok)
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  [{detail}]" if detail and not ok else ""))


def run(body, ctl, tag="om"):
    p = os.path.join(HERE, f"_{tag}.cir")
    with open(p, "w") as f:
        f.write(f"optmethods {tag}\n{body}.control\n{ctl}\n.endc\n.end\n")
    try:
        r = subprocess.run([NGSPICE, "-b", os.path.basename(p)], cwd=HERE, capture_output=True,
                           text=True, timeout=300, errors="replace")
        return r.stdout + r.stderr
    finally:
        if os.path.exists(p):
            os.remove(p)


def knob(out, name):
    m = re.search(r"^\s+" + re.escape(name) + r" = ([-+.\deE]+)\s*$", out, re.M)
    return float(m.group(1)) if m else None

def cost(out):
    m = re.search(r"^optimize: (.*?), (?:objective|sum-sq residual) = ([-+.\deE]+)(?: \(rms ([-+.\deE]+)\))? after (\d+) evaluations", out, re.M)
    return (m.group(1), float(m.group(2)), float(m.group(3)) if m.group(3) else None, int(m.group(4))) if m else (None, None, None, None)

def var(out, name):
    m = re.search(r"(?:^|\s)" + name + r"=(\S*)", out, re.M)
    return m.group(1) if m else None


DIV = "V1 in 0 dc 1\nR1 in out 1k\nR2 out 0 1k\n"
# a rotated ellipsoid, condition number 1e6, optimum at (0.3, 0.7); the start (0.5, 0.9)
# lies off the valley floor x + y = 1
ELL = ("V1 x1 0 dc 0.5\nV2 x2 0 dc 0.9\n"
       "B1 out 0 V = 0.5e6*pow((v(x1)-0.3)+(v(x2)-0.7),2) + 0.5*pow((v(x1)-0.3)-(v(x2)-0.7),2)\n")
ELL_OPT = "-param V1 0.5 0 1 -param V2 0.9 0 1 -analysis op -minimize v(out)"
# Rosenbrock in four knobs, x_i = 3 u_i - 1, optimum at u = 2/3
ROS = ("V1 x1 0 dc 0.5\nV2 x2 0 dc 0.5\nV3 x3 0 dc 0.5\nV4 x4 0 dc 0.5\n"
       "B1 out 0 V = 100*pow((3*v(x2)-1)-pow(3*v(x1)-1,2),2) + pow(1-(3*v(x1)-1),2)"
       " + 100*pow((3*v(x3)-1)-pow(3*v(x2)-1,2),2) + pow(1-(3*v(x2)-1),2)"
       " + 100*pow((3*v(x4)-1)-pow(3*v(x3)-1,2),2) + pow(1-(3*v(x3)-1),2)\n")
# a double well: global minimum at 0.8 (f = 0), local one near 0.238 (f = 6.77e-3)
WELL = "V1 x 0 dc 0.15\nB1 out 0 V = pow(v(x)-0.2,2)*pow(v(x)-0.8,2) + 0.02*pow(v(x)-0.8,2)\n"
WELL_OPT = "-param V1 0.15 0 1 -analysis op -minimize v(out)"

print("Enhancement-764: CMA-ES, -polish and -starts; Enhancement-765: Bayesian optimization")

# [1] the rotated ellipsoid ------------------------------------------------------------
print("\n[1] a rotated ellipsoid (condition 1e6): CMA-ES learns the valley, the swarm clamps")
o_c = run(ELL, f"optimize {ELL_OPT} -method cmaes -seed 1 -maxiter 400 -tol 1e-9", "ell_c")
o_p = run(ELL, f"optimize {ELL_OPT} -method pso -seed 1 -maxiter 400 -tol 1e-9", "ell_p")
ph, fc, _, nc = cost(o_c)
check("[1] CMA-ES converged with the objective below 1e-12 (an ellipsoid whose strong axis is 1e6 times the weak one)",
      ph == "converged" and fc is not None and fc < 1e-12, f"{ph} {fc}")
check("[1] ...at the optimum (0.3, 0.7) to 1e-6",
      knob(o_c, "v1") is not None and abs(knob(o_c, "v1") - 0.3) < 1e-6 and abs(knob(o_c, "v2") - 0.7) < 1e-6,
      f"{knob(o_c, 'v1')} {knob(o_c, 'v2')}")
check("[1] the report names the method and its default population: 'CMA-ES population of 6 (recombining 3), seed 1, up to 400 generations'",
      "(CMA-ES)" in o_c and "optimize: CMA-ES population of 6 (recombining 3), seed 1, up to 400 generations" in o_c)
php, fp, _, _ = cost(o_p)
check("[1] the swarm at the same seed and budget stops above 1e-3 (it 'converged' at 0.27: the stall test on a clamped swarm)",
      fp is not None and fp > 1e-3, f"{php} {fp}")

# [2] Rosenbrock ----------------------------------------------------------------------------
print("\n[2] Rosenbrock in four knobs")
o_r = run(ROS, "optimize -param V1 0.5 0 1 -param V2 0.5 0 1 -param V3 0.5 0 1 -param V4 0.5 0 1 "
               "-analysis op -minimize v(out) -method cmaes -seed 1 -maxiter 600 -tol 1e-9", "ros")
ph, fr, _, _ = cost(o_r)
check("[2] converged with the objective below 1e-8", ph == "converged" and fr is not None and fr < 1e-8, f"{ph} {fr}")
ks = [knob(o_r, f"v{i}") for i in range(1, 5)]
check("[2] all four knobs at 2/3 to 1e-3", all(k is not None and abs(k - 2.0 / 3.0) < 1e-3 for k in ks), f"{ks}")
check("[2] the default population for four knobs is 4 + floor(3 ln 4) = 8", "CMA-ES population of 8 (recombining 4)" in o_r)

# [3] hunt O1 -----------------------------------------------------------------------------
print("\n[3] hunt O1: the six-particle swarm on the bound, polished")
o1 = "optimize -param R2 1k 10 10k -minimize (v(out)-0.2)^2 -analysis op -method pso -seed 1 -swarmsize 6 -maxiter 20"
a = run(DIV, o1, "o1")
b = run(DIV, o1 + " -polish", "o1p")
check("[3] the swarm alone still finishes where the hunt found it: 'converged, objective = 0.0361376 after 67 evaluations', R2 = 10 on the bound",
      "optimize: converged, objective = 0.0361376 after 67 evaluations" in a and knob(a, "r2") == 10.0
      and "finished ON a search bound" in a)
check("[3] -polish: 'optimize: polish -- Nelder-Mead from the best point (cost 0.0361376)'",
      "optimize: polish -- Nelder-Mead from the best point (cost 0.0361376)" in b)
m = re.search(r"^optimize: polish converged -- cost 0\.0361376 -> ([\d.eE+-]+) in (\d+) evaluations", b, re.M)
check("[3] ...'polish converged -- cost 0.0361376 -> <below 1e-9> in <N> evaluations'",
      m is not None and float(m.group(1)) < 1e-9, m.group(0) if m else b[-400:])
ph, f1, _, n1 = cost(b)
check("[3] ...the final line converged below 1e-9 with R2 = 250 to 0.1, and no bound NOTE",
      ph == "converged" and f1 is not None and f1 < 1e-9 and knob(b, "r2") is not None and abs(knob(b, "r2") - 250) < 0.1
      and "finished ON a search bound" not in b, f"{ph} {f1} {knob(b, 'r2')}")
c = run(DIV, "optimize -param R2 1k 10 10k -minimize (v(out)-0.2)^2 -analysis op -method cmaes -seed 1", "o1c")
check("[3] CMA-ES alone on the same deck: R2 = 250 to 0.01 (a mean that settles inside the box, not a swarm clamped at the wall)",
      knob(c, "r2") is not None and abs(knob(c, "r2") - 250) < 0.01, f"{knob(c, 'r2')} {cost(c)}")

# [4] hunt F6: the failing start -------------------------------------------------------------
print("\n[4] hunt F6: a start the model refuses")
osdi = os.path.join(HERE, "optguard.osdi")
subprocess.run([OPENVAF, os.path.join(HERE, "optguard.va"), "-o", osdi], capture_output=True, text=True)
if os.path.exists(osdi):
    GB = "V1 in 0 dc 1\nR1 in out 1k\nN1 out 0 gm\n.model gm optguard\n"
    pre = f"pre_osdi {osdi}\n"
    g_nm = run(GB, pre + "optimize -param " + AT + "n1[g] -1m -2m 5m -analysis op -target v(out) 0.5 -method nm", "gnm")
    g_c = run(GB, pre + "optimize -param " + AT + "n1[g] -1m -2m 5m -analysis op -target v(out) 0.5 -method cmaes -seed 1", "gc")
    g_all = run(GB, pre + "optimize -param " + AT + "n1[g] -1m -2m -0.1m -analysis op -target v(out) 0.5 -method cmaes -seed 1", "gall")
    ph, _, _, n = cost(g_nm)
    check("[4] Nelder-Mead from g = -1m: 'NO SOLUTION -- no evaluation solved' after 3 evaluations (E-762's verdict; unchanged)",
          ph == "NO SOLUTION -- no evaluation solved" and n == 3, f"{ph} {n}")
    ph, fg, rg, n = cost(g_c)
    check("[4] CMA-ES from the same start converged with g = 1m to 1e-6 (rms below 1e-6)",
          ph == "converged" and knob(g_c, AT + "n1[g]") is not None and abs(knob(g_c, AT + "n1[g]") - 1e-3) < 1e-6
          and rg is not None and rg < 1e-6, f"{ph} {knob(g_c, AT + 'n1[g]')} rms {rg}")
    m = re.search(r"NOTE -- (\d+) of (\d+) evaluations did not solve", g_c)
    check("[4] ...E-438's NOTE counts the refused candidates, a minority of the run",
          m is not None and 0 < int(m.group(1)) < int(m.group(2)) // 4, m.group(0) if m else "no NOTE")
    ph, _, _, n = cost(g_all)
    check("[4] a box the model refuses entirely: NO SOLUTION after three all-failed generations (13 evaluations: the start and three populations of 4)",
          ph == "NO SOLUTION -- no evaluation solved" and n == 13, f"{ph} {n}")
    os.remove(osdi)
else:
    for _ in range(4):
        check("[4] optguard.va compiled", False, "openvaf-r failed")

# [5] hunt O2: nine decades ------------------------------------------------------------------
print("\n[5] hunt O2: a knob spanning nine decades")
o2 = "optimize -param R2 1k 1 1e9 -analysis op -target v(out) 0.9"
l = run(DIV, o2 + " -method lm", "o2lm")
d = run(DIV, o2 + " -method cmaes -seed 1", "o2c")
t = run(DIV, o2 + " -method cmaes -seed 1 -tol 1e-10", "o2ct")
_, _, rl, _ = cost(l); _, _, rd, _ = cost(d); ph, _, rt, _ = cost(t)
check("[5] Levenberg-Marquardt on [1, 1e9]: rms above 1e-5 (the hunt's 2.5e-5: a finite-difference step of 1e-3 of the box is a mega-ohm)",
      rl is not None and rl > 1e-5, f"rms {rl}")
check("[5] CMA-ES -tol 1e-10: converged, rms below 1e-6, R2 = 9000 to 0.1 (three orders better on the same box)",
      ph == "converged" and rt is not None and rt < 1e-6 and knob(t, "r2") is not None and abs(knob(t, "r2") - 9000) < 0.1,
      f"{ph} rms {rt} r2 {knob(t, 'r2')}")
check("[5] CMA-ES at the default -tol stops at the box's resolution (rms above 1e-3): -tol is a length in the cube, and 1e-6 of nine decades is a kilo-ohm",
      rd is not None and rd > 1e-3, f"rms {rd}")

# [6] reproducible, the cap, verbose -----------------------------------------------------------
print("\n[6] reproducible from -seed; -maxiter 1; -verbose")
s1a = run(ELL, f"optimize {ELL_OPT} -method cmaes -seed 1 -maxiter 400 -tol 1e-9", "s1a")
s1b = run(ELL, f"optimize {ELL_OPT} -method cmaes -seed 1 -maxiter 400 -tol 1e-9", "s1b")
s2 = run(ELL, f"optimize {ELL_OPT} -method cmaes -seed 2 -maxiter 400 -tol 1e-9", "s2")
def key(o): return [ln for ln in o.splitlines() if ln.startswith("optimize: conv") or ln.startswith("    v")]
check("[6] two runs at -seed 1 print the same report line and knob values to the digit", key(s1a) == key(s1b) and len(key(s1a)) == 3, f"{key(s1a)} {key(s1b)}")
check("[6] -seed 2 differs", key(s1a) != key(s2))
m1 = run(ELL, f"optimize {ELL_OPT} -method cmaes -seed 1 -maxiter 1\necho status=$optimize_status conv=$optimize_converged", "m1")
check("[6] -maxiter 1: 'stopped at -maxiter (1 iteration) -- NOT converged' with the NOTE, optimize_status = maxiter, optimize_converged = 0",
      "optimize: stopped at -maxiter (1 iteration) -- NOT converged, objective" in m1 and "NOTE -- the iteration cap ended" in m1
      and var(m1, "status") == "maxiter" and var(m1, "conv") == "0", m1[-500:])
v = run(ELL, f"optimize {ELL_OPT} -method cmaes -seed 1 -maxiter 400 -tol 1e-9 -verbose", "vb")
gens = re.findall(r"^  gen (\d+)\s+best cost ([\d.eE+-]+)\s+sigma ([\d.eE+-]+)\s+axis ratio ([\d.eE+-]+)\s+\((\d+) evals\)", v, re.M)
_, _, _, nv = cost(v)
check("[6] -verbose prints one line per generation ('gen N  best cost  sigma  axis ratio  (evals)'), numbered from 1, the last count the total less the final apply",
      len(gens) > 50 and [int(g[0]) for g in gens] == list(range(1, len(gens) + 1)) and int(gens[-1][4]) == nv - 1,
      f"{len(gens)} lines, last {gens[-1] if gens else None}, total {nv}")
check("[6] ...sigma shrinks by more than four orders and the axis ratio grows past 100 over the run (the covariance learned the ellipsoid)",
      len(gens) > 2 and float(gens[-1][2]) < 1e-4 * float(gens[0][2]) and float(gens[-1][3]) > 100,
      f"sigma {gens[0][2] if gens else None} -> {gens[-1][2] if gens else None}, axis ratio {gens[-1][3] if gens else None}")

# [7] the arguments --------------------------------------------------------------------------------
print("\n[7] the arguments")
sw = run(ELL, f"optimize {ELL_OPT} -method cma -seed 1 -swarmsize 2 -maxiter 5", "sw2")
check("[7] -swarmsize 2: 'NOTE -- -swarmsize 2 raised to 4 (CMA-ES recombines the best half of at least four candidates)'; 'cma' is an alias",
      "optimize: NOTE -- -swarmsize 2 raised to 4 (CMA-ES recombines the best half of at least four candidates)" in sw
      and "CMA-ES population of 4 (recombining 2)" in sw)
nm0 = run(ELL, f"optimize {ELL_OPT} -method nm", "nm0")
nm1 = run(ELL, f"optimize {ELL_OPT} -method nm -polish", "nm1")
check("[7] -polish under Nelder-Mead: a NOTE that it is ignored, and the run is the one without it (same report line)",
      "optimize: NOTE -- -polish finishes a global method (pso, de, sa, cmaes, bayes) with the local one; Nelder-Mead is the local method, so it is ignored" in nm1
      and cost(nm1) == cost(nm0) and "optimize: polish" not in nm1, f"{cost(nm0)} {cost(nm1)}")
ns_p = run(ELL, "optimize -param V1 0.5 0 1 -analysis op -minimize v(out) -maximize v(x1) -method nsga2 -polish", "nsp")
ns_s = run(ELL, "optimize -param V1 0.5 0 1 -analysis op -minimize v(out) -maximize v(x1) -method nsga2 -starts 2", "nss")
check("[7] -polish and -starts under nsga2 are refused: '... cannot be combined with -method nsga2 (a Pareto front has no single best point)', no run",
      "optimize: -polish cannot be combined with -method nsga2 (a Pareto front has no single best point)" in ns_p
      and "optimize: -starts cannot be combined with -method nsga2" in ns_s and "NSGA-II --" not in ns_p + ns_s)
bs = run(ELL, f"optimize {ELL_OPT} -method cmaes -starts", "bs")
s0 = run(ELL, f"optimize {ELL_OPT} -method cmaes -starts 0", "s0")
sa = run(ELL, f"optimize {ELL_OPT} -method cmaes -starts abc", "sa")
check("[7] a bare -starts, -starts 0 and -starts abc are refused by E-763's readers ('needs a count', 'must be 1 or more (got 0)', 'needs a number, not abc'), no run",
      "optimize: -starts needs a count" in bs and "optimize: -starts must be 1 or more (got 0)" in s0
      and "optimize: -starts needs a number, not 'abc'" in sa and "(CMA-ES)" not in bs + s0 + sa)
check("[7] the usage line lists the methods and the two flags", "-method nm|lm|pso|de|sa|cmaes|bayes]" in run(DIV, "optimize -param R2 1k 1 10k", "us")
      and "[-polish] [-starts k]" in run(DIV, "optimize -param R2 1k 1 10k", "us2"))
uk = run(DIV, "optimize -param R2 1k 1 10k -analysis op -minimize v(out) -method bogus", "uk")
check("[7] an unknown method names the eight: 'use nm, lm, pso, de, sa, cmaes, bayes or nsga2'", "(use nm, lm, pso, de, sa, cmaes, bayes or nsga2)" in uk)

# [8] -polish on a -target fit is Levenberg-Marquardt ---------------------------------------------------
print("\n[8] -polish on a -target fit")
tg = run(DIV, "optimize -param R2 1k 1 100k -analysis op -target v(out) 0.9 -method cmaes -seed 1 -polish", "tgt")
ph, ft, rt, _ = cost(tg)
m = re.search(r"^optimize: polish converged -- cost ([\d.eE+-]+) -> ([\d.eE+-]+) in (\d+) evaluations", tg, re.M)
check("[8] 'polish -- Levenberg-Marquardt from the best point', then LM converged in a handful of evaluations to a lower cost",
      "optimize: polish -- Levenberg-Marquardt from the best point (cost" in tg and m is not None
      and float(m.group(2)) <= float(m.group(1)) and int(m.group(3)) <= 10, m.group(0) if m else tg[-400:])
check("[8] ...the fit: converged, rms below 1e-8, R2 = 9000 to 1e-3",
      ph == "converged" and rt is not None and rt < 1e-8 and knob(tg, "r2") is not None and abs(knob(tg, "r2") - 9000) < 1e-3,
      f"{ph} rms {rt} r2 {knob(tg, 'r2')}")

# [9] -starts ----------------------------------------------------------------------------------------
print("\n[9] -starts on a double well")
w0 = run(WELL, f"optimize {WELL_OPT} -method nm", "w0")
ph, f0, _, _ = cost(w0)
check("[9] Nelder-Mead from 0.15 converges in the wrong basin: v1 = 0.238, objective 6.77e-3",
      ph == "converged" and knob(w0, "v1") is not None and abs(knob(w0, "v1") - 0.238) < 2e-3 and f0 is not None and abs(f0 - 6.77e-3) < 1e-4,
      f"{ph} {knob(w0, 'v1')} {f0}")
w4 = run(WELL, f"optimize {WELL_OPT} -method nm -starts 4 -seed 1\necho start=$optimize_start status=$optimize_status", "w4")
check("[9] -starts 4: the banner '5 starts -- the given point and 4 Latin-hypercube points, 20 iterations each, the winner polished' (100 iterations split five ways)",
      "optimize: 5 starts -- the given point and 4 Latin-hypercube points, 20 iterations each, the winner polished" in w4)
starts = re.findall(r"^optimize: start (\d) of 5 \((the given point|Latin-hypercube point)\) -- (\w+), cost ([\d.eE+-]+) after (\d+) evaluations", w4, re.M)
check("[9] ...five per-start lines, numbered 1 to 5, the first 'the given point' and the rest 'Latin-hypercube point', each with a verdict, a cost and a count",
      [int(s[0]) for s in starts] == [1, 2, 3, 4, 5] and starts[0][1] == "the given point" and all(s[1] == "Latin-hypercube point" for s in starts[1:]),
      f"{starts}")
win = re.search(r"^optimize: start (\d) of 5 won \(cost ([\d.eE+-]+)\)", w4, re.M)
check("[9] ...a winner line naming a start whose cost is the lowest of the five, below 1e-9, and not the given point",
      win is not None and float(win.group(2)) == min(float(s[3]) for s in starts) and float(win.group(2)) < 1e-9 and win.group(1) != "1",
      win.group(0) if win else w4[-400:])
ph, fw, _, _ = cost(w4)
check("[9] ...polished and converged at the global minimum, v1 = 0.8 to 1e-3, optimize_start = the winner, optimize_status = converged",
      ph == "converged" and knob(w4, "v1") is not None and abs(knob(w4, "v1") - 0.8) < 1e-3
      and win is not None and var(w4, "start") == win.group(1) and var(w4, "status") == "converged",
      f"{ph} {knob(w4, 'v1')} start={var(w4, 'start')} status={var(w4, 'status')}")
wc = run(WELL, f"optimize {WELL_OPT} -method cmaes -seed 1 -starts 2", "wc")
check("[9] CMA-ES -starts 2: three runs, the winner polished with Nelder-Mead, v1 = 0.8 to 1e-3",
      "optimize: 3 starts -- the given point and 2 Latin-hypercube points, 34 iterations each" in wc
      and len(re.findall(r"^optimize: start \d of 3 \(", wc, re.M)) == 3 and "optimize: polish -- Nelder-Mead from the best point" in wc
      and knob(wc, "v1") is not None and abs(knob(wc, "v1") - 0.8) < 1e-3, f"{knob(wc, 'v1')} {cost(wc)}")
pops = re.findall(r"^optimize: start \d of 3 \((?:the given point|Latin-hypercube point), population (\d+)\)", wc, re.M)
wcv = run(WELL, f"optimize {WELL_OPT} -method cmaes -seed 1 -starts 2 -verbose", "wcv")
gl = re.findall(r"^\s+gen (\d+)\s+.*\((\d+) evals\)", wcv, re.M)
firsts = [int(gl[i][1]) - (int(gl[i - 1][1]) if i else 0) for i in range(len(gl)) if gl[i][0] == "1"]
check("[9] ...the IPOP rule: the population doubles per start -- the per-start lines read 'population 4', 8, 16, and -verbose's first generation of each start counts that many evaluations",
      pops == ["4", "8", "16"] and firsts == [4, 8, 16], f"lines {pops}, first generations {firsts}")
wp = run(WELL, f"optimize {WELL_OPT} -method pso -seed 1 -starts 2 -swarmsize 5 -maxiter 30", "wp")
sc = re.findall(r"^optimize: start \d of 3 \(.*\) -- \w+, cost ([\d.eE+-]+) after", wp, re.M)
check("[9] the swarm with -starts 2: three runs of ten iterations with their own seeds (three distinct costs), polished to 0.8",
      len(sc) == 3 and len(set(sc)) == 3 and knob(wp, "v1") is not None and abs(knob(wp, "v1") - 0.8) < 1e-3, f"{sc} {knob(wp, 'v1')}")

# [10] the E-762 variables ------------------------------------------------------------------------------
print("\n[10] the published outcome of a CMA-ES run")
pv = run(ELL, f"optimize {ELL_OPT} -method cmaes -seed 1 -maxiter 400 -tol 1e-9\necho status=$optimize_status conv=$optimize_converged evals=$optimize_evals cost=$optimize_cost", "pv")
ph, fpv, _, npv = cost(pv)
check("[10] optimize_status = converged, optimize_converged = 1, optimize_evals and optimize_cost equal to the report line",
      var(pv, "status") == "converged" and var(pv, "conv") == "1" and var(pv, "evals") is not None and int(float(var(pv, "evals"))) == npv
      and var(pv, "cost") is not None and abs(float(var(pv, "cost")) - fpv) <= 1e-6 * max(1.0, abs(fpv)),
      f"status={var(pv, 'status')} conv={var(pv, 'conv')} evals={var(pv, 'evals')}/{npv} cost={var(pv, 'cost')}/{fpv}")

# ============================== Enhancement-765 ==============================================
print("\nEnhancement-765: Bayesian optimization")
BOWL = "V1 x1 0 dc 0.9\nV2 x2 0 dc 0.1\nB1 out 0 V = pow(v(x1)-0.3,2) + pow(v(x2)-0.7,2)\n"
BOWL_OPT = "-param V1 0.9 0 1 -param V2 0.1 0 1 -analysis op -minimize v(out)"
BOWL3 = "V1 x1 0 dc 0.9\nV2 x2 0 dc 0.1\nV3 x3 0 dc 0.5\nB1 out 0 V = pow(v(x1)-0.3,2) + pow(v(x2)-0.7,2)\n"
DIVFIT = "optimize -param R2 1k 1 100k -analysis op -target v(out) 0.9"
HAND = re.compile(r"^optimize: surrogate converged after (\d+) evaluations \((.*?)\); the budget's remaining (\d+) evaluations? go(?:es)? to the local method", re.M)

# [11] the divider fit ------------------------------------------------------------------------------
print("\n[11] the divider fit at a budget of 25 evaluations")
d1 = run(DIV, DIVFIT + " -method bayes -seed 1 -maxiter 25", "d1")
h = HAND.search(d1)
check("[11] the banner: 'Bayesian optimization -- a Gaussian-process surrogate (Matern 5/2, a length scale per knob) and expected improvement, seed 1, a budget of 25 evaluations (4 in the initial design)'",
      "optimize: Bayesian optimization -- a Gaussian-process surrogate (Matern 5/2, a length scale per knob) and expected improvement, seed 1, a budget of 25 evaluations (4 in the initial design)" in d1
      and ", Bayesian optimization" in d1)
check("[11] the hand-off: 'surrogate converged after N evaluations (it expects less than a thousandth of the cost spread); the budget's remaining M evaluations go to the local method', N <= 16, N + M = 25",
      h is not None and int(h.group(1)) <= 16 and int(h.group(1)) + int(h.group(3)) == 25 and h.group(2) == "it expects less than a thousandth of the cost spread",
      h.group(0) if h else d1[-600:])
check("[11] ...'polish -- Levenberg-Marquardt from the best point (cost ...), up to M iterations (the remaining budget)' and 'polish converged'",
      h is not None and re.search(r"^optimize: polish -- Levenberg-Marquardt from the best point \(cost [\d.eE+-]+\), up to " + h.group(3) + r" iterations \(the remaining budget\)", d1, re.M) is not None
      and "optimize: polish converged -- cost" in d1, d1[-600:])
ph, fd, rd, nd = cost(d1)
check("[11] ...converged, rms below 1e-8, R2 = 9000 to 0.01, within 40 evaluations in all (Nelder-Mead alone takes 35 to rms 5e-7, the swarm hundreds)",
      ph == "converged" and rd is not None and rd < 1e-8 and knob(d1, "r2") is not None and abs(knob(d1, "r2") - 9000) < 0.01 and nd <= 40,
      f"{ph} rms {rd} r2 {knob(d1, 'r2')} evals {nd}")
seeds_ok = []
for s in (2, 3, 4, 5):
    o = run(DIV, DIVFIT + f" -method bayes -seed {s} -maxiter 25", f"d{s}")
    seeds_ok.append(cost(o)[0] == "converged" and knob(o, "r2") is not None and abs(knob(o, "r2") - 9000) < 0.01 and cost(o)[3] <= 40)
check("[11] seeds 2 to 5 at the same budget all hand off and end at R2 = 9000 within 40 evaluations", all(seeds_ok), f"{seeds_ok}")

# [12] the bowl --------------------------------------------------------------------------------------------
print("\n[12] a smooth bowl in two knobs")
b60 = run(BOWL, f"optimize {BOWL_OPT} -method bayes -seed 1 -maxiter 60", "b60")
h = HAND.search(b60)
m = re.search(r"^optimize: polish -- Nelder-Mead from the best point \(cost ([\d.eE+-]+)\), up to (\d+) iterations \(the remaining budget\)", b60, re.M)
check("[12] the surrogate hands off within 25 evaluations with its best below 1e-5 (the basin found)",
      h is not None and int(h.group(1)) <= 25 and m is not None and float(m.group(1)) < 1e-5, f"{h.group(0) if h else None} | {m.group(0) if m else None}")
ph, fb, _, nb = cost(b60)
nm_b = run(BOWL, f"optimize {BOWL_OPT} -method nm", "bnm")
ps_b = run(BOWL, f"optimize {BOWL_OPT} -method pso -seed 1", "bps")
check("[12] ...with a budget of 60 the Nelder-Mead polish converges below 1e-10 at (0.3, 0.7) to 1e-4, in fewer evaluations than Nelder-Mead alone",
      ph == "converged" and fb is not None and fb < 1e-10 and abs(knob(b60, "v1") - 0.3) < 1e-4 and abs(knob(b60, "v2") - 0.7) < 1e-4
      and cost(nm_b)[3] is not None and nb < cost(nm_b)[3], f"{ph} {fb} evals {nb} vs nm {cost(nm_b)[3]}")
check("[12] the swarm on the same bowl spends more than 500 evaluations (it 'converged' at 2e-9 after 1153)",
      cost(ps_b)[3] is not None and cost(ps_b)[3] > 500, f"{cost(ps_b)}")

# [13] the budget is honoured ---------------------------------------------------------------------------------
print("\n[13] the budget is honoured")
b30 = run(BOWL, f"optimize {BOWL_OPT} -method bayes -seed 1 -maxiter 30", "b30")
h = HAND.search(b30)
check("[13] -maxiter 30: the hand-off leaves the polish its share and the report reads 'stopped at -maxiter (M iterations) -- NOT converged' with the NOTE, M = 30 - N",
      h is not None and re.search(r"^optimize: stopped at -maxiter \(" + h.group(3) + r" iterations\) -- NOT converged, objective", b30, re.M) is not None
      and "NOTE -- the iteration cap ended" in b30, b30[-700:])
m3 = run(BOWL, f"optimize {BOWL_OPT} -method bayes -seed 1 -maxiter 3\necho status=$optimize_status", "m3")
check("[13] -maxiter 3: a design of 3 ('3 in the initial design'), 'stopped at -maxiter (3 evaluations) -- NOT converged' -- the cap is counted in evaluations here -- and optimize_status = maxiter",
      "a budget of 3 evaluations (3 in the initial design)" in m3 and "optimize: stopped at -maxiter (3 evaluations) -- NOT converged, objective" in m3 and var(m3, "status") == "maxiter", m3[-500:])

# [14] the surrogate's report -------------------------------------------------------------------------------------
print("\n[14] the surrogate's report")
b3 = run(BOWL3, "optimize -param V1 0.9 0 1 -param V2 0.1 0 1 -param V3 0.5 0 1 -analysis op -minimize v(out) -method bayes -seed 1 -maxiter 40", "b3")
m = re.search(r"^optimize: surrogate -- predicted cost ([\d.eE+-]+) \(([\d.eE+-]+) \.\. ([\d.eE+-]+), one sigma\) at the optimum after (\d+) evaluations, fitted to (log cost|the cost); length scales \(box widths\):(.*)$", b3, re.M)
check("[14] 'surrogate -- predicted cost X (lo .. hi, one sigma) at the optimum after N evaluations, fitted to log cost; length scales (box widths): ...', lo <= X <= hi",
      m is not None and float(m.group(2)) <= float(m.group(1)) <= float(m.group(3)) and m.group(5) == "log cost", m.group(0) if m else b3[-600:])
check("[14] ...the third knob, which the objective does not use, reads '(no dependence seen)' and the two it uses do not",
      m is not None and re.search(r" v3 \d[\d.eE+-]* \(no dependence seen\)", m.group(6)) is not None and m.group(6).count("(no dependence seen)") == 1
      and re.search(r" v1 [\d.eE+-]+ v2 [\d.eE+-]+ v3", m.group(6)) is not None, m.group(6) if m else "no line")

# [15] hunt F6 -------------------------------------------------------------------------------------------------------
print("\n[15] hunt F6 under the surrogate")
subprocess.run([OPENVAF, os.path.join(HERE, "optguard.va"), "-o", osdi], capture_output=True, text=True)
if os.path.exists(osdi):
    GB = "V1 in 0 dc 1\nR1 in out 1k\nN1 out 0 gm\n.model gm optguard\n"
    pre = f"pre_osdi {osdi}\n"
    g1 = run(GB, pre + "optimize -param " + AT + "n1[g] -1m -2m 5m -analysis op -target v(out) 0.5 -method bayes -seed 1 -maxiter 30", "gb1")
    g2 = run(GB, pre + "optimize -param " + AT + "n1[g] -1m -2m -0.1m -analysis op -target v(out) 0.5 -method bayes -seed 1 -maxiter 30", "gb2")
    ph, _, rg, ng = cost(g1)
    mm = re.search(r"NOTE -- (\d+) of (\d+) evaluations did not solve", g1)
    check("[15] from g = -1m (refused): the failures are imputed, the surrogate hands off, LM converges at g = 1m to 1e-6 within 30 evaluations; E-438's NOTE counts a minority",
          ph == "converged" and knob(g1, AT + "n1[g]") is not None and abs(knob(g1, AT + "n1[g]") - 1e-3) < 1e-6 and ng <= 30
          and mm is not None and int(mm.group(1)) < int(mm.group(2)) // 3, f"{ph} g {knob(g1, AT + 'n1[g]')} evals {ng} {mm.group(0) if mm else ''}")
    ph, _, _, ng = cost(g2)
    check("[15] a box refused entirely: three designs of 4 are drawn and nothing solves; NO SOLUTION after 13 evaluations (12 and the final apply)",
          ph == "NO SOLUTION -- no evaluation solved" and ng == 13, f"{ph} {ng}")
    os.remove(osdi)
else:
    for _ in range(2):
        check("[15] optguard.va compiled", False, "openvaf-r failed")

# [16] a knob the objective ignores -----------------------------------------------------------------------------------
print("\n[16] a knob the objective does not depend on")
u = run("V1 x 0 dc 0.5\nV2 y 0 dc 0.5\nB1 out 0 V = pow(v(y)-0.3,2)\n", "optimize -param V1 0.5 0 1 -analysis op -minimize v(out) -method bayes -seed 1 -maxiter 30", "unch")
check("[16] 'unchanged -- nothing was optimised' after the design, and the surrogate line reads 'v1 100 (no dependence seen)'",
      "optimize: unchanged -- nothing was optimised, objective = 0.04 after" in u and "length scales (box widths): v1 100 (no dependence seen)" in u, u[-500:])

# [17] the arguments -------------------------------------------------------------------------------------------------------
print("\n[17] the arguments")
sw = run(BOWL, f"optimize {BOWL_OPT} -method bo -seed 1 -maxiter 12 -swarmsize 9", "bsw")
check("[17] -swarmsize under the surrogate: 'NOTE -- -swarmsize does not apply to Bayesian optimization (no population; ignored)'; 'bo' is an alias",
      "optimize: NOTE -- -swarmsize does not apply to Bayesian optimization (no population; ignored)" in sw and "(Bayesian optimization)" in sw)
s1 = run(BOWL, f"optimize {BOWL_OPT} -method bayes -seed 1 -maxiter 30", "bs1")
s2 = run(BOWL, f"optimize {BOWL_OPT} -method bayes -seed 2 -maxiter 30", "bs2")
def bkey(o): return [ln for ln in o.splitlines() if ln.startswith("optimize: surrogate") or ln.startswith("optimize: stop") or ln.startswith("optimize: conv") or ln.startswith("    v")]
check("[17] two runs at -seed 1 are identical to the digit (the surrogate line, the report line, the knobs); -seed 2 differs",
      bkey(s1) == bkey(b30) and len(bkey(s1)) >= 4 and bkey(s1) != bkey(s2), f"{bkey(s1)[:2]} vs {bkey(b30)[:2]}")
vb = run(BOWL, f"optimize {BOWL_OPT} -method bayes -seed 1 -maxiter 20 -verbose", "bvb")
ev = re.findall(r"^  eval (\d+)\s+cost [\d.eE+-]+\s+best [\d.eE+-]+\s+(\(design\)|max EI [\d.eE+-]+)$", vb, re.M)
check("[17] -verbose: one line per evaluation, numbered from 1, the first six '(design)' and the rest 'max EI <value>' (up to the hand-off)",
      len(ev) >= 7 and [int(e[0]) for e in ev] == list(range(1, len(ev) + 1)) and all(e[1] == "(design)" for e in ev[:6]) and all(e[1].startswith("max EI") for e in ev[6:]),
      f"{len(ev)} lines: {ev[:7]}")

# [18] -starts -------------------------------------------------------------------------------------------------------------
print("\n[18] -starts under the surrogate")
st = run(BOWL, f"optimize {BOWL_OPT} -method bayes -seed 1 -maxiter 40 -starts 1", "bst")
check("[18] the banner says '2 starts -- the given point and 1 Latin-hypercube point, 20 evaluations each, the winner polished', two per-start lines, a winner, the winner's polish below 1e-9 at (0.3, 0.7), and no per-start hand-off line (the winner is polished anyway)",
      "optimize: 2 starts -- the given point and 1 Latin-hypercube point, 20 evaluations each, the winner polished" in st
      and len(re.findall(r"^optimize: start \d of 2 \(", st, re.M)) == 2 and re.search(r"^optimize: start \d of 2 won", st, re.M) is not None
      and "optimize: polish -- Nelder-Mead from the best point" in st and cost(st)[1] is not None and cost(st)[1] < 1e-9
      and abs(knob(st, "v1") - 0.3) < 1e-3 and abs(knob(st, "v2") - 0.7) < 1e-3 and "surrogate converged after" not in st,
      st[-900:])

# [19] the variables -------------------------------------------------------------------------------------------------------
print("\n[19] the published outcome")
pv = run(DIV, DIVFIT + " -method bayes -seed 1 -maxiter 25\necho status=$optimize_status conv=$optimize_converged evals=$optimize_evals", "bpv")
ph, _, _, npv = cost(pv)
check("[19] optimize_status = converged, optimize_converged = 1, optimize_evals equal to the line", var(pv, "status") == "converged" and var(pv, "conv") == "1"
      and var(pv, "evals") is not None and int(float(var(pv, "evals"))) == npv, f"{var(pv, 'status')} {var(pv, 'conv')} {var(pv, 'evals')}/{npv}")

print(f"\n{'ALL PASS' if passed == checks else 'FAILURES'}: {passed}/{checks} passed")
sys.exit(0 if passed == checks else 1)
