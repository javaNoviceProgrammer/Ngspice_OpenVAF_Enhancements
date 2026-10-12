#!/usr/bin/env python3
"""verify_dynstable.py -- Enhancement-873: dynorder's high orders no longer
explode on a stiff network.

F1 of the transient stress campaign of 2026-10-12.

The truncation estimate (CKTterr) multiplies an error constant meant for the
derivative q^(k+1) by the divided difference, which is q^(k+1)/(k+1)!. SPICE's
trtol=7 makes up the 3! of order 2; at order k >= 3 the estimate was (k+1)!/3!
too small. Dynorder (Enhancement-128) chose the order by that estimate, took
the high orders for 20 to 840 times cheaper than they were, and on this
nine-element RLC network, which peaks at 0.919 V, it reached 2.5e7 V at
maxord=4 and 9e22 V at maxord=6, with status 0 and nothing said.

  [1] gear maxord=4, 5 and 6 with dynorder: the peak and the final value of
      v(c) agree with a reltol=1e-7 trap run (E-872: 2.5e7, 4.3e17, 9.2e22)
  [2] adams maxord=3 and 4 with dynorder: the same (E-872: 1.2e8, 1.4e22)
  [3] errpreset=conservative with gear maxord=4 dynorder, and gear maxord=6
      dynorder at reltol=1e-5: the same (E-872: 1.6e4, 8.9e34)
  [4] (control) dynorder still climbs to order 4 on a smooth LC, in fewer
      steps than the stock controller
  [5] (control) an RC discharge under gear maxord=4 dynorder lands within
      0.1 % of exp(-8)

Exit code 0 = pass.
"""
import math
import os
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from _setup import NG as NGSPICE  # noqa: E402
from _setup import check_both_solvers as _check_both_solvers; _check_both_solvers(__file__)  # noqa: E402

WORK = tempfile.mkdtemp(prefix="dynstable_")
checks = passed = 0


def check(label, ok, detail=""):
    global checks, passed
    checks += 1
    passed += bool(ok)
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  [{detail}]" if detail else ""))


def run(name, text):
    path = os.path.join(WORK, name + ".cir")
    with open(path, "w") as f:
        f.write(text)
    r = subprocess.run([NGSPICE, "-b", path], cwd=WORK, capture_output=True, text=True, timeout=120)
    return r.stdout + r.stderr


def num(out, name):
    m = re.search(r"^%s\s*=\s*(\S+)" % re.escape(name), out, re.M)
    return float(m.group(1)) if m else None


RLC = """* nine elements; every node has a dc path
v1 in 0 pwl(0 -0.6 0.697u 0.19 0.70u 0.92 1.08u -0.7)
r1 in a 13.8k
r2 a b 21.2k
l1 b c 2.32u
l2 d b 6.7u
l3 e c 0.125u
r3 f d 44.9
c1 f e 1.23p
i1 e f sin(-0.42m 0.56m 164k)
.option %s
.control
set numdgt=12
tran 9n 1.82u
let m = maximum(abs(v(c)))
let e = v(c)[length(v(c))-1]
print m e
.endc
.end
"""


def rlc(opts):
    out = run("rlc_" + re.sub(r"\W+", "_", opts), RLC % opts)
    return num(out, "m"), num(out, "e")


ref_m, ref_e = rlc("reltol=1e-7")


def close(opts):
    m, e = rlc(opts)
    ok = m is not None and e is not None and abs(m - ref_m) < 5e-3 * ref_m and abs(e - ref_e) < 1e-3
    return ok, "%s: peak %s end %s" % (opts, "%.4g" % m if m is not None else "none", "%.5g" % e if e is not None else "none")


def group(label, optlist):
    res = [close(o) for o in optlist]
    check(label, all(r[0] for r in res), "reference peak %.4g end %.5g; " % (ref_m, ref_e) + "; ".join(r[1] for r in res))


group("[1] gear maxord=4, 5, 6 with dynorder agree with the reltol=1e-7 run",
      ["method=gear maxord=4 dynorder", "method=gear maxord=5 dynorder", "method=gear maxord=6 dynorder"])
group("[2] adams maxord=3, 4 with dynorder agree", ["method=adams maxord=3 dynorder", "method=adams maxord=4 dynorder"])
group("[3] errpreset=conservative gear maxord=4 dynorder, and gear maxord=6 dynorder at reltol=1e-5, agree",
      ["errpreset=conservative method=gear maxord=4 dynorder", "method=gear maxord=6 dynorder reltol=1e-5"])

# [4] smooth LC ringdown: dynorder still reaches order 4 and saves steps
LC = """* parallel RLC ringdown
l1 a 0 1m
c1 a 0 1u
r1 a 0 1k
.ic v(a)=1
.option method=gear maxord=4 %s reltol=1e-6
.control
set ngdebug
tran 1u 2m uic
let n = length(time)
print n
.endc
.end
"""
out_d = run("lc_dyn", LC % "dynorder")
out_s = run("lc_stock", LC % "")
n_d, n_s = num(out_d, "n"), num(out_s, "n")
mo = re.search(r"highest integration order used\s*=\s*(\d+)", out_d)
order = int(mo.group(1)) if mo else 0
check("[4] (control) dynorder climbs to order 4 on a smooth LC and takes fewer steps than the stock controller",
      order >= 4 and n_d is not None and n_s is not None and n_d < n_s,
      "highest order %d; %s vs %s points" % (order, n_d, n_s))

# [5] RC discharge accuracy
RC = """* RC discharge
r1 a 0 1k
c1 a 0 1u
.ic v(a)=1
.option method=gear maxord=4 dynorder reltol=1e-6
.control
tran 10u 8m uic
let e = v(a)[length(v(a))-1]
print e
.endc
.end
"""
e = num(run("rc", RC), "e")
check("[5] (control) RC discharge under gear maxord=4 dynorder lands within 0.1 % of exp(-8)",
      e is not None and abs(e - math.exp(-8)) / math.exp(-8) < 1e-3,
      "v(8 ms) %s, exp(-8) %.6e" % (e, math.exp(-8)))

print(f"\n{passed}/{checks} checks passed")
sys.exit(0 if passed == checks else 1)
