#!/usr/bin/env python3
"""Enhancement-348: `.pss` argument handling.

`pss 1meg 1u out 1024` -- four of seven arguments -- segfaulted; bare `pss`
hung. The crash had a second entrance that has nothing to do with truncation:
`pss 1meg 1u out 1024 0 50 5u` is a complete, well-formed card and crashed the
same way, because `harmonics` is the length of every array the DFT writes into.
At 0 the TMALLOCs return NULL, and DFT's `Mag[0] = Phase[0]/ndata` -- written
outside any loop, so the numFreq bound does not protect it -- dereferences it.

Three layers were fixed: `dot_pss()` rejects a card that runs out of tokens,
`DCpss()` validates fguess/points/harmonics before sizing anything from them,
and `DFT()` guards its own unconditional index-0 stores.

  [1] every proper prefix of a valid .pss -- no signal, no hang
  [2] harmonics 0 at FULL arity -- the entrance a parser guard alone would miss
  [3] fguess 0 -- used to spin forever
  [4] points 0
  [5] sc_iter / steady_coeff at 0 are still ACCEPTED (measured harmless --
      documenting what was deliberately not tightened)
  [6] a valid .pss still runs and still produces its frequency-domain plot
  [7] the committed reproducer deck survives
"""
import os
import signal
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from _setup import NG as NGSPICE  # noqa: E402

DECK = ("pssargs\n"
        "V1 in 0 dc 1 ac 1 sin(0 1 1e6)\n"
        "R1 in out 1k\n"
        "R2 out 0 3k\n"
        "C1 out 0 1p\n")

FULL = ["1meg", "1u", "out", "1024", "10", "50", "5u"]

checks = passed = 0


def check(label, ok, detail=""):
    global checks, passed
    checks += 1
    passed += bool(ok)
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  [{detail}]" if detail else ""))


def run(control, timeout=120):
    """Run a .control block; return (rc, output). rc is a string on a signal."""
    p = os.path.join(HERE, "_pa.cir")
    with open(p, "w") as f:
        f.write("%s.control\noption noacct\n%s\necho SURVIVED\n.endc\n.end\n"
                % (DECK, control))
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
    # ---- [1] every proper prefix -------------------------------------------
    bad = []
    for k in range(len(FULL)):
        rc, _ = run("pss " + " ".join(FULL[:k]))
        if not isinstance(rc, int):
            bad.append("%d args: %s" % (k, rc))
    check("every proper prefix of .pss is refused, not crashed",
          not bad, "; ".join(bad) if bad else "7/7 prefixes clean")

    # ---- [2] the entrance a parser guard alone would miss -------------------
    rc, out = run("pss 1meg 1u out 1024 0 50 5u")
    check("harmonics 0 at FULL arity is rejected, not a segfault",
          isinstance(rc, int) and "harmonics" in out.lower(),
          f"rc={rc}")

    # ---- [3] fguess 0 -- used to hang ---------------------------------------
    rc, out = run("pss 0 1u out 1024 10 50 5u")
    check("fguess 0 is rejected instead of spinning forever",
          isinstance(rc, int) and "fguess" in out.lower(), f"rc={rc}")

    # ---- [4] points 0 -------------------------------------------------------
    rc, out = run("pss 1meg 1u out 0 10 50 5u")
    check("points 0 is rejected", isinstance(rc, int) and "points" in out.lower(),
          f"rc={rc}")

    # ---- [5] what was deliberately NOT tightened ----------------------------
    still_ok = []
    for label, cmd in (("sc_iter 0", "pss 1meg 1u out 1024 10 0 5u"),
                       ("steady_coeff 0", "pss 1meg 1u out 1024 10 50 0")):
        rc, out = run(cmd)
        if not (isinstance(rc, int) and "SURVIVED" in out):
            still_ok.append(f"{label}: rc={rc}")
    check("sc_iter / steady_coeff at 0 are still accepted (measured harmless)",
          not still_ok, "; ".join(still_ok) if still_ok else "both still run")

    # ---- [6] a valid .pss is untouched --------------------------------------
    rc, out = run("pss %s\nsetplot\nprint v(out)[0]" % " ".join(FULL))
    check("a valid .pss still runs and still yields its result",
          isinstance(rc, int) and rc == 0 and "SURVIVED" in out
          and "v(out)" in out, f"rc={rc}")

    # ---- [7] the committed deck --------------------------------------------
    r = subprocess.run([NGSPICE, "-b", "pssargs.cir"], cwd=HERE,
                       capture_output=True, text=True, timeout=180,
                       errors="replace")
    check("the committed reproducer deck runs without a signal",
          r.returncode >= 0 and "SURVIVED" in (r.stdout + r.stderr),
          f"rc={r.returncode}")

    for junk in os.listdir(HERE):
        if junk.startswith("_"):
            os.remove(os.path.join(HERE, junk))

    print(f"\n{'ALL PASS' if passed == checks else 'FAILURES'}: {passed}/{checks} passed")
    sys.exit(0 if passed == checks else 1)


main()
