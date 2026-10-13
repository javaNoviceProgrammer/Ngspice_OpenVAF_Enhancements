#!/usr/bin/env python3
"""verify_transopts.py -- Enhancement-881, Enhancement-882 and Enhancement-883:
transient options that had no reading are refused or reported.

D1, D2 and D3 of the transient stress campaign of 2026-10-12.

  [1] E-881: xmu=-1 and xmu=2 are refused with a warning, and the run is the
      default run (E-875: 2.58e-6 and -2.53e-7 where the answer is 3.757e-7,
      no word)
  [2] E-881 (control): xmu=0 and xmu=0.3 are taken, and move the answer
  [3] E-882: ordfix=-1 is refused; ordfix=7 and ordfix=1e9 warn that 6 is used
      (E-875: no word)
  [4] E-882: reltol=1 and reltol=10 are refused, and the run is the default
      run (E-875: taken without a word)
  [5] E-882: gear with ordfix=4 at the default maxord=2 says the order is
      pinned at 2; at maxord=4 there is no such note (E-875: no word; E-888's
      note on ordfix itself is printed either way)
  [6] E-883: method=trbdf (a typo) names the value and the valid ones, and
      says trap is kept; after `option method=gear`, method=foo says gear is
      kept; the generic "unsupported integration method" line is gone
  [7] (control) reltol=0 is refused as "must be greater than zero", as before

Exit code 0 = pass.
"""
import os
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from _setup import NG as NGSPICE  # noqa: E402
from _setup import check_both_solvers as _check_both_solvers; _check_both_solvers(__file__)  # noqa: E402

WORK = tempfile.mkdtemp(prefix="transopts_")
checks = passed = 0


def check(label, ok, detail=""):
    global checks, passed
    checks += 1
    passed += bool(ok)
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  [{detail}]" if detail else ""))


DECK = """* transient options
v1 a 0 pulse(0 1 0 1n 1n 1u 2u)
r1 a b 1k
c1 b 0 1n
l1 b c 1u
r2 c 0 100
.option %s
.control
set numdgt=12
%s
tran 10n 4u
let z = v(b)[length(v(b))-1]
print z
.endc
.end
"""


def run(tag, opts, pre=""):
    path = os.path.join(WORK, tag + ".cir")
    with open(path, "w") as f:
        f.write(DECK % (opts, pre))
    r = subprocess.run([NGSPICE, "-b", path], cwd=WORK, capture_output=True, text=True, timeout=120)
    out = r.stdout + r.stderr
    m = re.search(r"^z\s*=\s*(\S+)", out, re.M)
    return (float(m.group(1)) if m else None), out


z0, _ = run("default", "")

res = [run("xmu_m1", "xmu=-1"), run("xmu_2", "xmu=2")]
check("[1] E-881: xmu=-1 and xmu=2 are refused, and the run is the default run",
      all(z == z0 and "must lie in [0, 0.5]" in o for z, o in res),
      "default %s; %s" % (z0, ", ".join(str(z) for z, _ in res)))

res = [run("xmu_0", "xmu=0"), run("xmu_03", "xmu=0.3")]
check("[2] E-881 (control): xmu=0 and xmu=0.3 are taken, and move the answer",
      all(z is not None and z != z0 and "xmu" not in o for z, o in res),
      ", ".join(str(z) for z, _ in res))

a = run("of_m1", "ordfix=-1")[1]
b = run("of_7", "ordfix=7")[1]
c = run("of_1e9", "ordfix=1e9")[1]
check("[3] E-882: ordfix=-1 is refused; ordfix=7 and 1e9 warn that 6 is used",
      "ordfix = -1 must not be negative" in a and "ordfix = 7 is above 6" in b and "6 is used" in c,
      "-1 %s, 7 %s, 1e9 %s" % ("must not be negative" in a, "is above 6" in b, "6 is used" in c))

res = [run("rt_1", "reltol=1"), run("rt_10", "reltol=10")]
check("[4] E-882: reltol=1 and reltol=10 are refused, and the run is the default run",
      all(z == z0 and "must be less than 1" in o for z, o in res), ", ".join(str(z) for z, _ in res))

n2 = run("of4_mo2", "method=gear ordfix=4")[1]
n4 = run("of4_mo4", "method=gear maxord=4 ordfix=4")[1]
check("[5] E-882: gear ordfix=4 at maxord=2 says the order is pinned at 2; at maxord=4 no ceiling note",
      "the order is pinned at 2" in n2 and "is above the highest order" not in n4,
      "maxord=2 note %s, maxord=4 note %s" % ("pinned at 2" in n2, "is above the highest order" in n4))

t = run("m_trbdf", "method=trbdf")[1]
g = run("m_foo", "method=gear", "option method=foo")[1]
check("[6] E-883: an unknown method names the value and the kept method, without the generic line",
      "method = trbdf is unknown" in t and "keeping trap" in t and "keeping gear" in g
      and "unsupported integration method" not in t + g,
      "typo %s, after gear %s" % ("keeping trap" in t, "keeping gear" in g))

z, o = run("rt_0", "reltol=0")
check("[7] (control) reltol=0 is refused as before", "must be greater than zero" in o and z == z0, str(z))

print(f"\n{passed}/{checks} checks passed")
sys.exit(0 if passed == checks else 1)
