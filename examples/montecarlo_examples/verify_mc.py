#!/usr/bin/env python3
"""
verify_mc.py -- verifies Enhancement-66: Monte Carlo simulation with
Verilog-A (OSDI) devices, end-to-end through the committed openvaf-r +
ngspice.

The probe found ngspice's statistical machinery FULLY reaches OSDI
parameters -- a validation deliverable (like Enhancements 57/60). Both
standard MC idioms work:

  1. the RESET idiom: `.param rr = agauss(nom, var, sig)` feeding a
     `.model` card ({rr}) or an instance line (r={rr}); each `reset`
     re-throws the dice and re-runs the OSDI setup (the model card and
     the (*type="instance"*) path both re-evaluate);
  2. the ALTER loop: control-language `sgauss(0)`/`sunif(0)` vectors +
     `alter @n1[r] = value` per run -- no netlist re-parse, faster, and
     `setseed N` makes it exactly reproducible.

Distribution semantics verified against analytic expectations
(ngspice's agauss(nom, avar, sig) draws with sigma = avar/sig;
aunif(nom, avar) is uniform on [nom-avar, nom+avar]).

DOCUMENTED GOTCHA (pinned in check [6]): every textual occurrence of a
random-valued {param} draws INDEPENDENTLY -- two devices written with the
same `{rr}` get different values in the same run. Correlated (matched)
devices need the alter idiom, where one control-language value is
assigned to several instances explicitly.

Every SPICE deck starts with a title line (SPICE treats line 1 as the title!).
"""
import math
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from _setup import VAF as OPENVAF, NG as NGSPICE
from _setup import check_both_solvers as _check_both_solvers; _check_both_solvers(__file__)  # verify under BOTH KLU and Sparse solvers

passed = failed = 0


def check(name, ok, detail=""):
    global passed, failed
    if ok:
        passed += 1
        print(f"  PASS  {name} {detail}")
    else:
        failed += 1
        print(f"  FAIL  {name} {detail}")


def compile_va(src):
    osdi = os.path.splitext(src)[0] + ".osdi"
    out = os.path.join(HERE, osdi)
    if os.path.exists(out):
        os.remove(out)
    r = subprocess.run([OPENVAF, src, "-o", osdi],
                       capture_output=True, text=True, timeout=300, cwd=HERE)
    return r.stdout + r.stderr, os.path.exists(out)


def run_deck(name, deck, timeout=600):
    with open(os.path.join(HERE, name), "w") as f:
        f.write(deck)
    r = subprocess.run([NGSPICE, "-b", name],
                       capture_output=True, text=True, timeout=timeout, cwd=HERE)
    return r.stdout + r.stderr


def grab(log, name):
    m = re.search(rf"{re.escape(name)} = (-?[0-9.eE+-]+)", log)
    return float(m.group(1)) if m else float("nan")


out, ok = compile_va("mc_blocks.va")
if not ok:
    check("blocks compile", False, out.splitlines()[0] if out else "")
    raise SystemExit(1)

print("[1] reset idiom on a .model-card OSDI parameter (agauss)")
log = run_deck("_mc1.cir", """* reset idiom, model card
.control
pre_osdi mc_blocks.osdi
.endc
.param rr = agauss(1k, 100, 3)
V1 a 0 DC 1
N1 a 0 mm
.model mm ores r={rr}
.control
set numdgt=10
setseed 11
let iv = unitvec(200)
let run = 0
dowhile run < 200
  reset
  op
  let iv[run] = i(V1)
  let run = run + 1
end
print mean(iv) stddev(iv)
.endc
.end
""")
mean_i, sd_i = grab(log, "mean(iv)"), grab(log, "stddev(iv)")
# sigma_R = 100/3; sigma_I ~ sigma_R/R^2 = 3.33e-5 (N=200: estimate +-~15%)
check("mean(I) within 3 sigma/sqrt(N) of -1 mA",
      abs(mean_i + 1.003e-3) < 3 * 3.33e-5 / math.sqrt(200), f"({mean_i:.6g})")
check("stddev(I) == sigma_R/R^2 within 25%",
      0.75 * 3.33e-5 < sd_i < 1.25 * 3.33e-5, f"({sd_i:.4g})")

print("[2] reset idiom on an instance-line parameter, readback via @n1[r]")
log = run_deck("_mc2.cir", """* reset idiom, instance line
.control
pre_osdi mc_blocks.osdi
.endc
.param rr = agauss(1k, 100, 3)
V1 a 0 DC 1
N1 a 0 mm r={rr}
.model mm ires
.control
set numdgt=10
setseed 12
let rs = unitvec(200)
let run = 0
dowhile run < 200
  reset
  op
  let rs[run] = @n1[r]
  let run = run + 1
end
print mean(rs) stddev(rs) minimum(rs) maximum(rs)
.endc
.end
""")
mean_r, sd_r = grab(log, "mean(rs)"), grab(log, "stddev(rs)")
mn, mx = grab(log, "minimum(rs)"), grab(log, "maximum(rs)")
check("mean(R) ~ 1k, sigma(R) ~ 33.3 within 25%",
      abs(mean_r - 1000) < 10 and 0.75 * 33.33 < sd_r < 1.25 * 33.33,
      f"(mean={mean_r:.4g}, sd={sd_r:.4g})")
check("all draws within +-5 sigma", mn > 1000 - 5 * 33.33 and mx < 1000 + 5 * 33.33,
      f"([{mn:.4g}, {mx:.4g}])")

print("[3] alter loop with sgauss + setseed: exact reproducibility")
deck3 = """* alter loop, seeded
.control
pre_osdi mc_blocks.osdi
.endc
V1 a 0 DC 1
N1 a 0 mm
.model mm ires
.control
set numdgt=12
setseed 42
let n = 100
let iv = unitvec(n)
let run = 0
dowhile run < n
  let rv = 1k + 33.333*sgauss(0)
  alter @n1[r] = rv
  op
  let iv[run] = i(V1)
  let run = run + 1
end
print mean(iv) stddev(iv)
.endc
.end
"""
log_a = run_deck("_mc3.cir", deck3)
log_b = run_deck("_mc3.cir", deck3)
ma, sa = grab(log_a, "mean(iv)"), grab(log_a, "stddev(iv)")
mb, sb = grab(log_b, "mean(iv)"), grab(log_b, "stddev(iv)")
check("sigma(I) analytic within 25%", 0.75 * 3.33e-5 < sa < 1.25 * 3.33e-5, f"({sa:.4g})")
check("two seeded passes bit-identical", ma == mb and sa == sb)

print("[4] aunif: uniform bounds respected")
log = run_deck("_mc4.cir", """* aunif bounds
.control
pre_osdi mc_blocks.osdi
.endc
.param rr = aunif(1k, 100)
V1 a 0 DC 1
N1 a 0 mm r={rr}
.model mm ires
.control
set numdgt=10
setseed 13
let rs = unitvec(150)
let run = 0
dowhile run < 150
  reset
  op
  let rs[run] = @n1[r]
  let run = run + 1
end
print minimum(rs) maximum(rs) stddev(rs)
.endc
.end
""")
mn, mx, sd = grab(log, "minimum(rs)"), grab(log, "maximum(rs)"), grab(log, "stddev(rs)")
# uniform on [900, 1100]: sigma = 200/sqrt(12) = 57.7
check("draws inside [900, 1100] and spread uniform-like",
      mn >= 900 - 1e-6 and mx <= 1100 + 1e-6 and 0.7 * 57.7 < sd < 1.3 * 57.7,
      f"([{mn:.4g}, {mx:.4g}], sd={sd:.4g})")

print("[5] seeded reset reproducibility (single draw)")
log = run_deck("_mc5.cir", """* seeded reset
.control
pre_osdi mc_blocks.osdi
.endc
.param rr = agauss(1k, 100, 3)
V1 a 0 DC 1
N1 a 0 mm
.model mm ores r={rr}
.control
set numdgt=12
setseed 123
reset
op
print i(V1)
setseed 123
reset
op
print i(V1)
.endc
.end
""")
vals = re.findall(r"i\(v1\) = (-?[0-9.eE+-]+)", log)
check("identical seeds give identical draws",
      len(vals) == 2 and vals[0] == vals[1])

print("[6] gotcha pin: each {param} occurrence draws independently")
log = run_deck("_mc6.cir", """* independent draws
.control
pre_osdi mc_blocks.osdi
.endc
.param rr = agauss(1k, 100, 3)
V1 a 0 DC 1
N1 a 0 mm
.model mm ores r={rr}
V2 b 0 DC 1
R1 b 0 {rr}
.control
set numdgt=10
setseed 14
let dmax = 0
let run = 0
dowhile run < 25
  reset
  op
  let d = abs(i(V1) - i(V2))
  if d > dmax
    let dmax = d
  end
  let run = run + 1
end
print dmax
.endc
.end
""")
dmax = grab(log, "dmax")
check("shared {rr} does NOT correlate devices (dmax > 0, use alter to match)",
      dmax > 1e-7, f"(dmax={dmax:.4g})")

print("[7] nonlinear MC: diode saturation-current spread")
log = run_deck("_mc7.cir", """* diode is_ MC
.control
pre_osdi mc_blocks.osdi
.endc
.param isv = agauss(1e-15, 2e-16, 3)
V1 in 0 DC 5
R1 in a 1
N1 a 0 mm
.model mm odio is_={isv}
.control
set numdgt=10
setseed 15
let vs = unitvec(100)
let run = 0
dowhile run < 100
  reset
  op
  let vs[run] = v(a)
  let run = run + 1
end
print mean(vs) stddev(vs)
.endc
.end
""")
mv, sv = grab(log, "mean(vs)"), grab(log, "stddev(vs)")
# dV/dln(Is) = -vt: sigma_V ~ vt * sigma_Is/Is = 0.026*(2e-16/3)/1e-15 = 1.73 mV
check("diode op-point spread ~ vt*sigma_Is/Is",
      abs(mv - 0.9345) < 5e-3 and 0.5 * 1.73e-3 < sv < 1.5 * 1.73e-3,
      f"(mean={mv:.5g}, sd={sv:.4g})")

# --- MC hunt F1 (2026-09-04): a -spec in double quotes -- the natural spelling
# once it has parentheses or a leading minus -- used to keep its quotes and be
# looked up as one vector NAME, and a spec that resolves to nothing was scored 0
# against its limits: both reported a confident 0% or 100% yield. The quotes are
# now stripped like -analysis's, and an unresolvable spec refuses to report.
log = run_deck("_mc8.cir", """quoted spec, and a spec that names no vector
.param rr = agauss(1k, 100, 1)
v1 1 0 dc 1
r1 1 0 {rr}
.control
montecarlo 20 -seed 7 -spec "-1/i(v1)" -max 1500 -min 500
echo ---nosuch---
montecarlo 20 -seed 7 -spec v(nosuch) -max 1
echo ---after---
.endc
.end
""")
head, _, tail = log.partition("---nosuch---")
m = re.search(r"yield\s*:\s*[0-9.]+%\s*\((\d+) / (\d+) pass\)", head)
check('quoted -spec "-1/i(v1)" is the expression, not a vector name (20/20 pass)',
      m is not None and m.group(1) == "20" and m.group(2) == "20",
      f"({m.group(0).strip() if m else 'no yield line'})")
check("a -spec naming no vector is refused, spec named, no yield reported",
      "spec 1 (v(nosuch)) did not resolve" in tail
      and not re.search(r"yield\s*:", tail.partition("---after---")[0]), "")

# --- MC hunt F2 (2026-09-04): an un-seeded run re-seeds the netlist PRNG from
# the constant 1, so "run it again" returned the same samples and the report
# never said which seed it had used. The default stays; the banner now states
# the seed, an un-seeded run says what repeating it does, and montecarlo_seed
# publishes the seed for scripts.
log = run_deck("_mc9.cir", """the seed is stated
.param rr = agauss(1k, 100, 1)
v1 1 0 dc 1
r1 1 0 {rr}
.control
montecarlo 20 -spec i(v1) -max -0.9m -min -1.1m
print montecarlo_seed
echo ---seeded---
montecarlo 20 -seed 7 -spec i(v1) -max -0.9m -min -1.1m
print montecarlo_seed
.endc
.end
""")
head, _, tail = log.partition("---seeded---")
check("an un-seeded run states 'seed 1 (default)', says a rerun repeats it, publishes montecarlo_seed = 1",
      "1 spec, seed 1 (default)" in head and "running this montecarlo again repeats" in head
      and grab(head, "montecarlo_seed") == 1.0, "")
check("-seed 7 is stated in the banner, with no repeat note, and montecarlo_seed = 7",
      "1 spec, seed 7\n" in tail and "repeats" not in tail
      and grab(tail, "montecarlo_seed") == 7.0, "")

print(f"\n{'ALL PASS' if failed == 0 else 'FAILURES'}: {passed} passed, {failed} failed")
raise SystemExit(1 if failed else 0)
