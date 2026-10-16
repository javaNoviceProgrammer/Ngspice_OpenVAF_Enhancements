#!/usr/bin/env python3
"""verify_convtest.py -- Enhancement-889: the device convergence tests decide.

F1 of the nonlinear correctness campaign of 2026-10-15. Every built-in
device's convergence test ran and was ignored (NIiter overwrote the count with
CKTconvTest's return code), most read the point they had been loaded at, and
a Verilog-A device had none. An operating point was accepted as soon as no
node moved more than reltol of its voltage in a step -- 0.1 V at 100 V.

  [1] a diode across a 794 kOhm resistor, both between two 100 V nodes,
      converges off: |vd| < 1 uV, |I(r)| < 1 pA (E-888: 0.679 V forward,
      2.47 mA through the diode, 0.86 uA through the resistor)
  [2] the same with a Verilog-A diode (E-888: 0.679 V)
  [3] the same with a Verilog-A diode behind a series resistance on an
      internal node (E-888: 0.679 V)
  [4] an npn's base across the resistor: |vbe| < 1 uV (E-888: 0.552 V)
  [5] a level-1 MOSFET's bulk junction, started forward by a nodeset:
      |vbd| < 0.1 mV (E-888: 0.673 V)
  [6] a dc temp sweep of a diode at default tolerances is within 30 uV of the
      same sweep at reltol 1e-9 at every point, its current within reltol
      (E-888: 0.47 mV, 2 % of the current)
  [7] an npn that an ideal source forward-biases by 2 V -- its collector
      current the near-cancelling difference of 1e13 A transport currents --
      still converges: the tests ignore steps at the rounding of the unknowns
      (without that: no convergence after 39 000 iterations)
  [8] a diode marked `off` that the circuit drives forward converges in at
      most 20 iterations, within reltol of the point it reaches without `off`:
      the tests wait for MODEINITFLOAT (run in MODEINITFIX, where the diode is
      held at 0 V: 351 iterations, through dynamic gmin stepping; E-888: 0.12 mV
      apart, 0.5 % of the current)
  [9] a closed Verilog-A switch between two 100 V nodes converges in at most
      10 iterations

Exit code 0 = pass.
"""
import os
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from _setup import VAF as OPENVAF, NG as NGSPICE  # noqa: E402
from _setup import check_both_solvers as _check_both_solvers; _check_both_solvers(__file__)  # noqa: E402

WORK = tempfile.mkdtemp(prefix="convtest_")
checks = passed = 0


def check(label, ok, detail=""):
    global checks, passed
    checks += 1
    passed += bool(ok)
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  [{detail}]" if detail else ""))


def compile_va(name):
    osdi = os.path.join(WORK, name + ".osdi")
    r = subprocess.run([OPENVAF, os.path.join(HERE, name + ".va"), "-o", osdi],
                       capture_output=True, text=True, timeout=600)
    if not os.path.exists(osdi):
        print(r.stdout + r.stderr)
    return osdi


def run(tag, text):
    path = os.path.join(WORK, tag + ".cir")
    with open(path, "w") as f:
        f.write(text)
    r = subprocess.run([NGSPICE, "-b", path], cwd=WORK, capture_output=True, text=True, timeout=300)
    return r.stdout + r.stderr


def num(out, name):
    m = re.search(r"^%s\s*=\s*(\S+)" % re.escape(name), out, re.M)
    try:
        return float(m.group(1)) if m else None
    except ValueError:
        return None


def iters(out):
    m = re.search(r"Total iterations = (\d+)", out)
    return int(m.group(1)) if m else None


for m in ("ctdio", "ctdiors", "ctsw"):
    compile_va(m)

# a junction across a resistor, both between node 3 (driven to 100 V) and
# node 4, which nothing else touches: the only solution is 0 V across them
HIGH = """* %s across a resistor between two 100 V nodes
i1 0 3 dc 1e-4
r1 3 0 1e6
r2 4 3 793581
%s
.control
%s
set numdgt=12
op
let vd = v(4)-v(3)
print vd
let ir = (v(4)-v(3))/793581
print ir
rusage totiter
.endc
.end
"""

out = run("dio", HIGH % ("a diode", "d1 4 3 dm\n.model dm d is=1e-14", ""))
vd, ir = num(out, "vd"), num(out, "ir")
check("[1] a diode across a resistor between two 100 V nodes converges off",
      vd is not None and abs(vd) < 1e-6 and abs(ir) < 1e-12, f"vd {vd}, I(r) {ir}")

out = run("vadio", HIGH % ("a Verilog-A diode", "n1 4 3 tdio\n.model tdio ctdio is=1e-14", "pre_osdi ctdio.osdi"))
vd, ir = num(out, "vd"), num(out, "ir")
check("[2] the same with a Verilog-A diode",
      vd is not None and abs(vd) < 1e-6 and abs(ir) < 1e-12, f"vd {vd}, I(r) {ir}")

out = run("vadiors", HIGH % ("a Verilog-A diode with an internal node",
                             "n1 4 3 trs\n.model trs ctdiors is=1e-14 rs=10", "pre_osdi ctdiors.osdi"))
vd = num(out, "vd")
check("[3] the same with a Verilog-A diode behind an internal series node",
      vd is not None and abs(vd) < 1e-6, f"vd {vd}")

out = run("npn", HIGH % ("an npn base", "q1 3 4 3 qn\n.model qn npn is=1e-15 bf=100", ""))
vd = num(out, "vd")
check("[4] an npn's base across the resistor converges off",
      vd is not None and abs(vd) < 1e-6, f"vbe {vd}")

out = run("mos", HIGH % ("a MOSFET bulk junction",
                         "m1 3 3 3 4 mn w=10u l=1u\n.model mn nmos level=1 vto=0.7 kp=1e-4 is=1e-14\n"
                         ".nodeset v(4)=103", ""))
vd = num(out, "vd")
check("[5] a level-1 MOSFET's bulk junction started forward by a nodeset converges off",
      vd is not None and abs(vd) < 1e-4, f"vbd {vd}")

# [6] the dc temp sweep of the campaign's Family D seed 37: 40-degree steps
TEMP = """* a diode on 2.69 uA, dc temp sweep
i5 0 n5 dc 2.6877106444365614e-06
d5 n5 0 dm5 dtemp=-19.211385305094538
.model dm5 d is=3.2544826936857686e-13 n=1.108997167417154 eg=0.6895639401349207 xti=0.6635040172631177
%s
.control
set numdgt=12
dc temp -71.67947838408722 8.320521615912778 40
print v(n5)
.endc
.end
"""


def table(out):
    return [float(m.group(2)) for m in re.finditer(r"^\d+\s+(\S+)\s+(\S+)\s*$", out, re.M)]


loose = table(run("temp", TEMP % ""))
tight = table(run("temp_tight", TEMP % ".option reltol=1e-9 vntol=1e-12 abstol=1e-18"))
worst = max((abs(a - b) for a, b in zip(loose, tight)), default=None)
check("[6] a dc temp sweep at default tolerances is within 30 uV of reltol 1e-9 at every point",
      len(loose) == 3 and len(tight) == 3 and worst < 3e-5,
      f"worst {worst} V over {len(loose)} points")

# [7] Family A seed 1111: d9 and d7 hold the npn's emitter 2 V below its base
ROUND = """* an npn forward-biased 2 V by an ideal source
r0 1 0 527.112934238569
r1 2 0 661.6987658975482
r2 3 0 43797.13031785959
r3 0 2 490.9836804191783
v4 2 0 dc -4.226577970529781
i5 1 3 dc 0.0014591251326140898
i6 2 1 dc -0.0008515744105736145
d7 1 2 dm7
q8 3 0 1 qm8
d9 0 2 dm9
.model dm7 d is=1.2218646402059578e-14 n=1.4598572773297749
.model qm8 npn is=6.151228929932559e-16 bf=23.235866464223186 br=1.8123749382264718 nf=1.235237775300697 nr=1.2966616029731313
.model dm9 d is=1.332606006852675e-16 n=1.1654095711362193
.control
set numdgt=12
op
print v(1)
rusage totiter
.endc
.end
"""
out = run("round", ROUND)
v1, it = num(out, "v(1)"), iters(out)
check("[7] an npn with 1e13 A transport currents still converges",
      v1 is not None and abs(v1 + 2.0048031) < 1e-6 and it is not None and it < 100,
      f"v(1) {v1}, {it} iterations")

OFF = """* a diode marked off that the circuit drives forward
v1 1 0 5
r1 1 2 1k
d1 2 0 dm %s
.model dm d is=1e-14
.control
set numdgt=12
op
print v(2)
rusage totiter
.endc
.end
"""
on, off = run("on", OFF % ""), run("off", OFF % "off")
v_on, v_off = num(on, "v(2)"), num(off, "v(2)")
it = iters(off)
check("[8] a diode marked off that the circuit drives forward converges in at most 20 iterations",
      v_on is not None and v_off is not None and abs(v_on - v_off) < 3e-5 and v_off > 0.6 and
      it is not None and it <= 20,
      f"{v_off} V with off, {v_on} V without, {it} iterations")

SW = """* a closed Verilog-A switch between two 100 V nodes, carrying almost nothing
vh a 0 100
r1 a b 1e6
n1 b c ctl tsw
.model tsw ctsw gon=1e3
r2 c a 1e6
vc ctl 0 1
dx b c dm
.model dm d is=1e-14
.control
pre_osdi ctsw.osdi
set numdgt=12
op
let vbc = v(b)-v(c)
print vbc
rusage totiter
.endc
.end
"""
out = run("sw", SW)
vbc, it = num(out, "vbc"), iters(out)
check("[9] a closed Verilog-A switch between two 100 V nodes converges in at most 10 iterations",
      vbc is not None and abs(vbc) < 1e-9 and it is not None and it <= 10, f"vbc {vbc}, {it} iterations")

print(f"\n{passed}/{checks} checks passed")
sys.exit(0 if passed == checks else 1)
