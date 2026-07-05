#!/usr/bin/env python3
"""
verify_netinit.py -- verifies Enhancement-45: net initialization (nodeset
values, LRM 3.6.3.2) and net/branch attribute access (LRM 5.5.3), end-to-end
through the committed openvaf-r + ngspice.

Net initialization: `electrical a = 5.0;` -- the constant initializer is used
by the analog solver as a NODESET (initial-guess) value for the net's
potential. Previously a parse error. The value travels net declaration ->
item-tree -> OSDI node descriptor (new `nodeset` field, NAN = none; OSDI minor
version bumped to 0.5 since the node-array stride changed) -> ngspice, which
applies it as node->nodeset/nsGiven at instance setup for internal nodes and
connected terminals (netlist `.nodeset` wins on terminals).

Attribute access: `net.potential.abstol` / `net.flow.abstol` /
`branch.potential.abstol` -- previously "expected a scope but found node".
Resolution goes net -> discipline -> nature -> attribute through the same
machinery as branch attributes (which were themselves unreachable from module
bodies) and Enhancement-39's inheritance-aware nature lookup.

All bistable checks use x = tanh(5x), whose solutions are 0 and +-0.999909:
the nodeset selects which one Newton-Raphson converges to.

Checks:
  1. no initializer  -> converges to the trivial 0 solution
  2. `electrical m =  1.0;` (internal net) -> +0.999909
  3. `electrical m = -1.0;` -> -0.999909
  4. PORT initializer nodesets the terminal -> +0.999909;
     netlist `.nodeset v(q)=-1` overrides it -> -0.999909
  5. bus `electrical [0:2] b = '{0.5,-1.0,2.0};` -> per-bit branches: 90.99
  6. initializer inside a flattened submodule instance survives -> -0.999909
  7. attribute access: 1e6*q.potential.abstol + 1e12*q.flow.abstol
     + 1e6*br.potential.abstol = 3.0 exactly (electrical: 1e-6 / 1e-12)
  8. non-constant initializer (`= 2*p`) rejected with a named diagnostic
  9. unknown attribute (`a.potential.nonsense`) rejected cleanly

Every SPICE deck starts with a title line (SPICE treats line 1 as the title!).
"""
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from _setup import VAF as OPENVAF, NG as NGSPICE

SOL = 0.999909


def run(deck, *names):
    with open(os.path.join(HERE, "_n.cir"), "w") as fh:
        fh.write(deck)
    out = subprocess.run([NGSPICE, "-b", "_n.cir"], cwd=HERE,
                         capture_output=True, text=True, timeout=120).stdout
    vals = {}
    for line in out.splitlines():
        stripped = line.strip().lower()
        for nm in names:
            if stripped.startswith(nm.lower() + " ") and nm not in vals:
                vals[nm] = float(line.split("=", 1)[1].strip())
    return vals


def op_deck(model, extra_lines=""):
    return (f"* E-45 {model}\nNDUT q nm\nR1 q 0 1G\n.model nm {model}\n{extra_lines}"
            ".control\npre_osdi netinit_demo.osdi\nop\nprint v(q)\n.endc\n.end\n")


def main():
    subprocess.run([OPENVAF, "netinit_demo.va", "-o", "netinit_demo.osdi"],
                   cwd=HERE, check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    ok = True

    def check(label, got, want, tol=1e-4):
        nonlocal ok
        good = abs(got - want) < tol
        ok = ok and good
        print(f"  {'PASS' if good else 'FAIL'}  {label}   got {got:.6e}, want {want:.6e}")

    print("[1] no initializer: trivial 0 solution")
    check("bist_none -> 0", run(op_deck("bist_none"), "v(q)")["v(q)"], 0.0, 1e-9)

    print("[2] internal net nodeset selects the branch")
    check("bist_pos -> +sol", run(op_deck("bist_pos"), "v(q)")["v(q)"], SOL)
    check("bist_neg -> -sol", run(op_deck("bist_neg"), "v(q)")["v(q)"], -SOL)

    print("[3] port-net initializer nodesets the terminal; netlist wins")
    check("bist_port -> +sol", run(op_deck("bist_port"), "v(q)")["v(q)"], SOL)
    check(".nodeset v(q)=-1 overrides",
          run(op_deck("bist_port", ".nodeset v(q)=-1\n"), "v(q)")["v(q)"], -SOL)

    print("[4] bus initializer: per-bit leaves")
    check("bist_bus -> (1 - 10 + 100)*sol = 90.99",
          run(op_deck("bist_bus"), "v(q)")["v(q)"], 91.0 * SOL, 1e-2)

    print("[5] initializer inside a flattened submodule instance")
    check("bwrap -> -sol", run(op_deck("bwrap"), "v(q)")["v(q)"], -SOL)

    print("[6] net & branch attribute access (LRM 5.5.3)")
    deck = ("* attrs\nNDUT q s nm\nR1 q 0 1k\nR2 s 0 1G\n.model nm attrs\n"
            ".control\npre_osdi netinit_demo.osdi\nop\nprint v(s)\n.endc\n.end\n")
    check("1e6*pot.abstol + 1e12*flow.abstol + 1e6*br.pot.abstol = 3",
          run(deck, "v(s)")["v(s)"], 3.0, 1e-9)

    print("[7] rejections")
    bads = [
        ("non-constant initializer",
         "parameter real p = 1.0;\n  electrical m = 2*p;\n  analog I(m) <+ V(m)/1e3;",
         "net nodeset initializer is not a constant"),
        ("unknown attribute",
         "electrical m;\n  analog V(m) <+ m.potential.nonsense;",
         "'nonsense' was not found in 'Voltage'"),
    ]
    for label, body, msg in bads:
        src = ('`include "disciplines.vams"\nmodule bad(q);\n'
               f"  inout q; electrical q;\n  {body}\nendmodule\n")
        with open(os.path.join(HERE, "_bad.va"), "w") as fh:
            fh.write(src)
        r = subprocess.run([OPENVAF, "_bad.va", "-o", "_bad.osdi"], cwd=HERE,
                           capture_output=True, text=True, timeout=60)
        good = (r.returncode != 0 and msg in r.stderr
                and "crashed" not in r.stdout + r.stderr)
        ok = ok and good
        print(f"  {'PASS' if good else 'FAIL'}  {label}: named diagnostic, no crash")

    print()
    print("ALL PASS" if ok else "SOME CHECKS FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
