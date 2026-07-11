#!/usr/bin/env python3
"""
verify_qpxf.py -- Enhancement-141: two-tone small-signal QPXF (quasi-periodic
transfer function), the ADJOINT of QPAC.

`qpxf <output_node> <f_in>` runs, after a `qpss <expr> <f1> <f2> hb`, one adjoint solve
of the 2-D conversion matrix (H^T Psi = e_{out,(0,0)}) and dots each sideband block of
Psi with the netlist AC-source pattern -- giving the transfer from an input at every
sideband f_in + k1*f1 + k2*f2 to the chosen output at f_in. By the reciprocity identity
(H^-1 B)_out = (H^-T e_out)^T B, the sideband-(0,0) transfer is bit-identical to the
QPAC response at that node -- the cross-check that pins the adjoint (cf. PXF/PAC, E-125).

Checks (numpy-free, parsed from stdout):

  [1] reciprocity         -- QPXF (0,0) == QPAC (0,0) response (bit-identical)
  [2] sideband reciprocity -- |QPXF(k1,k2)| == |QPAC(k1,k2)| for the conversion sidebands
  [3] reduce-to-XF        -- pump->0: (0,0) = the plain transfer (R), sidebands vanish
  [4] no op-point         -- `qpxf` with no `qpss ... hb` errors cleanly
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


def run(deck, name="_qpxf"):
    p = os.path.join(HERE, name + ".cir")
    with open(p, "w") as f:
        f.write(deck)
    try:
        r = subprocess.run([NGSPICE, "-b", p], capture_output=True, text=True, timeout=180)
    finally:
        if os.path.exists(p):
            os.remove(p)
    return r.stdout + r.stderr


# QPAC row (has a node column):  n   ( 0, 0)   3.0e+08   9.857835e+02   0.000
_QPAC = re.compile(r"^\s+\w+\s+\(\s*(-?\d+),\s*(-?\d+)\)\s+[-\d.eE+]+\s+([-\d.eE+]+)\s+[-\d.eE+]+\s*$", re.M)
# QPXF row (no node column):        ( 0, 0)   3.0e+08   9.857835e+02   0.000
_QPXF = re.compile(r"^\s+\(\s*(-?\d+),\s*(-?\d+)\)\s+[-\d.eE+]+\s+([-\d.eE+]+)\s+[-\d.eE+]+\s*$", re.M)

def qpac_spec(out):
    blk = out.split("QPAC:")[-1].split("QPXF:")[0] if "QPAC:" in out else ""
    return {(int(m.group(1)), int(m.group(2))): float(m.group(3)) for m in _QPAC.finditer(blk)}

def qpxf_spec(out):
    blk = out.split("QPXF:")[-1] if "QPXF:" in out else ""
    return {(int(m.group(1)), int(m.group(2))): float(m.group(3)) for m in _QPXF.finditer(blk)}


def deck(Apump, extra="", opt="", withqpac=True):
    ctrl = "qpss v(n) 1.0G 1.1G hb 3 3\n"
    if withqpac:
        ctrl += "qpac 0.3G\n"
    ctrl += "qpxf n 0.3G\n"
    return (f"* qpxf two-tone\n"
            f"I1 0 n SIN(0 {Apump} 1.0G)\nI2 0 n SIN(0 {Apump} 1.1G)\n"
            f"R1 n 0 1k\nBnl n 0 I = 0.5e-3*V(n)*V(n)*V(n)\nIac 0 n AC 1\n{extra}"
            f"{opt}.control\n{ctrl}.endc\n.end\n")


print("Enhancement-141: two-tone QPXF (quasi-periodic transfer function)")

out = run(deck("0.1m"))
ac = qpac_spec(out)
xf = qpxf_spec(out)
# [1] reciprocity at (0,0): bit-identical to QPAC.
a00, x00 = ac.get((0, 0)), xf.get((0, 0))
check("reciprocity: QPXF (0,0) transfer == QPAC (0,0) response (bit-identical)",
      a00 and x00 and abs(a00 - x00) < 1e-9 * a00, f"qpac={a00} qpxf={x00}")

# [2] the conversion sidebands match QPAC in magnitude too.
common = [(1, 1), (1, -1), (2, 0), (0, 2)]
ok = all(k in ac and k in xf and abs(ac[k] - xf[k]) < 1e-6 * max(ac[k], 1e-12) for k in common)
check("sideband reciprocity: |QPXF| == |QPAC| for the conversion sidebands",
      ok, f"qpac={{k:ac.get(k) for k in common}} qpxf={{k:xf.get(k) for k in common}}")

# [3] reduce-to-XF: pump ~ 0 -> the operating point is time-invariant, so the (0,0)
# transfer is the plain linear transfer (1 A into R=1k => 1000) and the conversion
# sidebands vanish.
xf0 = qpxf_spec(run(deck("1e-9", withqpac=False)))
sb = max(xf0.get((1, 1), 0), xf0.get((2, 0), 0), xf0.get((1, -1), 0))
check("reduce-to-XF: pump->0 gives (0,0) = R = 1000",
      xf0.get((0, 0)) and abs(xf0[(0, 0)] - 1000.0) < 1.0, f"(0,0)={xf0.get((0,0))}")
check("reduce-to-XF: conversion sidebands vanish", sb < 1e-6 * xf0.get((0, 0), 1), f"max sb={sb:.2e}")

# [4] qpxf without a prior qpss ... hb must error cleanly.
o = run("* no op\nR1 n 0 1k\nIac 0 n AC 1\n.control\nqpxf n 0.3G\n.endc\n.end\n")
check("qpxf with no QPSS operating point errors cleanly",
      "no QPSS operating point" in o and "QPXF:" not in o)

# [5] solver parity.
xk = qpxf_spec(run(deck("0.1m", opt=".options klu\n", withqpac=False)))
xs = qpxf_spec(run(deck("0.1m", opt=".options sparse\n", withqpac=False)))
cm = set(xk) & set(xs)
maxrel = max((abs(xk[k] - xs[k]) / max(xs[k], 1e-9) for k in cm), default=1.0)
check("QPXF solver-independent: KLU vs Sparse identical", maxrel < 1e-6, f"maxrel={maxrel:.2e}")

print(f"\n{'ALL PASS' if passed == checks else 'FAILURES'}: {passed}/{checks} passed")
sys.exit(0 if passed == checks else 1)
