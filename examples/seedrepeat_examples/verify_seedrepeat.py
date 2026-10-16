#!/usr/bin/env python3
"""verify_seedrepeat.py -- Enhancement-891: every `setseed N` starts the same
stream.

F3 of the nonlinear correctness campaign of 2026-10-15. The control-language
draws (sgauss, sunif, rnd, poisson, exponential) reseed through checkseed()
when `rndseed` differs from the seed it last applied, and setseed never told
it. The first `setseed 11` was followed by that reseed; a second `setseed 11`
found the seed already applied and left the draws where setseed's own refill
of the transient-noise pools had taken the generator.

  [1] after a second `setseed 11`, sgauss, sunif, rnd, poisson and
      exponential draw what they drew after the first (E-889: all five
      differ)
  [2] the first `setseed 11` still draws what it always drew: sgauss gives
      -0.81594714, 0.65480624, -0.47049274
  [3] a Monte Carlo loop of sgauss draws repeated after `setseed 1` gives the
      same result (E-889: a different one)
  [4] (control) setseed 11, 12, 11 gives the 11 stream again
  [5] (control) `.param` agauss after `setseed 5; reset` draws the same value
      both times

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

WORK = tempfile.mkdtemp(prefix="seedrepeat_")
checks = passed = 0


def check(label, ok, detail=""):
    global checks, passed
    checks += 1
    passed += bool(ok)
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  [{detail}]" if detail else ""))


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


DRAWS = """* the control-language draws after two setseed 11
v1 a 0 1
r1 a 0 1k
.control
let z = sunif(vector(1))
setseed 11
let g = sgauss(vector(3))
let u = sunif(vector(3))
let r = rnd(vector(3) + 100)
let p = poisson(vector(3) + 20)
let e = exponential(vector(3) + 2)
setseed 11
let g2 = sgauss(vector(3))
let u2 = sunif(vector(3))
let r2 = rnd(vector(3) + 100)
let p2 = poisson(vector(3) + 20)
let e2 = exponential(vector(3) + 2)
setseed 12
let g3 = sgauss(vector(3))
setseed 11
let g4 = sgauss(vector(3))
let dg = vecmax(abs(g2 - g))
let du = vecmax(abs(u2 - u))
let dr = vecmax(abs(r2 - r))
let dp = vecmax(abs(p2 - p))
let de = vecmax(abs(e2 - e))
let d4 = vecmax(abs(g4 - g))
let d3 = vecmax(abs(g3 - g))
set numdgt=8
print dg du dr dp de d4 d3
print g
.endc
.end
"""
out = run("draws", DRAWS)
d = {k: num(out, k) for k in ("dg", "du", "dr", "dp", "de", "d4", "d3")}
check("[1] a second setseed 11 draws what the first drew, in all five functions",
      all(d[k] == 0.0 for k in ("dg", "du", "dr", "dp", "de")), f"{d}")
g = [float(m.group(1)) for m in re.finditer(r"^\d+\s+(\S+)\s*$", out, re.M)]
want = [-0.81594714, 0.65480624, -0.47049274]
check("[2] the first setseed 11 draws what it always drew",
      len(g) == 3 and all(abs(a - b) < 1e-7 for a, b in zip(g, want)), f"{g}")

MC = """* a Monte Carlo loop, run twice after setseed 1
v1 a 0 1
r1 a 0 1k
.control
let s1 = 0
let s2 = 0
setseed 1
let k = 0
while k < 50
  let x = sgauss(vector(1))
  let s1 = s1 + x[0] * x[0]
  let k = k + 1
end
setseed 1
let k = 0
while k < 50
  let x = sgauss(vector(1))
  let s2 = s2 + x[0] * x[0]
  let k = k + 1
end
set numdgt=12
print s1 s2
.endc
.end
"""
out = run("mc", MC)
s1, s2 = num(out, "s1"), num(out, "s2")
check("[3] a Monte Carlo loop repeated after setseed 1 gives the same result",
      s1 is not None and s1 == s2, f"{s1} and {s2}")
check("[4] (control) setseed 11, 12, 11 gives the 11 stream again, and 12 another",
      d["d4"] == 0.0 and d["d3"] is not None and d["d3"] > 0.1, f"d4 {d['d4']}, d3 {d['d3']}")

PARAM = """* agauss after setseed and reset, twice
v1 a 0 1
r1 a 0 {agauss(1000, 100, 1)}
.control
set numdgt=12
setseed 5
reset
op
print @r1[resistance]
setseed 5
reset
op
print @r1[resistance]
.endc
.end
"""
out = run("param", PARAM)
rs = [float(m.group(1)) for m in re.finditer(r"^@r1\[resistance\]\s*=\s*(\S+)", out, re.M)]
r1, r2 = (rs + [None, None])[:2]
check("[5] (control) .param agauss after setseed 5 and reset draws the same value both times",
      r1 is not None and r1 == r2 and r1 != 1000.0, f"{r1} and {r2}")

print(f"\n{passed}/{checks} checks passed")
sys.exit(0 if passed == checks else 1)
