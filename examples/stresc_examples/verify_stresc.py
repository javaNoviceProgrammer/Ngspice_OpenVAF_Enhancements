#!/usr/bin/env python3
"""
verify_stresc.py -- verifies Enhancement-48: string literal escape sequences
(LRM 2.7.1), end-to-end through the committed openvaf-r + ngspice.

The LRM escape set is \\n, \\t, \\\\, \\", and \\ddd (one to three octal
digits). Previously: octal escapes were unsupported ("\\101" printed
literally), and the unescaper -- a chain of sequential str::replace calls
with \\n handled before \\\\ -- corrupted overlapping sequences: "a\\\\nb"
(a literal backslash followed by 'n') became a backslash plus a REAL newline.
Enhancement-48 replaces it with a single left-to-right pass covering the full
LRM set; a backslash-newline keeps the newline (line-continuation extension)
and unknown escapes are preserved verbatim. Every string consumer (format
strings, string values, attribute strings, lint names) already routed through
the one function, so the fix applies everywhere at once.

Checks:
  1. $strobe output matrix: tab, newline, backslash, quote render as the
     real characters; "a\\\\nb" prints a literal backslash-n (the old bug
     printed a newline); octal \\101\\102\\103 prints ABC; \\060\\61 prints 01
  2. compile-time consistency: "\\101\\102" == "AB", overlap self-equality,
     and unknown escapes compare consistently (module output = 7 exactly)

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
    subprocess.run([OPENVAF, "stresc_demo.va", "-o", "stresc_demo.osdi"],
                   cwd=HERE, check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    deck = ("* E-48 string escapes\nNDUT out 0 nm\nR1 out 0 1k\n"
            ".model nm strescape\n"
            ".control\npre_osdi stresc_demo.osdi\nop\nprint v(out)\n.endc\n.end\n")
    with open(os.path.join(HERE, "_s.cir"), "w") as fh:
        fh.write(deck)
    out = subprocess.run([NGSPICE, "-b", "_s.cir"], cwd=HERE,
                         capture_output=True, text=True, timeout=120).stdout

    ok = True

    def check(label, cond):
        nonlocal ok
        ok = ok and cond
        print(f"  {'PASS' if cond else 'FAIL'}  {label}")

    print("[1] $strobe escape rendering")
    check("tab renders", "E1:[a\tb]" in out)
    check("newline splits the line", "E2:[l1\nl2]" in out.replace("\r\n", "\n"))
    check("literal backslash", "E3:[back\\slash]" in out)
    check('quote', 'E4:[quote"q]' in out)
    check("backslash-then-n stays literal (old bug: real newline)",
          "E5:[a\\nb]" in out and "E5:[a\nb]" not in out.replace("E5:[a\\nb]", ""))
    check("octal \\101\\102\\103 -> ABC", "E6:[ABC]" in out)
    check("octal digit forms -> 01", "E7:[01]" in out)

    print("[2] compile-time string consistency")
    val = None
    for line in out.splitlines():
        if line.strip().lower().startswith("v(out) "):
            val = float(line.split("=", 1)[1])
    check("octal==plain + overlap + unknown-escape equality = 7",
          val is not None and abs(val - 7.0) < 1e-12)

    print()
    print("ALL PASS" if ok else "SOME CHECKS FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
