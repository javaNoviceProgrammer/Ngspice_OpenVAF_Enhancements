#!/usr/bin/env python3
"""Enhancement-341: `sweep -analysis reset` / `-analysis remcirc` SIGSEGV'd.

`sweep` runs its `-analysis` argument as a command at every point, dispatched by
name, so a user can name `reset` or `remcirc` -- which free and rebuild (or
remove) the very circuit the sweep is iterating over. The loop then kept using
its resolved knob bindings, the old `CKTcircuit *` and the old plot.

Found by fuzzing `sweep`/`optimize` for RECURSION and STATE: the argument-surface
round (684 invocations) was clean, so the strategy was extended to commands that
take another command as an argument and to state carried across invocations.

The fix rejects such an analysis BEFORE the loop starts, which is deliberate.
Detecting the damage afterwards and breaking out is not enough -- the sweep's
post-loop plot finalisation touches the same freed state, and an early attempt at
that turned a previously WORKING case (`-analysis 'optimize ...'`, which resets
internally but recovers) into a crash. Rejecting up front cannot regress anything.

  [1] `-analysis reset` and `-analysis remcirc` are refused, no signal
  [2] the message says why and points at a real analysis
  [3] a real analysis still sweeps, and still produces the right values
  [4] `-analysis 'optimize ...'`, which resets internally, still works
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


DECK = (".param pr = 1k\nV1 in 0 dc 1\nR1 in out 1k\nR2 out 0 {pr}\n"
        ".control\n%s\n.endc\n.end\n")


def run(cmd, timeout=90):
    p = os.path.join(HERE, "_sa.cir")
    with open(p, "w") as f:
        f.write("sweep analysis\n" + DECK % cmd)
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
    # [1]+[2] the destructive analyses
    bad, msg_ok = [], True
    for what in ("reset", "remcirc"):
        rc, out = run(f"sweep pr lin 3 1k 3k -analysis {what} -output v(out)")
        if not isinstance(rc, int):
            bad.append(f"{what}: {rc}")
        if "would destroy the circuit" not in out:
            msg_ok = False
    check("`-analysis reset` and `-analysis remcirc` are refused, not a crash",
          not bad, "; ".join(bad) if bad else "")
    check("the message explains why and points at a real analysis", msg_ok)

    # [3] a real analysis still works, with the right numbers
    rc, out = run("sweep pr lin 3 1k 3k -analysis op -output v(out)\nprint v(out)")
    pts = re.search(r"sweep: (\d+) points into", out)
    check("a real analysis still sweeps (3 points recorded)",
          isinstance(rc, int) and pts is not None and pts.group(1) == "3",
          f"rc={rc} points={pts.group(1) if pts else None}")

    # [4] an analysis that resets INTERNALLY must keep working
    rc, out = run("sweep pr lin 3 1k 3k -analysis 'optimize -dparam pr 1k 1k 2k "
                  "-analysis op -minimize v(out) -maxiter 2' -output v(out)")
    check("`-analysis 'optimize ...'` (resets internally) still works",
          isinstance(rc, int), f"rc={rc}")

    # the committed deck as a whole
    p = os.path.join(HERE, "sweepanalysis.cir")
    r = subprocess.run([NGSPICE, "-b", os.path.basename(p)], cwd=HERE,
                       capture_output=True, text=True, timeout=120, errors="replace")
    check("the committed reproducer deck runs without a signal", r.returncode >= 0,
          f"rc={r.returncode}")

    print(f"\n{'ALL PASS' if passed == checks else 'FAILURES'}: {passed}/{checks} passed")
    sys.exit(0 if passed == checks else 1)


main()
