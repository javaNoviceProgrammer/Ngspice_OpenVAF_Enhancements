#!/usr/bin/env python3
"""Enhancement-206: design centering / yield optimization (`optimize -center`).

This fuses the two subsystems built earlier: the optimizer (Nelder-Mead / LM /
PSO / DE / SA, E-130-197) and the Monte-Carlo yield suite (agauss/mccorr sampling
+ montecarlo specs, E-149-151). The OUTER optimizer searches the nominal design
point; the objective at each candidate is the parametric yield / worst-case Cpk
from an INNER Monte-Carlo run at that point. Maximizing Cpk *centers* the design
under process variation -- a real Spectre/ADS design-centering capability.

    optimize -dparam xc <init> <lo> <hi> ... -center -samples N [-lhs] \
             -analysis <cmd> (-spec <metric> [-max HI] [-min LO])...

The process variation lives in the deck as usual (`.param v=agauss(xc,var,3)`),
re-sampled by each inner reset around the current design center; the design knobs
feed the agauss centers. Because a fixed inner seed gives every candidate the same
process draws (common random numbers), the objective is smooth and the search is
well-behaved -- with Latin-Hypercube sampling the stratified sample-mean is ~0, so
the optimum lands right on the analytic center.

Synthetic problems with KNOWN optimal centers:
  [center]   output ~ N(xc, 0.5), spec [4,6] -> the yield/Cpk-optimal center is the
             midpoint 5; the optimizer must find it from an off-center start (4.0),
             recovering Cpk = 1/(3*0.5) = 0.667.
  [improves] the centered design's yield beats the off-center start's (a montecarlo
             at xc=4.0 sits at ~50%, centered ~95%).
  [twoknob]  two design params with a lower and an upper spec on two outputs -> both
             center on their windows independently.

Every SPICE deck starts with a title line (SPICE treats line 1 as the title!).
"""
import os
import sys
import subprocess

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from _setup import NG as NGSPICE

passed = failed = 0


def check(label, ok, detail=""):
    global passed, failed
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  {detail}" if detail else ""))
    passed += bool(ok); failed += (not ok)


def run(deck):
    open(os.path.join(HERE, "_d.cir"), "w").write(deck)
    r = subprocess.run([NGSPICE, "-b", "_d.cir"], cwd=HERE,
                       capture_output=True, text=True, timeout=600)
    out = r.stdout + r.stderr
    vals = {}
    for line in out.splitlines():
        # nutmeg `print x` emits "x = value"
        if "=" in line and "Reset" not in line and "Circuit" not in line:
            p = line.split("=")
            name = p[0].strip().split()[-1] if p[0].strip() else ""
            try:
                vals[name] = float(p[1].strip().split()[0])
            except (ValueError, IndexError):
                pass
    return vals, out


print("Enhancement-206: design centering / yield optimization")

# ---- 1) known center: output ~ N(xc, 0.5), spec [4,6] -> optimal center 5 -------
deck1 = """* design centering, known optimum xc=5
.param xc = 4.0
.param vo = agauss(xc, 1.5, 3)
V1 out 0 dc {vo}
R1 out 0 1k
.control
  optimize -dparam xc 4.0 3 7 -center -lhs -samples 120 -analysis op -spec v(out) -max 6 -min 4 -seed 3 -maxiter 40
  print xc
  print dcenter_yield
  print dcenter_cpk
.endc
.end
"""
v, out = run(deck1)
xc = v.get("xc")
check("[center] the optimizer centers the design on the analytic optimum (output ~ N(xc,0.5), "
      "spec [4,6] -> center 5), starting from an off-centre 4.0",
      xc is not None and abs(xc - 5.0) < 0.3, f"(found xc = {xc})" if xc else out[-400:])
check("[cpk] the reported worst-case Cpk matches the analytic 1/(3*0.5) = 0.667 and the "
      "yield is high at the centre", "dcenter_cpk" in v and abs(v["dcenter_cpk"] - 0.667) < 0.12
      and v.get("dcenter_yield", 0) > 0.9,
      f"(Cpk {v.get('dcenter_cpk')}, yield {v.get('dcenter_yield')})")
check("[vars] design centering publishes dcenter_yield / dcenter_cpk result vectors",
      "dcenter_yield" in v and "dcenter_cpk" in v)

centered_yield = v.get("dcenter_yield", 0.0)

# ---- 2) the centred design's yield beats the off-centre start's -----------------
deck2 = """* off-centre baseline yield at xc=4.0
.param xc = 4.0
.param vo = agauss(xc, 1.5, 3)
V1 out 0 dc {vo}
R1 out 0 1k
.control
  montecarlo 200 -lhs -analysis op -spec v(out) -max 6 -min 4 -seed 3
  print montecarlo_yield
.endc
.end
"""
v2, out2 = run(deck2)
base = v2.get("montecarlo_yield")
check("[improves] centering raises the yield well above the off-centre start "
      "(a montecarlo at xc=4.0 sits near 50%)",
      base is not None and centered_yield > base + 0.25,
      f"(off-centre {100*base:.0f}% -> centred {100*centered_yield:.0f}%)" if base is not None else out2[-300:])

# ---- 3) two design knobs, a lower and an upper spec -> both centre independently -
deck3 = """* two-knob centering: va centres on [4,6]=5, vb centres on [9,11]=10
.param xa = 4.2
.param xb = 10.6
.param voa = agauss(xa, 1.5, 3)
.param vob = agauss(xb, 1.5, 3)
Va a 0 dc {voa}
Vb b 0 dc {vob}
Ra a 0 1k
Rb b 0 1k
.control
  optimize -dparam xa 4.2 3 7 -dparam xb 10.6 8 12 -center -lhs -samples 90 -analysis op -maxiter 40 -spec v(a) -max 6 -min 4 -spec v(b) -max 11 -min 9 -seed 5
  print xa
  print xb
  print dcenter_yield
.endc
.end
"""
v3, out3 = run(deck3)
xa, xb = v3.get("xa"), v3.get("xb")
check("[twoknob] two design params centre independently on their own spec windows "
      "(xa->5 on [4,6], xb->10 on [9,11])",
      xa is not None and xb is not None and abs(xa - 5.0) < 0.4 and abs(xb - 10.0) < 0.4,
      f"(xa = {xa}, xb = {xb})")

for f in ("_d.cir",):
    p = os.path.join(HERE, f)
    if os.path.exists(p):
        os.remove(p)

print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
