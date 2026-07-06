#!/usr/bin/env python3
"""
verify_casexz.py -- Enhancement-78: the `casex`/`casez` don't-care case
statements, end-to-end through the committed openvaf-r + ngspice.

The don't-care digits (`x`/`X`, `z`/`Z`, `?`) of a based literal written
directly as a casex/casez item form a comparison mask: the arm matches
when the discriminant equals the item on every *care* bit. `casex`
treats x, z and ? as don't-cares; `casez` only z and ?.

  [1] an 8-way self-checking bitmask module (the E-37 audit technique)
      pins the semantics exactly: casex x/z/? masking, casez z/?-only,
      fully-specified mismatch falling to default, first-match-wins arm
      order, and plain `case` unchanged -- expected score 63/63;
  [2] the classic idiom: a casex priority encoder whose 4-bit request
      word comes from the model card -- the highest set bit wins at
      every value, including the all-zero default arm;
  [3] the three diagnostics: a don't-care literal outside casex/casez
      items, an `x` digit in a `casez` item, and a non-integer (real)
      casex discriminant -- each a clean, located compile error.

Every SPICE deck starts with a title line (SPICE treats line 1 as the title!).
"""
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))  # the examples/ dir, for _setup.py
from _setup import VAF as OPENVAF, NG as NGSPICE

checks = []


def check(label, cond):
    checks.append(bool(cond))
    print(f"  {'PASS' if cond else 'FAIL'}  {label}")


def compile_va(src, out=None):
    out = out or src.replace(".va", ".osdi")
    return subprocess.run([OPENVAF, src, "-o", out], cwd=HERE,
                          capture_output=True, text=True, timeout=120)


def run(deck, name):
    open(os.path.join(HERE, f"_{name}.cir"), "w").write(deck)
    r = subprocess.run([NGSPICE, "-b", f"_{name}.cir"], cwd=HERE,
                       capture_output=True, text=True, timeout=120)
    return r.stdout + r.stderr


def current(out):
    m = re.search(r"-i\(vin\)\s*=\s*([-\d.e+]+)", out)
    return float(m.group(1)) if m else None


def main():
    print("[1] self-checking semantics bitmask (expect 63/63)")
    r = compile_va("casexz_probe.va")
    check("probe compiles", r.returncode == 0)
    out = run("* probe\nvin in 0 dc 1\nn1 in 0 mm\n.model mm casexz_probe()\n"
              ".control\npre_osdi casexz_probe.osdi\nop\nprint -i(vin)\n"
              ".endc\n.end\n", "p1")
    i = current(out)
    check(f"score 63/63 (got {i*1e3:.0f} if PASS)" if i else "score MISSING",
          i is not None and abs(i - 63e-3) < 1e-12)

    print("[2] casex priority encoder across model-card request words")
    r = compile_va("priority_enc.va")
    check("encoder compiles", r.returncode == 0)
    expect = {0: 0, 1: 1, 2: 2, 3: 2, 4: 4, 6: 4, 8: 8, 11: 8, 15: 8}
    ok = True
    for sel, grant in expect.items():
        out = run(f"* enc sel={sel}\nvin in 0 dc 1\nn1 in 0 mm\n"
                  f".model mm priority_enc(sel={sel})\n"
                  f".control\npre_osdi priority_enc.osdi\nop\nprint -i(vin)\n"
                  f".endc\n.end\n", "p2")
        i = current(out)
        if i is None or abs(i - grant * 1e-3) > 1e-12:
            ok = False
            print(f"        sel={sel}: expected {grant} mA, got {i}")
    check("highest set bit wins at all 9 request words", ok)

    print("[3] diagnostics")
    r = compile_va("d1.va")
    check("stray don't-care literal rejected",
          r.returncode != 0
          and "don't-care digits are only allowed in casex/casez" in r.stderr)
    r = compile_va("d2.va")
    check("x digit in casez item rejected",
          r.returncode != 0 and "not don't-cares in casez" in r.stderr)
    r = compile_va("d3.va")
    check("real casex discriminant rejected",
          r.returncode != 0 and "requires an integer discriminant" in r.stderr)

    n_pass = sum(checks)
    n_fail = len(checks) - n_pass
    print()
    print(("ALL PASS" if n_fail == 0 else "FAILURES")
          + f": {n_pass} passed, {n_fail} failed")
    return 1 if n_fail else 0


if __name__ == "__main__":
    raise SystemExit(main())
