#!/usr/bin/env python3
"""
verify_clog2.py -- verifies Enhancement-101 ($clog2 correctness), through
the committed openvaf-r + ngspice.

`$clog2(n)` is the IEEE-1800 system function returning ceil(log2 n) -- the
number of bits needed to index `n` distinct values. Before E-101 openvaf-r
rejected every call ("expected 2 arguments", from a bad 2-arg signature) and,
once that was fixed, computed floor(log2 n)+1, which overcounts exact powers of
two (clog2(16) gave 5, not 4).

  [1] clog2_demo.va compiles ($clog2 accepts ONE argument)
  [2] constant-folded literals: clog2(1,2,3,4,7,8,16,17,1024) are exact
  [3] runtime parameter path: clog2(N) exact for N a power of two (16->4),
      a non-power (33->6), and the edge value 1 (->0)
"""
import math
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from _setup import VAF as OPENVAF, NG as NGSPICE

checks = passed = 0
def check(label, ok, detail=""):
    global checks, passed
    checks += 1; passed += bool(ok)
    print(f"[{'PASS' if ok else 'FAIL'}] {label}" + (f"  ({detail})" if detail and not ok else ""))

def clog2(x):
    return 0 if x <= 1 else (x - 1).bit_length()

def run_deck(text, name):
    p = os.path.join(HERE, name)
    with open(p, "w") as f:
        f.write(text)
    r = subprocess.run([NGSPICE, "-b", name], capture_output=True, text=True, cwd=HERE)
    return r.stdout + r.stderr

def opval(log, tag):
    m = re.search(rf"{re.escape(tag)}\s*=\s*(-?\d+)", log)
    return int(m.group(1)) if m else None

# clean prior artifacts
for f in ("clog2_demo.osdi", "_clit.sp", "_cpar.sp"):
    p = os.path.join(HERE, f)
    if os.path.exists(p):
        os.remove(p)

# [1] compile
r = subprocess.run([OPENVAF, "clog2_demo.va"], capture_output=True, text=True, cwd=HERE)
compiled = r.returncode == 0 and os.path.exists(os.path.join(HERE, "clog2_demo.osdi"))
check("clog2_demo.va compiles ($clog2 takes one argument)", compiled,
      (r.stderr or r.stdout).strip()[:140])

if compiled:
    # [2] constant-folded literals
    lits = [1, 2, 3, 4, 7, 8, 16, 17, 1024]
    echoes = "\n".join(f"echo lit{n}_ = $&@n1[c_{n}]" for n in lits)
    deck = ("* clog2 literal opvars\n"
            "vpp pp 0 1.0\nn1 pp 0 cl\n.model cl clog2_demo N=16\n"
            ".control\npre_osdi clog2_demo.osdi\nop\n"
            f"{echoes}\n.endc\n.end\n")
    log = run_deck(deck, "_clit.sp")
    for n in lits:
        got = opval(log, f"lit{n}_")
        exp = clog2(n)
        check(f"clog2({n}) == {exp}", got == exp, f"got {got}")

    # [3] runtime parameter path
    for N, exp in [(16, 4), (33, 6), (1, 0)]:
        deck = ("* clog2 runtime param\n"
                "vpp pp 0 1.0\nn1 pp 0 cl\n"
                f".model cl clog2_demo N={N}\n"
                ".control\npre_osdi clog2_demo.osdi\nop\n"
                "echo cN_ = $&@n1[cN]\n.endc\n.end\n")
        log = run_deck(deck, "_cpar.sp")
        got = opval(log, "cN_")
        check(f"clog2(N={N}) == {exp} (runtime path)", got == exp, f"got {got}")

# cleanup
for f in ("clog2_demo.osdi", "_clit.sp", "_cpar.sp"):
    p = os.path.join(HERE, f)
    if os.path.exists(p):
        os.remove(p)

print(f"\n{passed}/{checks} checks passed")
raise SystemExit(0 if passed == checks else 1)
