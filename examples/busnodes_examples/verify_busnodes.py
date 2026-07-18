#!/usr/bin/env python3
"""
verify_busnodes.py -- Enhancement-221: array/bus node ranges in the netlist.

A node token  base[lo:hi]  is expanded to the scalar node sequence
    base[lo] base[lo±1] ... base[hi]
(descending when lo>hi) before device parsing, so the range supplies node
tokens positionally:
    R1 a[0:1] r=2k        -> R1 a[0] a[1] r=2k
    X1 n[0:1] res2        -> X1 n[0] n[1] res2
    .subckt res2 p[1:0]   -> .subckt res2 p[1] p[0]
An already-scalar name a[0] and the bus a[0:1] denote the SAME nodes.

Checks (all from node voltages / branch currents, so solver-independent):
  1. a 2-terminal R written as a bus R1 a[0:1] connects a[0]..a[1]: I = -1mA;
  2. the scalar form R2 a[0] addresses the SAME node a[0] as the bus element
     (I = +0.25mA -- only correct if a[0] is one shared node);
  3. a subcircuit with a DESCENDING port bus p[1:0], called with X1 n[0:1],
     connects positionally: I(Rs) = -5mA;
  4. malformed/non-integer ranges (b[x:y], c[1:2:3]) and scalar names are left
     as literal node names (not expanded), and `.control` is untouched.

Every SPICE deck starts with a title line (SPICE treats line 1 as the title!).
"""
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from _setup import NG as NGSPICE
from _setup import check_both_solvers as _check_both_solvers; _check_both_solvers(__file__)

checks = passed = 0


def check(label, ok, detail=""):
    global checks, passed
    checks += 1
    passed += bool(ok)
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"   [{detail}]" if detail else ""))


def run(deck):
    r = subprocess.run([NGSPICE, "-b", deck], cwd=HERE,
                       capture_output=True, text=True, timeout=120)
    return r.stdout + r.stderr


def val(out, name):
    """Return the float printed for a `print <name>` scalar, or None."""
    for line in out.splitlines():
        s = line.strip()
        if s.startswith(name):
            for tok in s.replace("=", " ").split():
                try:
                    return float(tok)
                except ValueError:
                    continue
    return None


def main():
    out = run("busnodes_demo.cir")

    print("[1] R1 a[0:1] expands to a 2-terminal R across a[0], a[1]")
    i_r1 = val(out, "i_r1")
    check("I(R1) = (1-3)/2k = -1mA", i_r1 is not None and abs(i_r1 - (-1e-3)) < 1e-9,
          f"{i_r1}")

    print("[2] scalar a[0] is the SAME node as the bus element a[0]")
    i_r2 = val(out, "i_r2")
    check("I(R2 via a[0]) = 1/4k = +0.25mA", i_r2 is not None and abs(i_r2 - 0.25e-3) < 1e-9,
          f"{i_r2}")

    print("[3] subckt descending port bus p[1:0], called with X1 n[0:1]")
    i_rs = val(out, "i_rs")
    check("I(Rs) = (0-5)/1k = -5mA (positional bus connection)",
          i_rs is not None and abs(i_rs - (-5e-3)) < 1e-9, f"{i_rs}")

    print("[4] malformed / scalar tokens are left literal; .control untouched")
    edge = os.path.join(HERE, "_edge.cir")
    with open(edge, "w") as f:
        f.write("* edge cases\n"
                "V1 a[0] 0 1\nR1 a[0] 0 2k\n"          # scalar, untouched
                "Rm a[0] b[x:y] 1k\nVb b[x:y] 0 0\n"    # non-integer range -> literal node
                "Rn a[0] c[1:2:3] 1k\nVc c[1:2:3] 0 0\n"  # malformed -> literal node
                ".op\n.control\nrun\nlet w = a[0:1]\nlisting e\n.endc\n.end\n")
    eout = run("_edge.cir")
    os.remove(edge)
    # the literal (unexpanded) node names must survive verbatim in the listing
    check("non-integer b[x:y] left literal", "b[x:y]" in eout and "b[x] b[y]" not in eout)
    check("malformed c[1:2:3] left literal", "c[1:2:3]" in eout)
    check("`.control` `let w = a[0:1]` not rewritten to a[0] a[1]",
          "a[0] a[1]" not in eout.split(".control")[-1] if ".control" in eout else True)

    print(f"\n{passed}/{checks} checks passed")
    print("ALL PASS" if passed == checks else "SOME FAILED")
    sys.exit(0 if passed == checks else 1)


if __name__ == "__main__":
    main()
