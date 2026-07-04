#!/usr/bin/env python3
"""
verify_escid.py -- verifies Enhancement-46: escaped identifiers (LRM A.9.3)
and integer literal bases (LRM A.8.7), end-to-end through the committed
openvaf-r + ngspice.

Integer literals: only plain decimals worked. Based literals ('h1F, 'o17,
'b1010, 'd42, sized 8'hFF, signed 8'shFF) were "unexpected token" -- the lexer
had no based-literal tokenization (only a commented-out sketch) -- and a legal
underscore separator (1_000_00) CRASHED the compiler ("IntNumber token must be
valid float syntax too"). E-46 tokenizes `[size]'[s]<base><digits>` (digits
validated per base while lexing, so an invalid digit or a bare 'h surfaces as
an ordinary parse error, never a silent 0), masks to the declared size,
sign-extends under `s`, and strips `_` separators in every number form.

Escaped identifiers: the lexer already emitted EscapedIdent tokens, but
Name::resolve stripped the identifier's LAST character along with the
backslash, so `\\foo` never named the same thing as `foo`; and the E-5
flattening re-rendered instance-prefixed names unescaped, so an escaped net
inside a submodule broke the synthesized text ("unexpected token '-'").

Checks:
  1. all literal bases/sizes/signs/underscores: 0.1443252345 V exactly
  2. escaped nets/vars/params with specials (\\2wire, \\value#, \\r+val):
     series 1k + r+val*1k with a small current source -- exact op values,
     and the r+val=2 default doubles the second resistor
  3. \\mid == mid (escaped and plain spellings are the same net): 2k series
  4. escaped net inside a flattened submodule instance: 2k series
  5. \\module (keyword spelling) as a net name
  6. malformed literals ('h, 'sh, 'b12, 8'squark) are clean errors

Every SPICE deck starts with a title line (SPICE treats line 1 as the title!).
"""
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from _setup import VAF as OPENVAF, NG as NGSPICE


def run(deck, *names):
    with open(os.path.join(HERE, "_e.cir"), "w") as fh:
        fh.write(deck)
    out = subprocess.run([NGSPICE, "-b", "_e.cir"], cwd=HERE,
                         capture_output=True, text=True, timeout=120).stdout
    vals = {}
    for line in out.splitlines():
        stripped = line.strip().lower()
        for nm in names:
            if stripped.startswith(nm.lower() + " ") and nm not in vals:
                vals[nm] = float(line.split("=", 1)[1].strip())
    return vals


def v_deck(model):
    return (f"* E-46 {model}\nNDUT out 0 nm\nR1 out 0 1k\n.model nm {model}\n"
            ".control\nset numdgt=12\npre_osdi escid_demo.osdi\nop\nprint v(out)\n.endc\n.end\n")


def i_deck(model):
    return (f"* E-46 {model}\nVs in 0 DC 1\nNDUT in 0 nm\n.model nm {model}\n"
            ".control\npre_osdi escid_demo.osdi\nop\nprint i(vs)\n.endc\n.end\n")


def main():
    subprocess.run([OPENVAF, "escid_demo.va", "-o",
                    os.path.join(HERE, "escid_demo.osdi")],
                   cwd=HERE, check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    ok = True

    def check(label, got, want, tol=1e-9):
        nonlocal ok
        good = abs(got - want) < tol
        ok = ok and good
        print(f"  {'PASS' if good else 'FAIL'}  {label}   got {got:.7e}, want {want:.7e}")

    print("[1] all integer literal forms")
    check("hex/oct/bin/dec/sized/signed/underscores/wrap = 0.1443252345",
          run(v_deck("literals"), "v(out)")["v(out)"], 0.1443252345, 1e-12)

    print("[2] escaped identifiers with specials (\\2wire, \\value#, \\r+val)")
    # series 1k + (r+val=2)*1k = 3k from 1V, minus \value#/1e7 = 0.3uA source
    got = run(i_deck("escids"), "i(vs)")["i(vs)"]
    check("i(vs): 3k series + 0.3uA shift", got, -(1.0/3000.0) + 3e-7/1.5, 1e-6)

    print("[3] \\mid == mid: escaped and plain spellings, one net")
    check("2k series -> -0.5mA", run(i_deck("escsame"), "i(vs)")["i(vs)"], -5e-4, 1e-12)

    print("[4] escaped net inside a flattened submodule")
    check("2k series -> -0.5mA", run(i_deck("escnest"), "i(vs)")["i(vs)"], -5e-4, 1e-12)

    print("[5] keyword spelling \\module as a net name")
    check("2k series -> -0.5mA", run(i_deck("esckw"), "i(vs)")["i(vs)"], -5e-4, 1e-12)

    print("[6] malformed literals are clean errors")
    for lit in ["'h", "'sh", "'b12", "8'squark"]:
        src = ('`include "disciplines.vams"\nmodule bad(a, c);\n'
               "  inout a, c; electrical a, c;\n"
               f"  integer v = {lit};\n  analog V(a,c) <+ 1e-6*v;\nendmodule\n")
        with open(os.path.join(HERE, "_bad.va"), "w") as fh:
            fh.write(src)
        r = subprocess.run([OPENVAF, "_bad.va", "-o", "_bad.osdi"], cwd=HERE,
                           capture_output=True, text=True, timeout=60)
        good = r.returncode != 0 and "crashed" not in r.stdout + r.stderr
        ok = ok and good
        print(f"  {'PASS' if good else 'FAIL'}  {lit}: rejected, no crash")

    print()
    print("ALL PASS" if ok else "SOME CHECKS FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
