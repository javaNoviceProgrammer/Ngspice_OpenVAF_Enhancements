#!/usr/bin/env python3
"""verify_txlcpl.py -- Enhancements 904 to 908: the KSPICE lossy lines TXL and
CPL. F9 of the analyses correctness campaign of 2026-10-16.

The references are the exact line, the telegrapher's two-port
Y11 = coth(g l)/Zc, Y12 = -csch(g l)/Zc, and the circuit's own operating point.

E-904: the transient starts from the operating point.
  [1] a TXL carrying dc current holds its operating point under a constant
      source (E-903: the far end dipped from 0.496 V to 0.183 V)
  [2] the same for a CPL line
E-905: the characteristic admittance's history update.
  [3] a TXL driven above its RC corner R/L: the transient's fundamental within
      1e-5 of the exact line (E-903: 3.9e-4; the second and third terms took
      the product of the slopes of all before them)
E-906: TXL's convolution steps are exact.
  [4] a lossy TXL driven in its RC regime stays periodic and within 2 % of the
      exact line for 3 ms (E-903: grew from 0.19 V to -0.33 V by 2.1 ms on a
      0.25 V signal)
E-907: the time in picoseconds is 64-bit.
  [5] a TXL keeps following its source past 2.147 ms (E-903: froze)
  [6] the same for a CPL line
E-908: the lines say where they hold.
  [7] a lossy TXL, a TXL that drops its resistance, a TXL model simulated as
      CPL and a lossy CPL each print a Note (E-903: none)

Exit code 0 = pass.
"""
import cmath
import math
import os
import re
import subprocess
import sys
import tempfile

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from _setup import NG as NGSPICE  # noqa: E402
from _setup import check_both_solvers as _check_both_solvers; _check_both_solvers(__file__)  # noqa: E402

WORK = tempfile.mkdtemp(prefix="txlcpl_")
checks = passed = 0


def check(label, ok, detail=""):
    global checks, passed
    checks += 1
    passed += bool(ok)
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  [{detail}]" if detail else ""))


def run(name, text, timeout=600):
    path = os.path.join(WORK, name + ".cir")
    with open(path, "w") as f:
        f.write(text)
    try:
        r = subprocess.run([NGSPICE, "-b", path], cwd=WORK, capture_output=True, text=True, timeout=timeout)
        return r.stdout + r.stderr
    except subprocess.TimeoutExpired:
        return "TIMEOUT"


def num(out, name):
    m = re.search(r"^%s\s*=\s*(-?[\d.]+e[+-]\d+)" % re.escape(name), out, re.M)
    return float(m.group(1)) if m else None


def card(kind, R, L, C, ln):
    if kind == "txl":
        return "y1 a 0 b 0 lm\n.model lm txl r=%r l=%r g=0 c=%r length=%r\n" % (R, L, C, ln)
    return "p1 a 0 b 0 lm\n.model lm cpl r=%r l=%r g=0 c=%r length=%r\n" % (R, L, C, ln)


def exact(R, L, C, ln, RS, RL, f):
    s = 2j * math.pi * f
    g = cmath.sqrt((R + s * L) * (s * C)); Zc = cmath.sqrt((R + s * L) / (s * C))
    y11, y12 = 1 / (Zc * cmath.tanh(g * ln)), -1 / (Zc * cmath.sinh(g * ln))
    A = np.array([[1 / RS + y11, y12], [y12, y11 + 1 / RL]])
    return np.linalg.solve(A, np.array([1 / RS, 0]))


print("Enhancements 904-908: the KSPICE lossy lines TXL and CPL")

# [1] [2] a constant source: the transient holds the operating point
for i, kind in ((1, "txl"), (2, "cpl")):
    out = run("hold_" + kind, "* hold\nvs s 0 dc 1\nrs s a 50\nrl b 0 50\n%s.control\nset numdgt=12\nop\nprint v(b)\n"
              "tran 0.1n 2u\nlet lo = minimum(v(b))\nlet hi = maximum(v(b))\nprint lo hi\n.endc\n.end\n"
              % card(kind, 8.5, 3.6e-7, 5e-11, 0.1))
    vop, lo, hi = num(out, "v(b)"), num(out, "lo"), num(out, "hi")
    check("[%d] a %s carrying dc current holds its operating point under a constant source" % (i, kind.upper()),
          None not in (vop, lo, hi) and abs(lo - vop) < 1e-6 and abs(hi - vop) < 1e-6,
          "operating point %s, transient %s to %s" % (vop, lo, hi))

# [3] above the RC corner: the campaign's Family G seed 104
R3, L3, C3, ln3, RS3, RL3, f3 = 0.2373222559947495, 2.4605331825137204e-07, 1.01564844190504e-11, \
    0.7391207079393048, 794.1496073126677, 3560.5976804114566, 387542.31241298834
T3 = 1 / f3
t0 = math.ceil(max(10 * T3, 60 * ln3 * math.sqrt(L3 * C3)) / T3) * T3
out = run("above", "* above the corner\nvs s 0 dc 0 sin(0 1 %r)\nrs s a %r\nrl b 0 %r\n%s"
          ".option reltol=1e-6 abstol=1e-15 vntol=1e-9\n.control\nset wr_singlescale\nset numdgt=15\n"
          "tran %r %r 0 %r\nwrdata %s v(a) v(b)\n.endc\n.end\n"
          % (f3, RS3, RL3, card("txl", R3, L3, C3, ln3), T3 / 400, t0 + 4 * T3, T3 / 400, os.path.join(WORK, "above.txt")))
err3 = None
try:
    d = np.loadtxt(os.path.join(WORK, "above.txt"), ndmin=2)
    sel = d[:, 0] >= t0
    tt = d[sel, 0]
    A = np.column_stack([np.ones_like(tt)] + [fn(2 * math.pi * k * f3 * tt) for k in (1, 2, 3) for fn in (np.cos, np.sin)])
    ref = exact(R3, L3, C3, ln3, RS3, RL3, f3)
    err3 = 0.0
    for col, rv in ((1, ref[0]), (2, ref[1])):
        x = np.linalg.lstsq(A, d[sel, col], rcond=None)[0]
        ph = complex(x[1], -x[2]) / (-1j)      # sin source: phasor -j
        err3 = max(err3, abs(ph - rv) / max(abs(rv), 1e-3))
except Exception:
    err3 = None
check("[3] a TXL driven above its RC corner: the fundamental within 1e-5 of the exact line",
      err3 is not None and err3 < 1e-5, "%.2e" % err3 if err3 is not None else "no transient")

# [4] [5] [6] long runs: same phase, one period apart and past 2.147 ms
PH = ".control\ntran 1u 3m\nmeas tran p1 find v(b) at=1.025m\nmeas tran p2 find v(b) at=1.925m\n" \
     "meas tran p4 find v(b) at=2.225m\nmeas tran p5 find v(b) at=2.925m\n.endc\n.end\n"
out = run("rc", "* lossy, in its RC regime\nvs s 0 dc 0 sin(0 1 10k)\nrs s a 50\nrl b 0 50\n%s%s"
          % (card("txl", 0.5, 3.6e-7, 5e-11, 200.0), PH))
p = [num(out, n) for n in ("p1", "p2", "p4", "p5")]
ex4 = abs(exact(0.5, 3.6e-7, 5e-11, 200.0, 50.0, 50.0, 1e4)[1])
check("[4] a lossy TXL in its RC regime stays periodic and within 2 % of the exact line for 3 ms",
      None not in p and max(p) - min(p) < 1e-3 * ex4 and abs(p[0] / ex4 - 1) < 0.02,
      "peaks %s, exact %.4f" % (", ".join("%.4f" % v for v in p) if None not in p else p, ex4))
for i, kind, r in ((5, "txl", 0.0), (6, "cpl", 0.5)):     # cpl takes no R = 0 (its setup ends ngspice)
    out = run("late_" + kind, "* past 2.147 ms\nvs s 0 dc 0 sin(0 1 10k)\nrs s a 50\nrl b 0 50\n%s%s"
              % (card(kind, r, 3.6e-7, 5e-11, 200.0), PH))
    p = [num(out, n) for n in ("p1", "p2", "p4", "p5")]
    check("[%d] a %s keeps following its source past 2.147 ms" % (i, kind.upper()),
          None not in p and max(p) - min(p) < 1e-3 * max(abs(v) for v in p),
          "peaks at 1.025, 1.925, 2.225, 2.925 ms: %s" % (", ".join("%.4f" % v for v in p) if None not in p else p))

# [7] the notes
o1 = run("n1", "* n1\nvs s 0 dc 1\nrs s a 50\nrl b 0 50\n%s.op\n.end\n" % card("txl", 8.5, 3.6e-7, 5e-11, 0.1))
o2 = run("n2", "* n2\nvs s 0 dc 1\nrs s a 50\nrl b 0 50\n%s.op\n.end\n" % card("txl", 0.1, 3.6e-7, 5e-11, 20.0))
o3 = run("n3", "* n3\nvs s 0 dc 1\nrs s a 50\nrl b 0 50\n%s.op\n.end\n" % card("txl", 848.5, 3.6e-7, 5e-11, 0.1))
o4 = run("n4", "* n4\nvs s 0 dc 1\nrs s a 50\nrl b 0 50\n%s.op\n.end\n" % card("cpl", 8.5, 3.6e-7, 5e-11, 0.1))
notes = [bool(re.search(r"Note: y1: txl's lossy-line fits hold above the line's RC corner", o1)),
         bool(re.search(r"Note: y1: R/L = \S+ is below 5e5, and txl simulates the line lossless", o2)),
         bool(re.search(r"Note: \.model lm: a txl with R/L = \S+ above 1\.6e9 is simulated as a single cpl line", o3)),
         bool(re.search(r"Note: p1: cpl does not model a lossy line below its RC corner", o4))]
check("[7] a lossy TXL, a lossless-shortcut TXL, a TXL model simulated as CPL and a lossy CPL each say so",
      all(notes), "lossy txl %s, dropped R %s, txl as cpl %s, lossy cpl %s" % tuple(notes))

print(f"\n{passed}/{checks} checks passed")
sys.exit(0 if passed == checks else 1)
