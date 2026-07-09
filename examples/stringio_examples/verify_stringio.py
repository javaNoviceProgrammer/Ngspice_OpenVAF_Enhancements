#!/usr/bin/env python3
"""
verify_stringio.py -- verify Enhancement-11's string-formatting and file-reading
system functions ($swrite, $sformat, $sscanf, $fgets, $fscanf, $ferror)
end-to-end through version11's own openvaf-r + ngspice-46.

`stringio_demo` exercises each function (formatting into strings, parsing fields
out of strings and files, reading a line back from a file, querying the error
state) and writes a one-fact-per-line report to `stringio_out.txt`, which this
script checks. Runs via a Python subprocess (a bare ngspice heredoc misbehaves
in some shells -- a known project note); no dependencies beyond the stdlib.
"""
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
import sys
sys.path.insert(0, os.path.dirname(HERE))  # repo root, for _setup.py
from _setup import VAF as OPENVAF, NG as NGSPICE
from _setup import check_both_solvers as _check_both_solvers; _check_both_solvers(__file__)  # verify under BOTH KLU and Sparse solvers

R = 1000.0


def run():
    subprocess.run([OPENVAF, "stringio_demo.va", "-o", "stringio_demo.osdi"], cwd=HERE,
                   check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    deck = (f"* stringio\nvin p 0 dc 2\nn1 p 0 mm\n.model mm stringio_demo(R={R:g})\n"
            f".control\npre_osdi stringio_demo.osdi\nop\n.endc\n.end\n")
    with open(os.path.join(HERE, "_sio.cir"), "w") as fh:
        fh.write(deck)
    for f in ("stringio_out.txt", "rt.txt", "rt2.txt"):
        p = os.path.join(HERE, f)
        if os.path.exists(p):
            os.remove(p)
    subprocess.run([NGSPICE, "-b", "_sio.cir"], cwd=HERE, capture_output=True, text=True)
    path = os.path.join(HERE, "stringio_out.txt")
    if not os.path.exists(path):
        sys.exit("no stringio_out.txt produced")
    with open(path) as fh:
        return dict(ln.split("=", 1) for ln in fh.read().splitlines() if "=" in ln)


def check(desc, cond, results):
    results.append(bool(cond))
    print(f"    {'PASS' if cond else 'FAIL'}  {desc}")


def main():
    fields = run()
    print("stringio_demo report:")
    for k, v in fields.items():
        print(f"      {k}={v}")
    print("    ----")
    results = []

    # $sformat("R=%g G=%g", R, 1/R)
    check("$sformat", fields.get("sformat") == f"[R={R:g} G={1.0 / R:g}]", results)
    # $swrite("n=", 5, " ok") -> $write concatenation with spaces
    check("$swrite", fields.get("swrite") == "[n= 5 ok]", results)
    # $sscanf("42 3.14 hello", ...) -> count=3, 42, 3.14, hello
    check("$sscanf", fields.get("sscanf") == "3 42 3.14 [hello]", results)
    # $fgets read "line seven 7\n" -> length 13 (incl. newline)
    check("$fgets (length incl. newline)", fields.get("fgets") == "13", results)
    # $fscanf("99 2.5") -> count=2, 99, 2.5
    check("$fscanf", fields.get("fscanf") == "2 99 2.5", results)
    # $ferror on a good descriptor -> code 0, empty message
    check("$ferror (no error)", fields.get("ferror") == "0 []", results)

    ok = all(results)
    print(f"\n{'ALL PASS' if ok else 'SOME CHECKS FAILED'} "
          f"({sum(results)}/{len(results)})")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
