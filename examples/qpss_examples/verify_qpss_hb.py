#!/usr/bin/env python3
"""
verify_qpss_hb.py -- Enhancement-136: frequency-domain two-tone Harmonic Balance,
the TRUE (incommensurate-capable) quasi-periodic steady state, `qpss ... hb`.

Unlike the E-133 transient qpss (which needs a common beat period -- commensurate
tones only), the HB engine expands each node voltage in a 2-D Fourier series
v(t)=sum V_{k1,k2} e^{j(k1 w1 + k2 w2) t}, samples the devices on a 2-D PHASE grid
(so incommensurate tones just work) and solves the frequency-domain KCL residual by
Newton on the 2-D conversion matrix. The source spectrum is captured by an
oversampled least-squares almost-periodic Fourier transform (APFT).

Checks (numpy-free, parsed from stdout):

  [1] two-tone cubic, analytic IM3       -- |IM3|/|3rd harmonic| = 3 exactly (a=b)
  [2] odd nonlinearity                   -- even-order products ~ 0
  [3] 3:1 IP3 slope law                  -- 2x drive -> fund x2, IM3 x8
  [4] INCOMMENSURATE tones (sqrt2 ratio) -- converges + same IM3 (E-133 CANNOT)
  [5] HB vs E-133 transient (commensurate) -- the two methods agree
  [6] KLU vs Sparse                      -- solver-independent (bit-identical)
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


def run(deck, name="_qphb"):
    p = os.path.join(HERE, name + ".cir")
    with open(p, "w") as f:
        f.write(deck)
    try:
        r = subprocess.run([NGSPICE, "-b", p], capture_output=True, text=True, timeout=180)
    finally:
        if os.path.exists(p):
            os.remove(p)
    return r.stdout + r.stderr


# QPSS-HB row:  n         ( 2,-1)       9.000000e+08     3.531480e-04       90.000
_HBROW = re.compile(
    r"^\s+(\w+)\s+\(\s*(-?\d+),\s*(-?\d+)\)\s+[-\d.eE+]+\s+([-\d.eE+]+)\s+[-\d.eE+]+\s*$", re.M)
# E-133 transient row (no node column)
_TRROW = re.compile(
    r"^\s+\(\s*(-?\d+),\s*(-?\d+)\)\s+[-\d.eE+]+\s+([-\d.eE+]+)\s+[-\d.eE+]+\s*$", re.M)

def hb_spec(out, node="n"):
    d = {}
    for m in _HBROW.finditer(out):
        if m.group(1) == node:
            d[(int(m.group(2)), int(m.group(3)))] = float(m.group(4))
    return d

def tr_spec(out):
    d = {}
    for m in _TRROW.finditer(out):
        d[(int(m.group(1)), int(m.group(2)))] = float(m.group(3))
    return d

def converged(out):
    return "QPSS-HB: converged" in out


def deck(f1, f2, A=0.1, extra="", ctrl="", opt=""):
    return (f"* two-tone cubic\n"
            f"I1 0 n SIN(0 {A}m {f1})\nI2 0 n SIN(0 {A}m {f2})\n"
            f"R1 n 0 1k\nBnl n 0 I = 0.5e-3*V(n)*V(n)*V(n)\n{extra}"
            f"{opt}.control\n{ctrl}.endc\n.end\n")


print("Enhancement-136: two-tone Harmonic Balance (frequency-domain QPSS)")

# [1] analytic cubic IM3: for equal tones a=b in the small-signal limit,
# |IM3(2,-1)| / |3rd harmonic(3,0)| = 3 exactly (small A -> negligible 5th order).
out = run(deck("1.0G", "1.1G", A=0.02, ctrl="qpss v(n) 1.0G 1.1G hb 3 3\n"))
s = hb_spec(out)
im3, h3 = s.get((2, -1)), s.get((3, 0))
ratio = im3 / h3 if (im3 and h3) else 0
check("two-tone cubic: |IM3(2,-1)| / |3rd(3,0)| = 3 (analytic)",
      converged(out) and abs(ratio - 3.0) < 0.05, f"ratio={ratio:.4f}")
check("both fundamentals present and equal",
      s.get((1, 0), 0) > 1e-3 and abs(s.get((1, 0), 0) - s.get((0, 1), 1)) < 1e-3 * s.get((1, 0), 1))

# [2] odd (cubic) nonlinearity -> even-order mixing products vanish.
even = max(s.get((1, 1), 0), s.get((2, 0), 0), s.get((0, 2), 0))
check("odd nonlinearity: even-order products ~ 0",
      even < 1e-6 * s.get((1, 0), 1), f"max even={even:.2e}")

# [3] 3:1 IP3 slope: double the drive amplitude -> fundamental x2, IM3 x8.
o1 = hb_spec(run(deck("1.0G", "1.1G", A=0.05, ctrl="qpss v(n) 1.0G 1.1G hb 3 3\n")))
o2 = hb_spec(run(deck("1.0G", "1.1G", A=0.10, ctrl="qpss v(n) 1.0G 1.1G hb 3 3\n")))
fr = o2.get((1, 0), 0) / o1.get((1, 0), 1)
ir = o2.get((2, -1), 0) / o1.get((2, -1), 1)
check("3:1 IP3 slope law (fund x2, IM3 x8 per 2x drive)",
      abs(fr - 2.0) < 0.1 and abs(ir - 8.0) < 0.8, f"fund x{fr:.2f}, IM3 x{ir:.2f}")

# [4] INCOMMENSURATE tones (irrational ratio, no beat period) -- the whole point:
# the transient E-133 cannot do this; HB gives the same cubic IM3 ratio.
out = run(deck("1.0G", "1.4142135624G", A=0.02, ctrl="qpss v(n) 1.0G 1.4142135624G hb 3 3\n"))
s = hb_spec(out)
im3, h3 = s.get((2, -1)), s.get((3, 0))
ratio = im3 / h3 if (im3 and h3) else 0
check("INCOMMENSURATE tones converge with correct IM3 (E-133 cannot)",
      converged(out) and abs(ratio - 3.0) < 0.05, f"ratio={ratio:.4f} conv={converged(out)}")

# [5] HB agrees with the E-133 transient qpss for a commensurate pair.
out = run(deck("1.0G", "1.1G", ctrl="qpss v(n) 1.0G 1.1G hb 3 3\nqpss v(n) 1.0G 1.1G 12 3\n"))
hb = hb_spec(out)
tr = tr_spec(out)
a, b = hb.get((2, -1)), tr.get((2, -1))
check("HB vs E-133 transient agree on IM3 (commensurate)",
      a and b and abs(a - b) < 2e-2 * b, f"hb={a} tran={b}")

# [6] SOLVER PARITY: KLU and Sparse must give identical spectra.
def sol_spec(sol):
    return hb_spec(run(deck("1.0G", "1.4142135624G", extra="C1 n 0 200f\n",
                            opt=f".options {sol}\n",
                            ctrl="qpss v(n) 1.0G 1.4142135624G hb 3 3\n")))
sk, ss = sol_spec("klu"), sol_spec("sparse")
common = set(sk) & set(ss)
maxrel = max((abs(sk[k] - ss[k]) / max(ss[k], 1e-12) for k in common), default=1.0)
check("QPSS-HB solver-independent: KLU vs Sparse identical", maxrel < 1e-6, f"maxrel={maxrel:.2e}")

print(f"\n{'ALL PASS' if passed == checks else 'FAILURES'}: {passed}/{checks} passed")
sys.exit(0 if passed == checks else 1)
