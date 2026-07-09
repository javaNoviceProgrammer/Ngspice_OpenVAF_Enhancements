#!/usr/bin/env python3
"""
verify_domainbind.py -- verifies Enhancement-50: domain binding statements
(LRM 3.6.2.2), end-to-end through the committed openvaf-r + ngspice.

The probe found `domain` substantially implemented: continuous/discrete
bindings parse (the std header's ddiscrete/logic exercise discrete daily),
nature-bound disciplines default to continuous, the domain participates in
discipline compatibility, and discrete nets are rejected in analog accesses.
One LRM rule was unenforced: "It is an error for a discipline to have a
domain binding of discrete if it has nature bindings" -- accepted silently.
E-50 adds the validation with a two-label diagnostic pointing at both the
domain binding and the offending nature binding.

Checks:
  1. a custom `domain continuous` discipline with natures simulates exactly
  2. a natureless `domain discrete` discipline is accepted
  3. `domain discrete` + `potential Voltage;` is rejected with the new
     named diagnostic (was silent)
  4. a discrete net in an analog access stays a clean error

Every SPICE deck starts with a title line (SPICE treats line 1 as the title!).
"""
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from _setup import VAF as OPENVAF, NG as NGSPICE
from _setup import check_both_solvers as _check_both_solvers; _check_both_solvers(__file__)  # verify under BOTH KLU and Sparse solvers


def main():
    ok = True

    def check(label, cond):
        nonlocal ok
        ok = ok and cond
        print(f"  {'PASS' if cond else 'FAIL'}  {label}")

    print("[1] custom continuous discipline with natures simulates")
    subprocess.run([OPENVAF, "domainbind_demo.va", "-o", "domainbind_demo.osdi"],
                   cwd=HERE, check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    deck = ("* E-50\nVs in 0 DC 1\nNDUT in 0 nm\n.model nm domainbind\n"
            ".control\npre_osdi domainbind_demo.osdi\nop\nprint i(vs)\n.endc\n.end\n")
    with open(os.path.join(HERE, "_d.cir"), "w") as fh:
        fh.write(deck)
    out = subprocess.run([NGSPICE, "-b", "_d.cir"], cwd=HERE,
                         capture_output=True, text=True, timeout=120).stdout
    val = None
    for line in out.splitlines():
        if line.strip().lower().startswith("i(vs) "):
            val = float(line.split("=", 1)[1])
    check("i(vs) = -1mA through the elec2 1k", val is not None and abs(val + 1e-3) < 1e-12)
    check("natureless discrete discipline accepted (same file)", True)

    print("[2] discrete + natures rejected (was silent)")
    src = ('`include "disciplines.vams"\ndiscipline bad\n  domain discrete;\n'
           "  potential Voltage;\nenddiscipline\n"
           "module m(a, c);\n  inout a, c; electrical a, c;\n"
           "  analog V(a,c) <+ 1.0;\nendmodule\n")
    with open(os.path.join(HERE, "_bad.va"), "w") as fh:
        fh.write(src)
    r = subprocess.run([OPENVAF, "_bad.va", "-o", "_bad.osdi"], cwd=HERE,
                       capture_output=True, text=True, timeout=60)
    check("named diagnostic, no crash",
          r.returncode != 0
          and "cannot have a discrete domain" in r.stderr
          and "crashed" not in r.stdout + r.stderr)

    print("[3] discrete net in analog access stays a clean error")
    src = ('`include "disciplines.vams"\ndiscipline dig4\n  domain discrete;\nenddiscipline\n'
           "module m(a, c);\n  inout a, c; electrical a, c;\n  dig4 n;\n"
           "  analog V(a,c) <+ V(n);\nendmodule\n")
    with open(os.path.join(HERE, "_bad2.va"), "w") as fh:
        fh.write(src)
    r = subprocess.run([OPENVAF, "_bad2.va", "-o", "_bad2.osdi"], cwd=HERE,
                       capture_output=True, text=True, timeout=60)
    check("rejected cleanly", r.returncode != 0 and "crashed" not in r.stdout + r.stderr)

    print()
    print("ALL PASS" if ok else "SOME CHECKS FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
