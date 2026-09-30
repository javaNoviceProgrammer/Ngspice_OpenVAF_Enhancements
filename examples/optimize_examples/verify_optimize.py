#!/usr/bin/env python3
"""
verify_optimize.py -- Enhancement-130 / -143: the built-in `optimize` command.

`optimize` varies circuit/device parameters (via in-place `alter`), re-runs one
or more analyses, and drives an objective to a minimum, in normalized [0,1]
parameter space. Two modes: a derivative-free Nelder-Mead simplex on a scalar
`-minimize` objective (E-130), and a gradient-based Levenberg-Marquardt
least-squares fit of several weighted `-target`s spread over one or more
`-analysis` stages (E-143).

Each check optimizes a circuit with a KNOWN analytic optimum and confirms the
command reaches it:

  [1] DC divider: minimize (v(out)-0.3)^2 over R1 (R2=1k, Vin=1). v(out)=R2/(R1+R2)
      => R1 = 1k*(1/0.3 - 1) = 2333.3 ohm exactly.
  [2] AC low-pass: minimize (mag(v(out))-0.5)^2 over R1 at 1 kHz (C=100n).
      |H|=1/sqrt(1+(2pi f R C)^2)=0.5 => 2pi f R C = sqrt(3) => R = 2756.6 ohm.
  [3] Two parameters at once (2-D simplex): a divider where R1=3k, R2=2k is the
      unique solution of v(out)=0.4 AND R1+R2=5k (i(V1)=-0.2 mA); minimize the
      compound objective (v(out)-0.4)^2 + (abs(i(v1))-0.2m)^2.
  [4] the inner analyses are quiet by default (few "Doing analysis" banners) but
      `-verbose` prints per-iteration progress.
  [5] OSDI / Verilog-A device: fit a compiled diode's saturation current `is`.

  Enhancement-143 (gradient-based least-squares + multi-analysis objectives):
  [6] LM curve fit: recover R of an RC low-pass (C=100n) from |H| at three
      frequencies -- one -target per frequency, each on its own -analysis stage.
  [7] Two-parameter multi-analysis fit: series R1 + shunt (R2||C), fit R1 and R2
      to a DC gain (op stage) AND an AC magnitude (ac stage) simultaneously.
  [8] Levenberg-Marquardt reaches the same optimum as Nelder-Mead in far fewer
      evaluations on a smooth least-squares problem.
  [9] OSDI diode parameter extraction: recover BOTH `is` and `n` from two I-V
      points (measured from a reference device) by weighted least squares.
  [10] input validation: -method lm without -target, -minimize with -target, and
      multiple -analysis with a scalar -minimize are all rejected.

  Enhancement-144 (optimizing symbolic `.param` values via -dparam):
  [11] scalar `.param` fit: `-dparam rtop` tunes a `.param` used as a device value
      (via alterparam + a quiet re-source) so v(out) = 0.3 => rtop = 2333.3.
  [12] mixed -dparam + -param: a `.param` AND a device (`alter`) parameter fitted
      together (R1={rtop}, R2 altered) => rtop = 3 k, R2 = 2 k. Confirms the deck
      param is re-sourced FIRST and the in-place alter is re-applied after, so the
      two kinds mix correctly.
  [13] `.param` inside an arithmetic device expression (R1={500*k}) => k = 6.
  [14] least-squares `-dparam` fit (`-target`, Levenberg-Marquardt) => rtop = 2333.3.
  [15] the per-iteration re-sources are quiet: the "Reset re-loads" banner appears
      at most once (only the final leave-at-optimum run), not once per evaluation.

  Enhancement-145 (optimizing `.model`-card parameters via -mparam):
  [16] OSDI model param: `-mparam @rmod[r]` fits a Verilog-A resistor's MODEL `r`
      (via altermod) so v(out) = 0.25 => r = 3 k.
  [17] built-in model param: `-mparam @dmod[is]` fits a diode model's `is` so
      I(0.65 V) = 1 mA => is = 1.22e-14.
  [18] determined mixed fit: a model param (`@rmod[r]`) AND an instance param
      (`R2`) fitted together => r = 3 k, R2 = 2 k.
  Enhancement-762 (optimize hunt F1 of 2026-09-29): the stop status.
  [19] "stopped at -maxiter ... NOT converged" (three methods) with its NOTE, a
      converged line unchanged, "NO SOLUTION", "unchanged", "cooling schedule
      complete"; optimize_status / optimize_converged / optimize_cost /
      optimize_evals published and equal to the line.
  Enhancement-763 (optimize hunt F2 of 2026-09-29): a strict parser.
  [20] a bound that is not a number, an init outside the box, a zero or negative
      weight, a -target expression with spaces, a bare -method/-maxiter, two
      -minimize under a scalar method, a knob given twice and a stray token are
      refused with a message; suffixes, a negative target and a raised
      population (with a NOTE) still work; `-minimize -v(out)` is refused with
      the quoting hint and the quoted form runs (hunt F3).
  [19] `-mparam` is the in-place fast path: it does NOT re-source (0 "Reset
      re-loads" banners), unlike -dparam.
  [20] all three knob kinds (`-dparam` + `-mparam` + `-param`) coexist in one run
      and converge.

It is a front-end command, independent of the linear solver, so it is checked once.
"""
import math
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


def run(deck):
    p = os.path.join(HERE, "_opt.cir")
    with open(p, "w") as f:
        f.write(deck)
    try:
        r = subprocess.run([NGSPICE, "-b", p], capture_output=True, text=True, timeout=120)
    finally:
        if os.path.exists(p):
            os.remove(p)
    return r.stdout + r.stderr


def val(out, name):
    m = re.search(rf"(?im)^\s*{re.escape(name)}\s*=\s*([-\d.eE+]+)", out)
    return float(m.group(1)) if m else None


def optval(out, name):
    """the 'name = value' the optimizer prints for a converged parameter"""
    m = re.search(rf"(?im)^\s+{re.escape(name)}\s*=\s*([-\d.eE+]+)\s*$", out)
    return float(m.group(1)) if m else None


print("Enhancement-130: built-in Nelder-Mead optimizer")

# [1] DC divider -> R1 = 2333.3
d1 = ("optimizer dc divider\nV1 in 0 dc 1\nR1 in out 1k\nR2 out 0 1k\n.control\n"
      "optimize -param R1 1k 100 10k -analysis op -minimize (v(out)-0.3)^2 -tol 1e-14\n"
      "let vout = v(out)\nprint vout\n.endc\n.end\n")
o1 = run(d1)
r1 = optval(o1, "r1") or optval(o1, "R1")
vout1 = val(o1, "vout")
check(f"DC divider: R1 -> 2333.3 ohm (got {r1})",
      r1 is not None and abs(r1 - 2333.333) / 2333.333 < 1e-3, str(r1))
check(f"DC divider: v(out) -> 0.3 target (got {vout1})",
      vout1 is not None and abs(vout1 - 0.3) < 1e-4, str(vout1))

# [2] AC low-pass -> R1 = 2756.6
R_ac = math.sqrt(3.0) / (2 * math.pi * 1e3 * 100e-9)     # 2756.6
d2 = ("optimizer ac lowpass\nV1 in 0 ac 1\nR1 in out 1k\nC1 out 0 100n\n.control\n"
      "optimize -param R1 1k 100 100k -analysis ac lin 1 1k 1k "
      "-minimize (mag(v(out))-0.5)^2 -tol 1e-14\n"
      "let g = mag(v(out))\nprint g\n.endc\n.end\n")
o2 = run(d2)
r2 = optval(o2, "r1") or optval(o2, "R1")
g2 = val(o2, "g")
check(f"AC low-pass: R1 -> {R_ac:.1f} ohm (got {r2})",
      r2 is not None and abs(r2 - R_ac) / R_ac < 2e-3, str(r2))
check(f"AC low-pass: |H(1kHz)| -> 0.5 target (got {g2})",
      g2 is not None and abs(g2 - 0.5) < 1e-3, str(g2))

# [3] two-parameter compound objective -> R1=3k, R2=2k
d3 = ("optimizer two-param\nV1 in 0 dc 1\nR1 in out 1k\nR2 out 0 1k\n.control\n"
      "optimize -param R1 1k 100 10k -param R2 1k 100 10k -analysis op "
      "-minimize (v(out)-0.4)^2+(abs(i(v1))-0.2m)^2 -maxiter 400 -tol 1e-15\n"
      "let vout = v(out)\nprint vout\n.endc\n.end\n")
o3 = run(d3)
r1b = optval(o3, "r1") or optval(o3, "R1")
r2b = optval(o3, "r2") or optval(o3, "R2")
check(f"2-param: R1 -> 3k (got {r1b})", r1b is not None and abs(r1b - 3000) / 3000 < 5e-3, str(r1b))
check(f"2-param: R2 -> 2k (got {r2b})", r2b is not None and abs(r2b - 2000) / 2000 < 5e-3, str(r2b))
check(f"2-param: v(out) -> 0.4 (got {val(o3,'vout')})",
      val(o3, "vout") is not None and abs(val(o3, "vout") - 0.4) < 2e-3)

# [4] output is quiet by default; -verbose prints progress
quiet_banners = o1.count("Doing analysis")
check(f"inner analyses are suppressed by default ({quiet_banners} banner(s) for ~67 evals)",
      quiet_banners <= 3, f"{quiet_banners} banners")
o_verbose = run(d1.replace("-tol 1e-14", "-tol 1e-14 -verbose"))
check("-verbose prints per-iteration progress",
      "best cost" in o_verbose)

# [5] OSDI / Verilog-A device: fit a compiled diode's saturation current `is`
osdi = os.path.join(HERE, "optdiode.osdi")
subprocess.run([OPENVAF, os.path.join(HERE, "optdiode.va"), "-o", osdi],
               capture_output=True, text=True, timeout=120)
d5 = ("osdi diode fit\nVd a 0 dc 0.65\nN1 a 0 dmod\n.model dmod optdiode is=1e-15 n=1\n"
      f".control\npre_osdi {osdi}\n"
      "optimize -param " + AT + "n1[is] 1e-15 1e-16 1e-12 -analysis op "
      "-minimize (abs(i(vd))-1m)^2 -tol 1e-24\n"
      "let icurr = abs(i(vd))\nprint icurr\n.endc\n.end\n")
o5 = run(d5)
if os.path.exists(osdi):
    os.remove(osdi)
is_fit = optval(o5, "" + AT + "n1[is]")
icurr = val(o5, "icurr")
check(f"OSDI diode: is fitted so I(0.65V)=1mA (got is={is_fit})",
      is_fit is not None and 1.0e-14 < is_fit < 1.5e-14, str(is_fit))
check(f"OSDI diode: current -> 1 mA target (got {icurr})",
      icurr is not None and abs(icurr - 1e-3) / 1e-3 < 1e-3, str(icurr))

print("\nEnhancement-143: gradient least-squares + multi-analysis objectives")


def nevals(out):
    m = re.search(r"after\s+(\d+)\s+evaluations", out)
    return int(m.group(1)) if m else None

# [6] LM 1-param, 3-target, 3-analysis RC magnitude fit -> R = 2000
Rc, Cc = 2000.0, 100e-9
freqs = (500.0, 1000.0, 2000.0)
Hmag = [1.0 / math.sqrt(1.0 + (2 * math.pi * f * Rc * Cc) ** 2) for f in freqs]
stages = "\n+  ".join(
    f"-analysis ac lin 1 {f:g} {f:g} -target mag(v(out)) {h:.10g}"
    for f, h in zip(freqs, Hmag))
d6 = ("optimizer LM curve fit\nV1 in 0 ac 1\nR1 in out 1k\nC1 out 0 100n\n.control\n"
      f"optimize -param R1 1k 100 10k\n+  {stages}\n+  -tol 1e-12 -maxiter 200\n"
      ".endc\n.end\n")
o6 = run(d6)
r6 = optval(o6, "r1") or optval(o6, "R1")
check(f"LM curve fit (3 targets / 3 stages): R -> 2000 (got {r6})",
      r6 is not None and abs(r6 - 2000.0) / 2000.0 < 2e-3, str(r6))
check("LM curve fit reports a least-squares (sum-sq residual) convergence",
      "sum-sq residual" in o6)

# [7] LM 2-param, DC + AC multi-analysis fit -> R1=3k, R2=2k
R1t, R2t = 3000.0, 2000.0
dc_gain = R2t / (R1t + R2t)                                   # 0.4
fac = 2000.0
Hac = R2t / math.hypot(R1t + R2t, 2 * math.pi * fac * R1t * R2t * Cc)
d7 = ("optimizer LM multi-analysis\nV1 in 0 dc 1 ac 1\nR1 in out 3.3k\n"
      "R2 out 0 3.3k\nC1 out 0 100n\n.control\n"
      "optimize -param R1 3.3k 500 8k -param R2 3.3k 500 8k\n"
      f"+  -analysis op                 -target v(out)      {dc_gain:.10g}\n"
      f"+  -analysis ac lin 1 {fac:g} {fac:g} -target mag(v(out)) {Hac:.10g}\n"
      "+  -tol 1e-13 -maxiter 200\n.endc\n.end\n")
o7 = run(d7)
r1c = optval(o7, "r1") or optval(o7, "R1")
r2c = optval(o7, "r2") or optval(o7, "R2")
check(f"LM DC+AC multi-analysis: R1 -> 3k (got {r1c})",
      r1c is not None and abs(r1c - 3000.0) / 3000.0 < 3e-3, str(r1c))
check(f"LM DC+AC multi-analysis: R2 -> 2k (got {r2c})",
      r2c is not None and abs(r2c - 2000.0) / 2000.0 < 3e-3, str(r2c))
check("LM combines 2 analysis stages in one objective",
      "over 2 analysis stages" in o7)

# [8] LM more efficient than NM on the same least-squares problem
two = ("-analysis ac lin 1 500 500   -target mag(v(out)) %.10g\n"
       "+  -analysis ac lin 1 2000 2000 -target mag(v(out)) %.10g"
       % (Hmag[0], Hmag[2]))
base = ("optimizer method compare\nV1 in 0 ac 1\nR1 in out 1k\nC1 out 0 100n\n"
        ".control\noptimize -param R1 1k 100 10k\n+  " + two +
        "\n+  -method %s -tol 1e-12 -maxiter 400\n.endc\n.end\n")
o_lm, o_nm = run(base % "lm"), run(base % "nm")
n_lm, n_nm = nevals(o_lm), nevals(o_nm)
r_lm = optval(o_lm, "r1") or optval(o_lm, "R1")
r_nm = optval(o_nm, "r1") or optval(o_nm, "R1")
check(f"LM and NM reach the same optimum R=2000 (lm={r_lm}, nm={r_nm})",
      r_lm is not None and r_nm is not None and
      abs(r_lm - 2000.0) < 5.0 and abs(r_nm - 2000.0) < 5.0)
check(f"LM converges in fewer evaluations than NM (lm={n_lm}, nm={n_nm})",
      n_lm is not None and n_nm is not None and n_lm < n_nm,
      f"lm={n_lm} nm={n_nm}")

# [9] OSDI diode: recover BOTH is and n from two measured I-V points
osdi9 = os.path.join(HERE, "optdiode.osdi")
subprocess.run([OPENVAF, os.path.join(HERE, "optdiode.va"), "-o", osdi9],
               capture_output=True, text=True, timeout=120)
ref = ("diode ref iv\nVd a 0 dc 0.6\nN1 a 0 dmod\n"
       ".model dmod optdiode is=1e-14 n=1.2\n.control\n"
       f"pre_osdi {osdi9}\ndc Vd 0.6 0.7 0.1\nprint abs(i(vd))\n.endc\n.end\n")
oref = run(ref)
iv = [float(m) for m in re.findall(r"^\s*\d+\s+[-\d.eE+]+\s+([-\d.eE+]+)",
                                   oref, re.M)]
if len(iv) >= 2:
    i06, i07 = iv[0], iv[1]
    d9 = ("diode ls extraction\nVd a 0 dc 0.6\nN1 a 0 dmod\n"
          ".model dmod optdiode is=5e-15 n=1.0\n.control\n"
          f"pre_osdi {osdi9}\n"
          "optimize -param " + AT + "n1[is] 5e-15 1e-15 5e-14 -param " + AT + "n1[n] 1.0 0.5 2.0\n"
          "+  -analysis dc Vd 0.6 0.7 0.1\n"
          f"+  -target abs(i(vd))[0] {i06:.10g} {1.0 / i06:.10g}\n"
          f"+  -target abs(i(vd))[1] {i07:.10g} {1.0 / i07:.10g}\n"
          "+  -tol 1e-14 -maxiter 200\n.endc\n.end\n")
    o9 = run(d9)
    is9 = optval(o9, "" + AT + "n1[is]")
    n9 = optval(o9, "" + AT + "n1[n]")
    check(f"OSDI diode LS: is -> 1e-14 (got {is9})",
          is9 is not None and abs(is9 - 1e-14) / 1e-14 < 2e-2, str(is9))
    check(f"OSDI diode LS: n -> 1.2 (got {n9})",
          n9 is not None and abs(n9 - 1.2) < 1e-2, str(n9))
else:
    check("OSDI diode LS: measured reference I-V points", False, str(iv))
    check("OSDI diode LS: n -> 1.2", False)
if os.path.exists(osdi9):
    os.remove(osdi9)

# [10] input validation
head = ("optval\nV1 in 0 dc 1\nR1 in out 1k\nR2 out 0 1k\n.control\n")
e_lm = run(head + "optimize -param R1 1k 100 10k -analysis op "
           "-minimize (v(out)-0.3)^2 -method lm\n.endc\n.end\n")
e_both = run(head + "optimize -param R1 1k 100 10k -analysis op "
            "-minimize (v(out)-0.3)^2 -target v(out) 0.3\n.endc\n.end\n")
e_multi = run(head + "optimize -param R1 1k 100 10k -analysis op -analysis op "
             "-minimize (v(out)-0.3)^2\n.endc\n.end\n")
check("rejects -method lm without -target", "requires -target" in e_lm)
check("rejects -minimize together with -target", "not both" in e_both)
check("rejects multiple -analysis with a scalar -minimize",
      "require -target" in e_multi)

print("\nEnhancement-144: optimizing symbolic .param values (-dparam)")

# [11] scalar .param fit: rtop used as a device value -> 2333.3 for v(out)=0.3
d11 = ("optimizer dparam divider\n.param rtop=1k\nV1 in 0 dc 1\nR1 in out {rtop}\n"
       "R2 out 0 1k\n.control\n"
       "optimize -dparam rtop 1k 100 10k -analysis op -minimize (v(out)-0.3)^2 -tol 1e-14\n"
       "op\nlet vout = v(out)\nprint vout\n.endc\n.end\n")
o11 = run(d11)
rt11 = optval(o11, "rtop")
vo11 = val(o11, "vout")
check(f"scalar .param fit: rtop -> 2333.3 (got {rt11})",
      rt11 is not None and abs(rt11 - 2333.333) / 2333.333 < 1e-3, str(rt11))
check(f"scalar .param fit: v(out) -> 0.3 (got {vo11})",
      vo11 is not None and abs(vo11 - 0.3) < 1e-4, str(vo11))

# [12] mixed -dparam (rtop) + -param (R2): rtop=3k, R2=2k for v(out)=0.4 & Rtot=5k
d12 = ("optimizer mixed dparam+param\n.param rtop=1k\nV1 in 0 dc 1\nR1 in out {rtop}\n"
       "R2 out 0 1k\n.control\n"
       "optimize -dparam rtop 1k 100 10k -param R2 1k 100 10k -analysis op "
       "-minimize (v(out)-0.4)^2+(abs(i(v1))-0.2m)^2 -maxiter 400 -tol 1e-15\n"
       ".endc\n.end\n")
o12 = run(d12)
rt12 = optval(o12, "rtop")
r2_12 = optval(o12, "r2") or optval(o12, "R2")
check(f"mixed: .param rtop -> 3k (got {rt12})",
      rt12 is not None and abs(rt12 - 3000) / 3000 < 5e-3, str(rt12))
check(f"mixed: alter R2 -> 2k, survives the re-source (got {r2_12})",
      r2_12 is not None and abs(r2_12 - 2000) / 2000 < 5e-3, str(r2_12))

# [13] .param inside an arithmetic expression: R1 = {500*k}, v(out)=0.25 -> k=6
d13 = ("optimizer dparam expr\n.param k=2\nV1 in 0 dc 1\nR1 in out {500*k}\n"
       "R2 out 0 1k\n.control\n"
       "optimize -dparam k 2 0.5 20 -analysis op -minimize (v(out)-0.25)^2 -tol 1e-16\n"
       ".endc\n.end\n")
o13 = run(d13)
k13 = optval(o13, "k")
check(f".param in expression: k -> 6 (got {k13})",
      k13 is not None and abs(k13 - 6.0) / 6.0 < 2e-3, str(k13))

# [14] least-squares .param fit (LM)
d14 = ("optimizer dparam lsq\n.param rtop=1k\nV1 in 0 dc 1\nR1 in out {rtop}\n"
       "R2 out 0 1k\n.control\n"
       "optimize -dparam rtop 1k 100 10k -analysis op -target v(out) 0.3 -tol 1e-14\n"
       ".endc\n.end\n")
o14 = run(d14)
rt14 = optval(o14, "rtop")
check(f"least-squares .param fit: rtop -> 2333.3 (got {rt14})",
      rt14 is not None and abs(rt14 - 2333.333) / 2333.333 < 1e-3, str(rt14))
check("least-squares .param fit uses Levenberg-Marquardt",
      "Levenberg-Marquardt" in o14)

# [15] the inner re-sources are quiet (one banner for the final run, not ~67)
resets = o11.count("Reset re-loads")
check(f"inner re-sources are silent ({resets} 'Reset re-loads' banner(s) for ~67 evals)",
      resets <= 1, f"{resets} banners")

print("\nEnhancement-145: optimizing .model-card parameters (-mparam)")

# compile the model-parameter Verilog-A resistor (r is a MODEL param)
osdim = os.path.join(HERE, "optresm.osdi")
subprocess.run([OPENVAF, os.path.join(HERE, "optresm.va"), "-o", osdim],
               capture_output=True, text=True, timeout=120)

# [16] OSDI model param: fit `@rmod[r]` so v(out)=0.25 -> r=3k
d16 = ("optimizer mparam osdi\nV1 in 0 dc 1\nN1 in out rmod\nR2 out 0 1k\n"
       ".model rmod optresm r=1k\n.control\n"
       f"pre_osdi {osdim}\n"
       "optimize -mparam " + AT + "rmod[r] 1k 100 10k -analysis op -minimize (v(out)-0.25)^2 -tol 1e-16\n"
       "op\nlet vo = v(out)\nprint vo\n.endc\n.end\n")
o16 = run(d16)
rm16 = optval(o16, "" + AT + "rmod[r]")
vo16 = val(o16, "vo")
check(f"OSDI model param: " + AT + f"rmod[r] -> 3k (got {rm16})",
      rm16 is not None and abs(rm16 - 3000) / 3000 < 2e-3, str(rm16))
check(f"OSDI model param: v(out) -> 0.25 (got {vo16})",
      vo16 is not None and abs(vo16 - 0.25) < 1e-4, str(vo16))

# [17] built-in diode model param: fit `@dmod[is]` so I(0.65V)=1mA
d17 = ("optimizer mparam builtin\nVd a 0 dc 0.65\nD1 a 0 dmod\n"
       ".model dmod d(is=1e-15 n=1)\n.control\n"
       "optimize -mparam " + AT + "dmod[is] 1e-15 1e-16 1e-12 -analysis op "
       "-minimize (abs(i(vd))-1m)^2 -tol 1e-24\n"
       "op\nlet ic = abs(i(vd))\nprint ic\n.endc\n.end\n")
o17 = run(d17)
is17 = optval(o17, "" + AT + "dmod[is]")
ic17 = val(o17, "ic")
check(f"built-in model param: " + AT + f"dmod[is] fitted (got {is17})",
      is17 is not None and 1.0e-14 < is17 < 1.5e-14, str(is17))
check(f"built-in model param: I(0.65V) -> 1 mA (got {ic17})",
      ic17 is not None and abs(ic17 - 1e-3) / 1e-3 < 1e-3, str(ic17))

# [18] determined mixed model + instance fit -> r=3k, R2=2k
d18 = ("optimizer mparam+param\nV1 in 0 dc 1\nN1 in mid rmod\nR2 mid 0 1k\n"
       ".model rmod optresm r=1k\n.control\n"
       f"pre_osdi {osdim}\n"
       "optimize -mparam " + AT + "rmod[r] 1k 100 10k -param R2 1k 100 10k -analysis op "
       "-minimize (v(mid)-0.4)^2+(abs(i(v1))-0.2m)^2 -maxiter 400 -tol 1e-15\n"
       ".endc\n.end\n")
o18 = run(d18)
rm18 = optval(o18, "" + AT + "rmod[r]")
r2_18 = optval(o18, "r2") or optval(o18, "R2")
check(f"mixed model+instance: " + AT + f"rmod[r] -> 3k (got {rm18})",
      rm18 is not None and abs(rm18 - 3000) / 3000 < 5e-3, str(rm18))
check(f"mixed model+instance: R2 -> 2k (got {r2_18})",
      r2_18 is not None and abs(r2_18 - 2000) / 2000 < 5e-3, str(r2_18))

# [19] -mparam alone is in-place: NO re-source (unlike -dparam)
resets16 = o16.count("Reset re-loads")
check(f"-mparam is the in-place fast path (0 re-sources, got {resets16})",
      resets16 == 0, f"{resets16} banners")

# [20] all three knob kinds coexist in one run and converge
d20 = ("optimizer all-three\n.param rtop=1k\nV1 in 0 dc 1\nRtop in a {rtop}\n"
       "N1 a b rmod\nR2 b 0 1k\n.model rmod optresm r=1k\n.control\n"
       f"pre_osdi {osdim}\n"
       "optimize -dparam rtop 1k 100 10k -mparam " + AT + "rmod[r] 1k 100 10k "
       "-param R2 1k 100 10k -analysis op "
       "-target v(a) 0.66667 -target v(b) 0.33333 -maxiter 400 -tol 1e-13\n"
       ".endc\n.end\n")
o20 = run(d20)
m20 = re.search(r"sum-sq residual = ([-\d.eE+]+)", o20)
resid20 = float(m20.group(1)) if m20 else None
has_all3 = (optval(o20, "rtop") is not None and optval(o20, "" + AT + "rmod[r]") is not None
            and (optval(o20, "r2") or optval(o20, "R2")) is not None)
check(f"all three knob kinds (-dparam/-mparam/-param) coexist and converge "
      f"(residual {resid20})",
      resid20 is not None and resid20 < 1e-12 and has_all3, str(resid20))

if os.path.exists(osdim):
    os.remove(osdim)

# --- Enhancement-322: the optimizer shares the .param fast-path. On a circuit
# large enough that a per-eval reset dominates, an OPT_DECKPARAM knob is pushed
# in place (no reset per evaluation). Verify it ARMS and still converges to the
# correct optimum (a big fixed ladder whose input R = .param sets v(n2)). ---
N = 60                                    # 2*N+2 = 122 devices, above the guard
ladder = ["* E-322 large .param optimize", ".param rtop=1k", "V1 n0 0 1",
          "R1 n0 n1 {rtop}"]
for i in range(1, N + 1):
    ladder += [f"Rs{i} n{i} n{i+1} 1k", f"Rp{i} n{i} 0 10k"]
ladder += [".control",
           "optimize -dparam rtop 1k 100 10k -analysis op "
           "-minimize (v(n2)-0.5)^2 -maxiter 120 -tol 1e-12",
           "op", "print v(n2)", ".endc", ".end"]
o22 = run("\n".join(ladder) + "\n")
armed22 = "fast .param path armed" in o22
vn2 = val(o22, "v(n2)")
mobj = re.search(r"objective\s*=\s*([-\d.eE+]+)", o22)
obj22 = float(mobj.group(1)) if mobj else None
check("optimizer arms the .param fast-path on a large circuit (E-322)", armed22)
check(f"large -dparam optimize converges: v(n2) -> 0.5 (got {vn2}, obj {obj22})",
      vn2 is not None and abs(vn2 - 0.5) < 1e-4
      and obj22 is not None and obj22 < 1e-6, f"{vn2}/{obj22}")

# --- Enhancement-323: the fast-path guard is cost-aware. An OSDI (compiled
# Verilog-A) reset re-runs each instance's setup callbacks and is ~30x costlier
# per device than a resistor, so even a SMALL OSDI circuit benefits. The guard
# weights OSDI instances, so a handful of OSDI devices ARMS the fast path where a
# resistor circuit of the same size would (correctly) stay on reset. ---
osdir = os.path.join(HERE, "optres.osdi")
subprocess.run([OPENVAF, os.path.join(HERE, "optres.va"), "-o", osdir],
               capture_output=True, text=True, timeout=120)
osdi_opt = ["osdi resistor .param optimize", ".param rval=1k",
            ".model resmod optres", "V1 in 0 1"]
prev = "in"
for i in range(5):                        # 5 OSDI instances -> weighted well over the guard
    osdi_opt.append(f"Ns{i} {prev} n{i+1} resmod r={{rval}}")
    prev = f"n{i+1}"
osdi_opt += [f"Rload {prev} 0 2k", ".control", f"pre_osdi {osdir}",
             # v(n5) = 2k / (5*rval + 2k); target 0.25 -> rval = 1200
             f"optimize -dparam rval 1k 100 10k -analysis op "
             f"-minimize (v({prev})-0.25)^2 -maxiter 80 -tol 1e-11",
             "op", f"print v({prev})", ".endc", ".end"]
o23 = run("\n".join(osdi_opt) + "\n")
if os.path.exists(osdir):
    os.remove(osdir)
armed23 = "fast .param path armed" in o23
vout23 = val(o23, "v(n5)")
check("small OSDI -dparam optimize arms the fast path (E-323 cost-aware guard)",
      armed23)
check(f"OSDI -dparam optimize converges: v(n5) -> 0.25 (got {vout23})",
      vout23 is not None and abs(vout23 - 0.25) < 1e-3, str(vout23))

# ---- [19] Enhancement-762 (optimize hunt F1 of 2026-09-29): the stop status ----
# Every stop used to be reported as "converged" -- the iteration cap, a run in
# which no evaluation solved, one whose objective never moved -- and only an
# interrupt (E-537) was told apart. The methods now record why they stopped, the
# report opens with the matching phrase (plus a NOTE for the cap), and
# `optimize_status`, `optimize_converged`, `optimize_cost` and `optimize_evals`
# are published for a script to test.
print("\nEnhancement-762: the stop status is reported and published")
TAIL = ("\necho status=$optimize_status conv=$optimize_converged evals=$optimize_evals\n"
        "print optimize_converged optimize_evals optimize_cost\n")
def status_of(out):
    m = re.search(r"(?m)^status=(\S+) conv=(\S+) evals=(\S+)", out)
    return (m.group(1), int(float(m.group(2))), int(float(m.group(3)))) if m else None
def report_line(out):
    m = re.search(r"(?m)^optimize: (.*?), (?:objective|sum-sq residual) = (\S+).*?after (\d+) evaluations", out)
    return (m.group(1), float(m.group(2)), int(m.group(3))) if m else None
DIVD = "opt status\nV1 in 0 dc 1\nR1 in out 1k\nR2 out 0 1k\n.control\n"
# the cap, three methods
for meth, opt in (("Nelder-Mead", "-minimize (v(out)-0.9)^2"), ("Levenberg-Marquardt", "-target v(out) 0.9"),
                  ("particle swarm", "-minimize (v(out)-0.9)^2 -method pso -swarmsize 5 -seed 1")):
    o = run(DIVD + f"optimize -param R2 100 10 100k -analysis op {opt} -maxiter 1" + TAIL + ".endc\n.end\n")
    rl, st = report_line(o), status_of(o)
    check(f"[19] {meth} at -maxiter 1 reports 'stopped at -maxiter (1 iteration) -- NOT converged' (it said converged)",
          rl is not None and rl[0] == "stopped at -maxiter (1 iteration) -- NOT converged", str(rl))
    check(f"[19] ... with the NOTE to raise -maxiter, and optimize_status=maxiter, optimize_converged=0",
          "the iteration cap ended the search" in o and st is not None and st[0] == "maxiter" and st[1] == 0, str(st))
# a normal run: the line is unchanged and the published numbers match it
o = run(DIVD + "optimize -param R2 1k 10 10k -analysis op -minimize (v(out)-0.9)^2" + TAIL + ".endc\n.end\n")
rl, st = report_line(o), status_of(o)
cost_v, evals_v = val(o, "optimize_cost"), val(o, "optimize_evals")
check("[19] a converged run still reads 'converged, objective = ... after N evaluations'",
      rl is not None and rl[0] == "converged", str(rl))
check("[19] ... and publishes optimize_status=converged, optimize_converged=1, optimize_evals=N and optimize_cost equal to the line",
      st is not None and st == ("converged", 1, rl[2]) and evals_v == rl[2] and cost_v is not None
      and abs(cost_v - rl[1]) <= 1e-6 * max(abs(rl[1]), 1e-30) + 1e-300, f"{st} {evals_v} {cost_v}")
# no evaluation solved
o = run(DIVD + "optimize -param R2 1k 10 10k -analysis tran 1 -minimize (v(out)-0.9)^2" + TAIL + ".endc\n.end\n")
rl, st = report_line(o), status_of(o)
check("[19] an analysis that never solves reports 'NO SOLUTION -- no evaluation solved' and optimize_status=nosolve",
      rl is not None and rl[0] == "NO SOLUTION -- no evaluation solved" and st is not None and st[0] == "nosolve" and st[1] == 0, f"{rl} {st}")
# the objective never moved
o = run(DIVD + "optimize -param R9 1k 10 10k -analysis op -minimize (v(out)-0.9)^2" + TAIL + ".endc\n.end\n")
rl, st = report_line(o), status_of(o)
check("[19] a knob the objective does not depend on reports 'unchanged -- nothing was optimised' and optimize_status=unchanged",
      rl is not None and rl[0] == "unchanged -- nothing was optimised" and st is not None and st[0] == "unchanged", f"{rl} {st}")
# annealing completes its schedule
o = run(DIVD + "optimize -param R2 1k 10 10k -analysis op -minimize (v(out)-0.9)^2 -method sa -seed 1 -maxiter 10" + TAIL + ".endc\n.end\n")
rl, st = report_line(o), status_of(o)
check("[19] simulated annealing reports 'cooling schedule complete (10 levels)' and optimize_status=completed, optimize_converged=1",
      rl is not None and rl[0] == "cooling schedule complete (10 levels)" and st == ("completed", 1, rl[2]), f"{rl} {st}")

# ---- [20] Enhancement-763 (optimize hunt F2 of 2026-09-29): a strict parser ------
# The knob's <init> <lo> <hi>, a -target's value and weight went through a
# lenient number parser (`abc` was 0), an init outside the box was clamped in
# silence, a bare option flag ran the default, a stray token was skipped, a
# second scalar objective was dropped, a duplicate knob was altered twice and
# a raised population said nothing. Every one is refused (or said) now.
print("\nEnhancement-763: the knobs, targets and options are refused when they are not what they must be")
def refused(ctl, needle):
    o = run(DIVD + ctl + "\n.endc\n.end\n")
    return (needle in o) and ("optimize: 1 parameter" not in o) and ("converged" not in o), o
for label, ctl, needle in (
    ("a bound that is not a number (`abc`) is refused, not taken as 0",
     "optimize -param R2 1k abc 10k -analysis op -minimize (v(out)-0.9)^2", "<lo> needs a number, not 'abc'"),
    ("an init outside [lo, hi] is refused, not clamped to a bound in silence",
     "optimize -param R2 5k 10 1k -analysis op -minimize (v(out)-0.9)^2", "init 5000 lies outside [10, 1000]"),
    ("a -target weight of 0 is refused (it fitted nothing)",
     "optimize -param R2 1k 10 10k -analysis op -target v(out) 0.9 0", "the weight must be positive (got 0)"),
    ("a -target weight of -1 is refused (the sign vanished in the square)",
     "optimize -param R2 1k 10 10k -analysis op -target v(out) 0.9 -1", "the weight must be positive (got -1)"),
    ("a -target expression with spaces is refused with the one-token hint (it fitted to a target of 0)",
     "optimize -param R2 1k 10 10k -analysis op -target v(out) - v(in) 0.4", "<value> needs a number, not '-'"),
    ("a bare -method is refused (it ran the default)",
     "optimize -param R2 1k 10 10k -analysis op -minimize (v(out)-0.9)^2 -method", "-method needs nm, lm, pso, de, sa, cmaes, bayes or nsga2"),   # E-764 added cmaes, E-765 bayes
    ("a bare -maxiter is refused",
     "optimize -param R2 1k 10 10k -analysis op -minimize (v(out)-0.9)^2 -maxiter", "-maxiter needs a value"),
    ("two -minimize under a scalar method are refused (the second was dropped)",
     "optimize -param R2 1k 10 10k -analysis op -minimize (v(out)-0.9)^2 -minimize (v(out)-0.1)^2", "2 objectives were given"),
    ("a knob given twice is refused",
     "optimize -param R2 1k 10 10k -param R2 2k 10 10k -analysis op -minimize (v(out)-0.9)^2", "'r2' given twice"),
    ("a stray token (`-maxiter5`) refuses the command instead of running with the default",
     "optimize -param R2 1k 10 10k -analysis op -minimize (v(out)-0.9)^2 -maxiter5", "unrecognized token '-maxiter5'; the command is refused"),
):
    ok, o = refused(ctl, needle)
    check(f"[20] {label}", ok, o.strip().splitlines()[-1][:100] if o.strip() else "no output")
# what must still pass: SPICE suffixes, a negative target value, a unit letter
o = run(DIVD + "optimize -param R2 1k 10 1meg -analysis op -target v(out) 0.9 1k\n.endc\n.end\n")
check("[20] SPICE suffixes on a bound (1meg) and a weight (1k) still parse and the fit converges",
      "converged" in o and optval(o, "R2") is not None and abs(optval(o, "R2") - 9000) / 9000 < 1e-3, str(optval(o, "R2")))
o = run("opt neg\nV1 in 0 dc -1\nR1 in out 1k\nR2 out 0 1k\n.control\noptimize -param R2 1k 10 10k -analysis op -target v(out) -0.9\n.endc\n.end\n")
check("[20] a negative -target value (-0.9) is a number, not a flag", "converged" in o and optval(o, "R2") is not None and abs(optval(o, "R2") - 9000) / 9000 < 1e-3, str(optval(o, "R2")))
o = run(DIVD + "optimize -param R2 1k 10 10k -analysis op -minimize (v(out)-0.9)^2 -method de -swarmsize 3 -seed 1\n.endc\n.end\n")
check("[20] a population below the method's minimum is raised WITH a NOTE (-swarmsize 3 -> 5 for differential evolution)",
      "-swarmsize 3 raised to 5" in o and "converged" in o, o.strip().splitlines()[-1][:80])
# hunt F3: an objective that begins with a minus sign
ok, o = refused("optimize -param R2 1k 10 10k -analysis op -minimize -v(out)", "must be quoted")
check("[20] `-minimize -v(out)` is refused with the quoting hint (it printed the usage line and, in batch mode, 'incomplete or empty netlist')", ok,
      o.strip().splitlines()[-1][:100] if o.strip() else "no output")
o = run(DIVD + 'optimize -param R2 1k 10 10k -analysis op -minimize "-v(out)"\n.endc\n.end\n')
check("[20] ... and the quoted form `-minimize \"-v(out)\"` runs: v(out) maximised to the upper bound (R2 = 10k)",
      "converged" in o and optval(o, "R2") is not None and abs(optval(o, "R2") - 10000) / 10000 < 1e-3, str(optval(o, "R2")))

print(f"\n{'ALL PASS' if passed == checks else 'FAILURES'}: {passed}/{checks} passed")
sys.exit(0 if passed == checks else 1)
