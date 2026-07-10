#!/usr/bin/env python3
"""
verify_qpac.py -- Enhancement-137: two-tone small-signal QPAC (quasi-periodic AC).

`qpac <f_in>` injects a small signal at f_in around the QPSS operating point retained
by a prior `qpss <expr> <f1> <f2> hb`, and reports the response at every sideband
f_in + k1*f1 + k2*f2 -- the two-tone analogue of PAC. The quasi-periodic operating
point mixes the small signal to the sidebands through the same 2-D conversion matrix
the QPSS Newton used as its Jacobian.

Checks (numpy-free, parsed from stdout):

  [1] reduce-to-AC        -- pump -> 0: direct (0,0) response = the plain .ac response,
                             and the conversion sidebands vanish
  [2] conversion ratio    -- with pump, |(1,1)| / |(2,0)| = 2 (from the v^2 pump term)
  [3] tone symmetry       -- equal tones: |(1,1)|=|(1,-1)|, |(2,0)|=|(0,2)|
  [4] no op-point         -- `qpac` with no prior `qpss ... hb` errors cleanly
  [5] KLU vs Sparse       -- solver-independent (bit-identical)
"""
import math
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from _setup import NG as NGSPICE

checks = passed = 0
def check(label, ok, detail=""):
    global checks, passed
    checks += 1; passed += bool(ok)
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  [{detail}]" if detail and not ok else ""))


def run(deck, name="_qpac"):
    p = os.path.join(HERE, name + ".cir")
    with open(p, "w") as f:
        f.write(deck)
    try:
        r = subprocess.run([NGSPICE, "-b", p], capture_output=True, text=True, timeout=180)
    finally:
        if os.path.exists(p):
            os.remove(p)
    return r.stdout + r.stderr


_ROW = re.compile(
    r"^\s+(\w+)\s+\(\s*(-?\d+),\s*(-?\d+)\)\s+[-\d.eE+]+\s+([-\d.eE+]+)\s+[-\d.eE+]+\s*$", re.M)

def qpac_spec(out, node="n"):
    """QPAC block -> {(k1,k2): |response|} for the given node."""
    d = {}
    block = out.split("QPAC:")[-1] if "QPAC:" in out else ""
    for m in _ROW.finditer(block):
        if m.group(1) == node:
            d[(int(m.group(2)), int(m.group(3)))] = float(m.group(4))
    return d


def deck(Apump, f_in="0.3G", extra="", opt="", pre=""):
    return (f"* qpac two-tone\n"
            f"I1 0 n SIN(0 {Apump} 1.0G)\nI2 0 n SIN(0 {Apump} 1.1G)\n"
            f"R1 n 0 1k\nBnl n 0 I = 0.5e-3*V(n)*V(n)*V(n)\nIac 0 n AC 1\n{extra}"
            f"{opt}.control\n{pre}qpss v(n) 1.0G 1.1G hb 3 3\nqpac {f_in}\n.endc\n.end\n")


print("Enhancement-137: two-tone small-signal QPAC (quasi-periodic AC)")

# [1] reduce-to-AC: with the pump ~ 0 the operating point is time-invariant, so the
# direct (0,0) response is exactly the plain .ac response (here R = 1 kOhm into a 1 A
# stimulus = 1000) and every conversion sideband vanishes.
s = qpac_spec(run(deck("1e-9")))
d00 = s.get((0, 0), 0)
sb = max(s.get((1, 1), 0), s.get((2, 0), 0), s.get((1, -1), 0), s.get((0, 2), 0))
check("reduce-to-AC: pump->0 gives (0,0) = R = 1000",
      abs(d00 - 1000.0) < 1.0, f"(0,0)={d00}")
check("reduce-to-AC: conversion sidebands vanish", sb < 1e-6 * d00, f"max sb={sb:.2e}")

# [2] conversion ratio: G(t)=3 g3 v^2 gives a pump v^2 whose (1,+-1) [f1+-f2] harmonic is
# twice its (2,0)/(0,2) [2f1] harmonic, so the converted sidebands share that 2:1 ratio.
s = qpac_spec(run(deck("0.1m")))
r11, r20 = s.get((1, 1), 0), s.get((2, 0), 0)
ratio = r11 / r20 if r20 else 0
check("conversion sideband ratio |(1,1)|/|(2,0)| = 2 (v^2 pump)",
      abs(ratio - 2.0) < 0.1, f"ratio={ratio:.4f}")
check("conversion sidebands present under pump", r11 > 1e-3, f"|(1,1)|={r11:.3e}")

# [3] equal tones -> symmetric conversion.
check("equal-tone symmetry |(1,1)|=|(1,-1)| and |(2,0)|=|(0,2)|",
      abs(s.get((1, 1), 0) - s.get((1, -1), 1)) < 1e-3 * s.get((1, 1), 1)
      and abs(s.get((2, 0), 0) - s.get((0, 2), 1)) < 1e-3 * s.get((2, 0), 1))

# [4] qpac without a prior qpss ... hb must error cleanly, not crash.
out = run("* no op-point\nR1 n 0 1k\nIac 0 n AC 1\n.control\nqpac 0.3G\n.endc\n.end\n")
check("qpac with no QPSS operating point errors cleanly",
      "no QPSS operating point" in out and "QPAC:" not in out)

# [5] SOLVER PARITY: KLU and Sparse must give identical QPAC responses.
sk = qpac_spec(run(deck("0.1m", opt=".options klu\n")))
ss = qpac_spec(run(deck("0.1m", opt=".options sparse\n")))
common = set(sk) & set(ss)
maxrel = max((abs(sk[k] - ss[k]) / max(ss[k], 1e-9) for k in common), default=1.0)
check("QPAC solver-independent: KLU vs Sparse identical", maxrel < 1e-6, f"maxrel={maxrel:.2e}")

print(f"\n{'ALL PASS' if passed == checks else 'FAILURES'}: {passed}/{checks} passed")
sys.exit(0 if passed == checks else 1)
