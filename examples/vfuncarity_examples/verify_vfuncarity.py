#!/usr/bin/env python3
"""Enhancement-339: `v()` with three or more node names SIGSEGV'd ngspice.

`v()` takes at most two node names -- `v(a)`, or the differential `v(a,b)`. A
third was not rejected. `PP_mkfnode`'s comma branch recursed on a child that is
itself a comma node, and that branch CONSUMES its argument (`free_pnode`) while
the normal path BORROWS it and bumps `pn_use`. So the recursive call freed the
child and the outer `free_pnode(arg)` then walked into it: a double free.

`print v(a,b,c)`, `let q = v(a,b,c)` and `pyplot v(a,b,c)` all died with SIGSEGV.
`plot` survived only because it does not take that path -- which is why this was
easy to miss.

Node existence is irrelevant: all-present `v(in,out,0)`, all-missing `v(a,b,c)`
and mixed `v(in,out,zz)` crashed alike. It is purely the arity.

Found by fuzzing the pyplot command family, but the defect is in the shared
expression parser, so it is filed against that rather than pyplot.

  [1] three node names are a clean error in print / let / pyplot -- no signal
  [2] four likewise
  [3] the diagnostic says what the limit is
  [4] one and two node names still work, present or missing
"""
import os
import re
import signal
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from _setup import NG as NGSPICE  # noqa: E402

checks = passed = 0


def check(label, ok, detail=""):
    global checks, passed
    checks += 1
    passed += bool(ok)
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  [{detail}]" if detail else ""))


DECK = ("varity\nV1 in 0 pulse(0 1 0 1n 1n 5n 10n)\nR1 in out 1k\nC1 out 0 1p\n"
        ".control\ntran 0.1n 20n\n%s\n.endc\n.end\n")


def run(cmd, timeout=60):
    p = os.path.join(HERE, "_va.cir")
    with open(p, "w") as f:
        f.write(DECK % cmd)
    try:
        r = subprocess.run([NGSPICE, "-b", os.path.basename(p)], cwd=HERE,
                           capture_output=True, text=True, timeout=timeout,
                           errors="replace")
    except subprocess.TimeoutExpired:
        return "HANG", ""
    finally:
        if os.path.exists(p):
            os.remove(p)
    if r.returncode < 0:
        try:
            nm = signal.Signals(-r.returncode).name
        except ValueError:
            nm = str(-r.returncode)
        return "SIG" + nm, r.stdout + r.stderr
    return r.returncode, r.stdout + r.stderr


def main():
    # [1] three node names, through every command that used to crash
    crashed = []
    for cmd in ("print v(in,out,0)", "let q = v(in,out,0)",
                "pyplot _p3 v(in,out,0)", "print v(a,b,c)",
                "print v(in,out,zz)"):
        rc, _ = run(cmd)
        if not isinstance(rc, int):
            crashed.append(f"{cmd}: {rc}")
    check("three node names never crash (print / let / pyplot, any node existence)",
          not crashed, "; ".join(crashed) if crashed else "")

    # [2] four
    rc, _ = run("print v(in,out,0,in)")
    check("four node names do not crash either", isinstance(rc, int), f"rc={rc}")

    # [3] the diagnostic names the limit
    rc, out = run("print v(in,out,0)")
    check("the error says v() takes at most two node names",
          "at most two node names" in out,
          next((l.strip()[:60] for l in out.splitlines() if "at most two" in l),
               "no such message"))

    # [4] the legal forms still work, and still give the right numbers
    rc, out = run("print v(out)")
    ok1 = isinstance(rc, int) and "at most two" not in out
    rc, out2 = run("print v(in,out)")
    ok2 = isinstance(rc, int) and "at most two" not in out2
    rc, out3 = run("print v(a,b)")          # missing nodes, still only two
    ok3 = isinstance(rc, int) and "at most two" not in out3
    check("one and two node names still work (present or missing)",
          ok1 and ok2 and ok3, f"{ok1} {ok2} {ok3}")

    # the committed deck as a whole must survive
    with open(os.path.join(HERE, "vfuncarity.cir")) as f:
        deck = f.read()
    p = os.path.join(HERE, "_full.cir")
    with open(p, "w") as f:
        f.write(deck)
    try:
        r = subprocess.run([NGSPICE, "-b", os.path.basename(p)], cwd=HERE,
                           capture_output=True, text=True, timeout=120,
                           errors="replace")
        sig = r.returncode
    finally:
        for junk in ("_full.cir", "_va3.py", "_va3.data", "_p3.py", "_p3.data"):
            q = os.path.join(HERE, junk)
            if os.path.exists(q):
                os.remove(q)
    check("the committed reproducer deck runs without a signal", sig >= 0, f"rc={sig}")

    print(f"\n{'ALL PASS' if passed == checks else 'FAILURES'}: {passed}/{checks} passed")
    sys.exit(0 if passed == checks else 1)


main()
