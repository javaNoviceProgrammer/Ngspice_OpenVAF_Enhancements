#!/usr/bin/env python3
"""verify_pivrelone.py -- Enhancement-871: with pivrel=1 Sparse no longer
reports a pivot above pivtol as below it.

D1 of the Sparse and KLU correctness campaign of 2026-10-11.

Sparse's whole-matrix pivot search accepts an element only if
|a| > pivrel * (its column's largest). With pivrel=1 that strict test admits
nothing, the search takes the largest element of the reduced matrix, and
Enhancement-736 recorded every such step as a pivot below pivtol: "the pivot
for node neg ... is 1e+12, below pivtol (1e-13)". Only a pivot at or below
the absolute threshold is a small pivot now. (The warnings speak when the deck
sets pivtol, as here.)

  [1] a follower, pivrel=1 pivtol=1e-13: no pivot is reported (E-869: 1e+12)
  [2] teraohm dead ends, pivrel=1 pivtol=1e-13: every pivot reported is below
      1e-13 (E-869: 3370.9 and 1, which hid the real one)
  [3] (control) a pivot that is below pivtol is still reported: the follower
      with pivtol=1e13
  [4] (control) the answers are unchanged, the follower's to the bit

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

WORK = tempfile.mkdtemp(prefix="pivrelone_")
checks = passed = 0


def check(label, ok, detail=""):
    global checks, passed
    checks += 1
    passed += bool(ok)
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  [{detail}]" if detail else ""))


def run(name, body, opts, control):
    path = os.path.join(WORK, name + ".cir")
    with open(path, "w") as f:
        f.write("* %s\n%s\n.option sparse %s\n.control\nset numdgt=17\n%s\n.endc\n.end\n" % (name, body, opts, control))
    r = subprocess.run([NGSPICE, "-b", path], cwd=WORK, capture_output=True, text=True, timeout=120)
    return r.stdout + r.stderr


def reported(out):
    return [float(m) for m in re.findall(r"the pivot for node .*? is (\S+), below pivtol", out)]


def scalar(out, name):
    m = re.search(r"^%s\s*=\s*(\S+)" % re.escape(name), out, re.M)
    return float(m.group(1)) if m else None


FOLLOWER = "vin in 0 1.234567\ne1 out 0 in neg 1e12\nvfb out neg 0\nrl out 0 1k"
TERA = """v1 1 0 1.5623065557674634
l15 1 2 1u
r9 2 6 72.584775376258920T
r14 2 4 24.287618294387902T
r11 3 4 6.53218850813767T
l16 3 5 1u
e19 1 7 7 4 -3370.897504251147"""

# The suite pins Sparse itself (the defect is in Sparse's search); under the
# KLU pass of the harness the deck's own `.option sparse` still selects it.
out1 = run("fol", FOLLOWER, "pivrel=1 pivtol=1e-13", "op\nprint v(out)")
r1 = reported(out1)
check("[1] a follower, pivrel=1 pivtol=1e-13: no pivot reported", not r1, "reported %s" % r1)

out2 = run("tera", TERA, "pivrel=1 pivtol=1e-13", "op\nprint v(3)")
r2 = reported(out2)
check("[2] teraohm dead ends, pivrel=1 pivtol=1e-13: every pivot reported is below 1e-13",
      all(p <= 1e-13 for p in r2), "reported %s" % r2)

out3 = run("big", FOLLOWER, "pivtol=1e13", "op\nprint v(out)")
r3 = reported(out3)
check("[3] (control) a pivot below pivtol is still reported (pivtol=1e13)",
      len(r3) >= 1 and all(p <= 1e13 for p in r3), "reported %s" % r3)

v1 = scalar(out1, "v(out)")
v0 = scalar(run("fol0", FOLLOWER, "pivrel=1", "op\nprint v(out)"), "v(out)")
v2 = scalar(out2, "v(3)")
check("[4] (control) the answers: the follower's as without pivtol, to the bit; v(3) = v(1)",
      v1 is not None and v1 == v0 and v2 is not None and abs(v2 - 1.5623065557674634) < 1e-12,
      "v(out) %s vs %s, v(3) %s" % (v1, v0, v2))

print(f"\n{passed}/{checks} checks passed")
sys.exit(0 if passed == checks else 1)
