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

print("Enhancement-764: CMA-ES, -polish and -starts")

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
      "optimize: NOTE -- -polish finishes a global method (pso, de, sa, cmaes) with the local one; Nelder-Mead is the local method, so it is ignored" in nm1
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
check("[7] the usage line lists the method and the two flags", "-method nm|lm|pso|de|sa|cmaes]" in run(DIV, "optimize -param R2 1k 1 10k", "us")
      and "[-polish] [-starts k]" in run(DIV, "optimize -param R2 1k 1 10k", "us2"))
uk = run(DIV, "optimize -param R2 1k 1 10k -analysis op -minimize v(out) -method bogus", "uk")
check("[7] an unknown method names the seven: 'use nm, lm, pso, de, sa, cmaes or nsga2'", "(use nm, lm, pso, de, sa, cmaes or nsga2)" in uk)

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

print(f"\n{'ALL PASS' if passed == checks else 'FAILURES'}: {passed}/{checks} passed")
sys.exit(0 if passed == checks else 1)
