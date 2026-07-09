#!/usr/bin/env python3
"""
verify_hiername.py -- verifies Enhancement-49: $root + hierarchical names,
the transition() real-input fix, and the builtin argument-type audit,
end-to-end through the committed openvaf-r + ngspice.

Three defects fixed:
  * hierarchical references into flattened instances didn't resolve
    (`V(u1.m)`, `u1.r` -> "'u1' was not found in the current scope"): the E-5
    elaboration flattens instances into prefixed locals (u1__m) but never
    rewrote parent-side references. A token-level path scanner now rewrites
    instance chains (u1.m, u1.u2.x, u1[2].m, and the $root.<top>./<top>.
    anchored spellings) to the flattened names, composing prefixes per
    segment; nested modules' own references rewrite through their scopes too.
  * nested named-block paths (`outer.inner.w`) failed with "'w' was not found
    in 'inner'": after the resolver redirected into a nested block's def map,
    the FINAL name lookup still probed the original map (`self.scopes` vs
    `current_map.scopes` -- a one-token aliasing bug).
  * transition() typed its input Integer, rejecting the LRM's canonical
    comparator (`real vcout; ... transition(vcout, td, tr, tf)` -- "expected
    integer value but found real variable reference"); the input is Real per
    LRM 4.5.7, with integer inputs still promoting implicitly. The audit of
    every builtin signature table also caught DIST_2_ARG_CONST_SEED typing
    its middle argument Real while its three siblings say Integer.

Checks (all exact):
  1. deep hierarchy: 1e-3*u1.u2.r + (10+100+1000)*V(u1.u2.m) with the
     divider midpoint at 0.5 V -> 2 + 555 = 557; covers plain, $root-anchored
     and top-qualified spellings
  2. nested named blocks: outer.inner.w + 2*$root...inner.w = 3.75
  3. the LRM comparator compiles (real transition input) and switches: +1 on
     the sine's positive half, ~0 on the negative half

Every SPICE deck starts with a title line (SPICE treats line 1 as the title!).
"""
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from _setup import VAF as OPENVAF, NG as NGSPICE
from _setup import check_both_solvers as _check_both_solvers; _check_both_solvers(__file__)  # verify under BOTH KLU and Sparse solvers


def run(deck, *names):
    with open(os.path.join(HERE, "_h.cir"), "w") as fh:
        fh.write(deck)
    out = subprocess.run([NGSPICE, "-b", "_h.cir"], cwd=HERE,
                         capture_output=True, text=True, timeout=120).stdout
    vals = {}
    for line in out.splitlines():
        stripped = line.strip().lower()
        for nm in names:
            if stripped.startswith(nm.lower() + " ") and nm not in vals:
                vals[nm] = float(line.split("=", 1)[1].strip())
    return vals


def main():
    subprocess.run([OPENVAF, "hiername_demo.va", "-o", "hiername_demo.osdi"],
                   cwd=HERE, check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    ok = True

    def check(label, got, want, tol=1e-9):
        nonlocal ok
        good = abs(got - want) < tol
        ok = ok and good
        print(f"  {'PASS' if good else 'FAIL'}  {label}   got {got:.6e}, want {want:.6e}")

    print("[1] deep instance paths: plain, $root-anchored, top-qualified")
    deck = ("* hier\nVs in 0 DC 1\nNDUT in 0 out nm\nRL out 0 1G\n.model nm hier\n"
            ".control\npre_osdi hiername_demo.osdi\nop\nprint v(out)\n.endc\n.end\n")
    check("2 + (10+100+1000)*0.5 = 557", run(deck, "v(out)")["v(out)"], 557.0, 1e-6)

    print("[2] nested named-block paths (was: 'w' not found in 'inner')")
    deck = ("* blocks\nNDUT out 0 nm\nR1 out 0 1k\n.model nm blocks\n"
            ".control\npre_osdi hiername_demo.osdi\nop\nprint v(out)\n.endc\n.end\n")
    check("outer.inner.w + 2*$root form = 3.75", run(deck, "v(out)")["v(out)"], 3.75)

    print("[3] LRM comparator: transition() with a real input (was type error)")
    deck = ("* comparator\nVp inp 0 DC 0 SIN(0 1 1meg)\nVm inm 0 DC 0\n"
            "NDUT cout inp inm nm\nRL cout 0 1k\n.model nm comparator\n"
            ".tran 1n 2u\n.control\npre_osdi hiername_demo.osdi\nrun\n"
            "meas tran vhi FIND v(cout) AT=0.25u\n"
            "meas tran vlo FIND v(cout) AT=0.75u\n.endc\n.end\n")
    v = run(deck, "vhi", "vlo")
    check("high on positive half", v["vhi"], 1.0, 1e-6)
    check("low on negative half", v["vlo"], 0.0, 1e-6)

    print()
    print("ALL PASS" if ok else "SOME CHECKS FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
