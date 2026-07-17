#!/usr/bin/env python3
"""
verify_plusargs.py -- Enhancement-215: $test$plusargs / $value$plusargs.

Before E-215 these were constant fallbacks (E-12): $test$plusargs always returned
false and $value$plusargs never wrote its output. They are now served through the
simparam channel -- ngspice collects each command-line `+name[=value]` and a
compiled model reads it, so a corner or feature flag is chosen at RUN TIME without
editing the deck.

`plusargs_demo.va` maps plusargs onto a conductance (mS), observable as the DC
current through a 1 V source: baseline 1, then (last applicable wins)
  +boost -> 10 (presence), +gain=<n> -> n (int), +scale=<x> -> x (real),
  +corner=ff|ss -> 5|0.2 (string).

Each check runs `ngspice -b deck +args...` and asserts the current equals -g mA.
The verify is wrapped by check_both_solvers, so the whole matrix runs under both
KLU and Sparse (plusargs are solver-independent, but this proves it).

Every SPICE deck starts with a title line (SPICE treats line 1 as the title!).
"""
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))          # the examples/ dir (holds _setup.py)
from _setup import VAF as OPENVAF, NG as NGSPICE
from _setup import check_both_solvers as _check_both_solvers; _check_both_solvers(__file__)  # both solvers

DECK = (
    "* plusargs conductance\n"
    "vin a 0 dc 1\n"
    "n1 a 0 dm\n"
    ".model dm plusargs_demo\n"
    ".control\n"
    "pre_osdi plusargs_demo.osdi\n"
    "dc vin 1 1 1\n"
    "wrdata _pa.txt i(vin)\n"
    ".endc\n.end\n"
)

checks = passed = 0


def check(label, ok, detail=""):
    global checks, passed
    checks += 1
    passed += bool(ok)
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"   [{detail}]" if detail else ""))


def current_mA(plusargs):
    """Run `ngspice -b deck <plusargs...>` and return -i(vin) in mA (g, in mS)."""
    with open(os.path.join(HERE, "_pa.cir"), "w") as fh:
        fh.write(DECK)
    out = os.path.join(HERE, "_pa.txt")
    if os.path.exists(out):
        os.remove(out)
    subprocess.run([NGSPICE, "-b", "_pa.cir", *plusargs], cwd=HERE,
                   capture_output=True, text=True, timeout=120)
    if not os.path.exists(out):
        return None
    row = open(out).read().split("\n")[0].split()
    return -float(row[1]) * 1000.0 if len(row) >= 2 else None


def main():
    print("[1] the model compiles ($test$plusargs / $value$plusargs used to be fallbacks)")
    r = subprocess.run([OPENVAF, "plusargs_demo.va", "-o", "plusargs_demo.osdi"],
                       cwd=HERE, capture_output=True, text=True)
    check("openvaf-r plusargs_demo.va", r.returncode == 0,
          "" if r.returncode == 0 else (r.stdout + r.stderr).strip().splitlines()[-1][:70])
    if r.returncode != 0:
        print("\nSOME FAILED")
        sys.exit(1)

    # (label, command-line plusargs, expected conductance in mS)
    cases = [
        ("baseline (no plusargs)",                 [],                    1.0),
        ("$test$plusargs: +boost",                 ["+boost"],           10.0),
        ("$test$plusargs: unrelated +foo ignored", ["+foo"],              1.0),
        ("$value$plusargs %d: +gain=25",           ["+gain=25"],         25.0),
        ("$value$plusargs %d: +gain=3",            ["+gain=3"],           3.0),
        ("$value$plusargs %g: +scale=2.5",         ["+scale=2.5"],        2.5),
        ("$value$plusargs %s: +corner=ff",         ["+corner=ff"],        5.0),
        ("$value$plusargs %s: +corner=ss",         ["+corner=ss"],        0.2),
        ("$value$plusargs %s: +corner=tt (unmatched -> baseline)",
                                                   ["+corner=tt"],        1.0),
        ("precedence: +boost +gain=7 (last wins)", ["+boost", "+gain=7"], 7.0),
        ("presence without value: +gain alone -> not a value match",
                                                   ["+gain"],             1.0),
    ]
    print("[2] each plusarg selects the right conductance at run time")
    for label, args, want in cases:
        g = current_mA(args)
        check(label, g is not None and abs(g - want) < 1e-6,
              f"got {g} mS, want {want} mS")

    for f in os.listdir(HERE):
        if f.startswith("_") and f.split(".")[-1] in ("cir", "txt"):
            os.remove(os.path.join(HERE, f))

    print(f"\n{passed}/{checks} checks passed")
    print("ALL PASS" if passed == checks else "SOME FAILED")
    sys.exit(0 if passed == checks else 1)


if __name__ == "__main__":
    main()
