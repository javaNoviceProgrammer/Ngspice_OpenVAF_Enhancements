#!/usr/bin/env python3
"""verify_mutsystem.py -- Enhancement-872: the coupled-inductor check no longer
writes into freed memory when it runs twice.

Found while folding F4 of the Sparse and KLU correctness campaign of
2026-10-11.

MUTtemp groups coupled inductors into systems to check that each is positive
definite, and freed the systems at the end while the inductors and couplings
kept pointing at them; only INDsetup cleared the pointers. A second MUTtemp
without a setup between -- every point of a `dc temp` sweep -- found them
non-NULL, took each pair to be in a system already, and wrote into freed
memory (Guard Malloc: SIGSEGV in MUTtemp). No system was built again, so a
coupling that went wrong at a later temperature was never reported. The links
are cleared before the systems are freed, and a system's report is given once.

  [1] L1 with tc1 = -0.02 turns negative at 100 C in a `dc temp` sweep: the
      inductive-system report names it (E-869: silent)
  [2] k = 1.5 through an 11-point temperature sweep: "not positive definite"
      is reported once, not at every point
  [3] (control) k = 0.9 through the sweep: no report, 11 points
  [4] the sweep under Guard Malloc runs to the end (macOS; skipped where
      /usr/lib/libgmalloc.dylib is absent)

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

WORK = tempfile.mkdtemp(prefix="mutsystem_")
checks = passed = 0


def check(label, ok, detail=""):
    global checks, passed
    checks += 1
    passed += bool(ok)
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  [{detail}]" if detail else ""))


def deck(name, k, tc1="", sweep="dc temp 0 100 10"):
    path = os.path.join(WORK, name + ".cir")
    with open(path, "w") as f:
        f.write("* %s\nv1 1 0 dc 1\nr1 1 2 50\nl1 2 0 10u %s\nl2 3 0 40u\nk1 l1 l2 %r\nr2 3 0 200\n"
                ".control\n%s\nprint v(1)\n.endc\n.end\n" % (name, tc1, k, sweep))
    return path


def run(path, env=None):
    r = subprocess.run([NGSPICE, "-b", path], cwd=WORK, capture_output=True, text=True, timeout=300, env=env)
    return r.returncode, r.stdout + r.stderr


def points(out):
    return len(re.findall(r"^\d+\s+\S+\s+\S+\s*$", out, re.M))


rc, out = run(deck("negl", 0.9, "tc1=-0.02", "dc temp 0 100 50"))
check("[1] L1 turning negative at 100 C is reported (l1 < 0)",
      rc == 0 and re.search(r"^\s*l1 < 0", out, re.M) is not None,
      "rc %d, %d report(s)" % (rc, out.count("The Inductive System")))

rc, out = run(deck("k15", 1.5))
n = out.count("not positive definite")
check("[2] k = 1.5 through an 11-point sweep: reported once", rc == 0 and n == 1 and points(out) == 11,
      "rc %d, %d report(s), %d points" % (rc, n, points(out)))

rc, out = run(deck("k09", 0.9))
check("[3] (control) k = 0.9 through the sweep: no report, 11 points",
      rc == 0 and "Inductive System" not in out and points(out) == 11,
      "rc %d, %d points" % (rc, points(out)))

GM = "/usr/lib/libgmalloc.dylib"
if sys.platform == "darwin" and os.path.exists(GM):
    env = dict(os.environ, DYLD_INSERT_LIBRARIES=GM)
    rc, out = run(deck("gm", 0.9), env)
    if rc != 0 and points(out) == 0 and "dyld" in out:
        check("[4] the sweep under Guard Malloc runs to the end", True,
              "skipped: dyld would not load %s" % GM)
    else:
        check("[4] the sweep under Guard Malloc runs to the end", rc == 0 and points(out) == 11,
              "rc %d, %d points" % (rc, points(out)))
else:
    check("[4] the sweep under Guard Malloc runs to the end", True, "skipped: no %s here" % GM)

print(f"\n{passed}/{checks} checks passed")
sys.exit(0 if passed == checks else 1)
