#!/usr/bin/env python3
"""
verify_defparam.py -- verifies Enhancement-58: `defparam` hierarchical
parameter override, end-to-end through the committed openvaf-r + ngspice.

Before E-58 `defparam` did not parse at all (it was a reserved word with no
grammar rule -- `defparam u1.r = 2e3;` produced "'defparam' was not found in
the current scope"). Now:
  * DEFPARAM_KW is a keyword token with a parser rule producing a DEFPARAM
    syntax node (deliberately NOT a typed ModuleItem, so the later compiler
    stages never see it);
  * the E-5 elaboration pass resolves each defparam target through the same
    instance-chain rewrite E-49 uses for hierarchical references
    (`u1.u2.r` -> `u1__u2__r`) and rewrites the flattened parameter's
    default. defparam has higher precedence than an instance `#(...)`
    override (LRM 2.6); the override expression may reference the enclosing
    module's own parameters; an unresolved target is a hard error.

Checks (exact conductances measured via op-point current at V=1):
  1. dp_basic: `defparam u1.r = 2e3` overrides the 1k default -> I = 0.5 mA
  2. dp_deep: two-level `defparam u1.u2.r = 4e3`; `up.r`/`up.g` via a
     multi-assignment defparam that OVERRIDES the instance `#(.r(5e3))`
     (2k not 5k) plus adds g = 1e-3 -> total I = 1/2k + 1e-3 + 1/4k = 1.75 mA
  3. dp_expr: `defparam u1.r = 2.0*scale` (scale = 3e3) -> 6k -> I = 1/6 mA
  4. an unresolved defparam target (`u1.typo`) is a compile error naming the
     original source path

Every SPICE deck starts with a title line (SPICE treats line 1 as the title!).
"""
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from _setup import VAF as OPENVAF, NG as NGSPICE


def op_current(model):
    deck = (f"* defparam {model}\nV1 a 0 DC 1\nNX a 0 mm\n.model mm {model}\n"
            f".control\nset numdgt=12\npre_osdi defparam_demo.osdi\nop\n"
            f"print i(v1)\n.endc\n.end\n")
    with open(os.path.join(HERE, "_dp.cir"), "w") as fh:
        fh.write(deck)
    out = subprocess.run([NGSPICE, "-b", "_dp.cir"], cwd=HERE,
                         capture_output=True, text=True, timeout=120).stdout
    m = re.search(r"i\(v1\)\s*=\s*(\S+)", out)
    return -float(m.group(1)) if m else None   # current INTO the device


def main():
    subprocess.run([OPENVAF, "defparam_demo.va", "-o", "defparam_demo.osdi"],
                   cwd=HERE, check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    ok = True

    def check(label, got, want, tol=1e-8):
        nonlocal ok
        good = got is not None and abs(got - want) < tol
        ok = ok and good
        g = "None" if got is None else f"{got:.9e}"
        print(f"  {'PASS' if good else 'FAIL'}  {label}   got {g}, want {want:.9e}")

    print("[1] dp_basic: defparam u1.r = 2e3 (1k default -> 2k)")
    check("I = 1/2000", op_current("dp_basic"), 1 / 2000)

    print("[2] dp_deep: deep target + multi-assign + precedence over #()")
    check("I = 1/2k + 1e-3 + 1/4k", op_current("dp_deep"),
          1 / 2000 + 1e-3 + 1 / 4000)

    print("[3] dp_expr: defparam u1.r = 2.0*scale (scale=3k -> 6k)")
    check("I = 1/6000", op_current("dp_expr"), 1 / 6000)

    print("[4] unresolved defparam target is a compile error")
    bad = ("`include \"disciplines.vams\"\n"
           "module dp_leaf(a,c); inout a,c; electrical a,c; parameter real r=1e3;"
           " analog I(a,c)<+V(a,c)/r; endmodule\n"
           "module dp_bad(a,c); inout a,c; electrical a,c;\n"
           "  dp_leaf u1(a,c);\n  defparam u1.nosuch = 5e3;\nendmodule\n")
    with open(os.path.join(HERE, "_dp_bad.va"), "w") as fh:
        fh.write(bad)
    bad_osdi = os.path.join(HERE, "_dp_bad.osdi")
    if os.path.exists(bad_osdi):
        os.remove(bad_osdi)
    r = subprocess.run([OPENVAF, "_dp_bad.va", "-o", bad_osdi],
                       cwd=HERE, capture_output=True, text=True, timeout=60)
    msg = r.stdout + r.stderr
    # openvaf-r prints diagnostics but exits 0; a failed compile emits no .osdi
    good = ("did not resolve to any parameter" in msg
            and "u1.nosuch" in msg
            and not os.path.exists(bad_osdi))
    ok = ok and good
    print(f"  {'PASS' if good else 'FAIL'}  rejected naming the source path 'u1.nosuch'")

    print()
    print("ALL PASS" if ok else "SOME CHECKS FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
