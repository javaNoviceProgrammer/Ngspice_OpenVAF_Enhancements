#!/usr/bin/env python3
"""verify_dynstaged.py -- Enhancement-876: dynorder leaves trbdf2 and sdirk at
their own order, and no longer freezes their step.

F3 of the transient stress campaign of 2026-10-12.

TR-BDF2 sets the order to 2 at the start of every step and SDIRK to 3.
Dynorder re-decided the order after each accepted step; when a neighbouring
order allowed a bigger step it "changed" the order, and its rule is not to grow
the step in the step that changes the order. The staged method reset the order
the next step, so the change happened every step and the step never grew: a
sine into an RC took 1 391 814 points under trbdf2 dynorder where trbdf2 took
130, and runs with a small first step never ended.

  [1] a sine into an RC: trbdf2 with dynorder runs point for point as trbdf2
      (E-875: 38 points but another answer, -0.45196 against -0.45258; on
      E-872, before E-874, 1 391 814 points)
  [2] a capacitor that never moves: sdirk with dynorder runs as sdirk
      (E-875: 10 002 points against 16, every step the first step's 5 ns)
  [3] the campaign's seed-14 network, 48 ns at a 2e-14 s first step, under
      sdirk maxord=4 dynorder ends within 20 s (E-875: no end in 120 s)
  [4] a note says dynorder has no effect with trbdf2 and sdirk
  [5] (control) dynorder still takes gear above order 2 on the RC

Exit code 0 = pass.
"""
import os
import re
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from _setup import NG as NGSPICE  # noqa: E402
from _setup import check_both_solvers as _check_both_solvers; _check_both_solvers(__file__)  # noqa: E402

WORK = tempfile.mkdtemp(prefix="dynstaged_")
checks = passed = 0


def check(label, ok, detail=""):
    global checks, passed
    checks += 1
    passed += bool(ok)
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  [{detail}]" if detail else ""))


def run(name, text, timeout=60):
    path = os.path.join(WORK, name + ".cir")
    with open(path, "w") as f:
        f.write(text)
    t0 = time.time()
    try:
        r = subprocess.run([NGSPICE, "-b", path], cwd=WORK, capture_output=True, text=True, timeout=timeout)
        out = r.stdout + r.stderr
    except subprocess.TimeoutExpired:
        out = "TIMEOUT"
    return out, time.time() - t0


def num(out, name):
    m = re.search(r"^%s\s*=\s*(\S+)" % re.escape(name), out, re.M)
    return float(m.group(1)) if m else None


RC = """* a sine into an RC
v1 in 0 sin(0 1 100k)
r1 in out 1k
c1 out 0 1n
.option %s
.control
set numdgt=17
set ngdebug
tran 1u 50u 0 50u
let n = length(time)
let e = v(out)[length(v(out))-1]
print n
print e
.endc
.end
"""
QUIET = """* a capacitor that never moves
v1 in 0 sin(0 1 100k)
r1 in 0 1k
r2 x 0 1k
c1 x 0 1n
.option %s
.control
tran 1u 50u 0 50u
let n = length(time)
print n
.endc
.end
"""

a, _ = run("rc_trbdf2", RC % "method=trbdf2")
b, _ = run("rc_trbdf2_dyn", RC % "method=trbdf2 dynorder")
check("[1] trbdf2 with dynorder runs point for point as trbdf2",
      num(a, "n") is not None and num(a, "n") == num(b, "n") and num(a, "e") == num(b, "e"),
      "%s vs %s points, end %s vs %s" % (num(b, "n"), num(a, "n"), num(b, "e"), num(a, "e")))

a, _ = run("q_sdirk", QUIET % "method=sdirk")
b, _ = run("q_sdirk_dyn", QUIET % "method=sdirk dynorder")
check("[2] a capacitor that never moves: sdirk with dynorder runs as sdirk",
      num(a, "n") is not None and num(a, "n") == num(b, "n"), "%s vs %s points" % (num(b, "n"), num(a, "n")))

S14 = """* the campaign's Family A seed 14
c0 3 0 1.651496352273684e-12
r1 1 0 5456.730590077879
r2 3 1 376.0438491524685
r3 2 0 113.25717919453662
v0 2 0 sin(-0.22466999169477642 -0.9787894092247145 6228714.852782994)
.option method=sdirk maxord=4 dynorder
.control
tran 2.408201427506027e-10 4.8164028550120545e-08
let n = length(time)
print n
.endc
.end
"""
out, sec = run("seed14", S14, timeout=60)
n = num(out, "n")
check("[3] the seed-14 network under sdirk maxord=4 dynorder ends within 20 s",
      n is not None and sec < 20, "%s points in %.1f s" % (n, sec))

o2, _ = run("rc_trbdf2_dyn_note", RC % "method=trbdf2 dynorder")
check("[4] a note says dynorder has no effect with trbdf2 and sdirk",
      "Note: dynorder has no effect with method=trbdf2, whose order is 2" in o2
      and "Note: dynorder has no effect with method=sdirk, whose order is 3" in b,
      "trbdf2 note %s, sdirk note %s" % ("dynorder has no effect with method=trbdf2" in o2,
                                         "dynorder has no effect with method=sdirk" in b))

g, _ = run("rc_gear_dyn", RC % "method=gear maxord=4 dynorder")
m = re.search(r"highest integration order used\s*=\s*(\d+)", g)
check("[5] (control) dynorder still takes gear above order 2 on the RC",
      m is not None and int(m.group(1)) >= 3, "highest order %s" % (m.group(1) if m else None))

print(f"\n{passed}/{checks} checks passed")
sys.exit(0 if passed == checks else 1)
