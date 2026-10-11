#!/usr/bin/env python3
"""verify_guardgain.py -- Enhancement-869: the E-256 false-convergence guard
allows a row the rounding of its unknowns makes.

N1 of the Sparse and KLU correctness campaign of 2026-10-11.

An inverting amplifier built from a VCVS of open-loop gain 1e12 went through
126 iterations of dynamic gmin stepping under KLU, 3 up to a gain of 1e11.
The control voltage of the VCVS is v(out)/A, rounded at the circuit's volts,
and the gain multiplies that rounding into its branch row: 2.5e-5 of residual
in 2.5 of terms, where the guard exempted a row only below one part per
million of its terms. The guard now also allows 1024 eps of (|G| s)_k, s_j
the largest unknown of j's kind.

  [1] the inverter at gains 1e12, 1e13 and 1e15: exact, in at most 5
      iterations, under each solver
  [2] the inverter's transient at a gain of 1e12: exact
  [3] a dc sweep of the gain from 1e12 to 1e15: exact at every point, in at
      most 25 iterations
  [4] (control) a gain of 1e9: 3 iterations, as before
  [5] (control) the guard still declines E-256's false point: B I=sqrt(v(n))
      on a 0.6 V / 1 ohm divider reaches v(n) = 0.17805, not 0

Exit code 0 = pass.
"""
import math
import os
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from _setup import NG as NGSPICE  # noqa: E402
from _setup import check_both_solvers as _check_both_solvers; _check_both_solvers(__file__)  # noqa: E402

WORK = tempfile.mkdtemp(prefix="guardgain_")
checks = passed = 0


def check(label, ok, detail=""):
    global checks, passed
    checks += 1
    passed += bool(ok)
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  [{detail}]" if detail else ""))


def run(name, body, control):
    deck = os.path.join(WORK, name + ".cir")
    with open(deck, "w") as f:
        f.write("* %s\n%s\n.control\nset numdgt=17\nset wr_singlescale\n%s\n.endc\n.end\n" % (name, body, control))
    r = subprocess.run([NGSPICE, "-b", deck], cwd=WORK, capture_output=True, text=True, timeout=120)
    return r.stdout + r.stderr


def scalar(out, name):
    m = re.search(r"^%s\s*=\s*(\S+)" % re.escape(name), out, re.M)
    return float(m.group(1)) if m else None


def table(path, ncol):
    rows = []
    if os.path.exists(path):
        for line in open(path):
            v = line.split()
            if len(v) >= ncol:
                try:
                    rows.append([float(t) for t in v[:ncol]])
                except ValueError:
                    pass
    return rows


VIN = 1.234567


def inverter(A, source="0.1234567"):
    return "vin in 0 %s\nr1 in neg 1k\nr2 neg out 10k\ne1 out 0 0 neg %r\nrl out 0 2k" % (source, A)


def exact(A, vin=0.1234567):
    return -10 * vin * A / (A + 11)


def op(A):
    out = run("inv%g" % A, inverter(A), "op\nprint v(out)\nrusage totiter")
    v = scalar(out, "v(out)")
    it = scalar(out, "Total iterations")
    err = abs(v - exact(A)) / abs(exact(A)) if v is not None else None
    return err, it


# [1]
res = [(A,) + op(A) for A in (1e12, 1e13, 1e15)]
check("[1] the inverter at gains 1e12, 1e13 and 1e15: exact, in at most 5 iterations",
      all(e is not None and it is not None and e < 1e-14 and it <= 5 for _, e, it in res),
      "; ".join("%g: %s, %s iterations" % (A, "%.1e" % e if e is not None else "no run", it) for A, e, it in res))

# [2]
path = os.path.join(WORK, "tr.txt")
run("tr", inverter(1e12, "dc 0.1234567 sin(0.1234567 0.05 1k)"), "tran 10u 1m\nwrdata %s v(in) v(out)" % path)
rows = table(path, 3)
w = max((abs(o - (-10 * i * 1e12 / (1e12 + 11))) / abs(10 * i) for _, i, o in rows), default=None)
check("[2] the inverter's transient at a gain of 1e12: exact to 1e-14",
      w is not None and len(rows) > 50 and w < 1e-14,
      "%s over %d points" % ("%.1e" % w if w is not None else "no run", len(rows)))

# [3]
path = os.path.join(WORK, "gain.txt")
out = run("gain", inverter(1e12), "dc @e1[gain] 1e12 1e15 2.497e14\nwrdata %s v(out)\nrusage totiter" % path)
rows = table(path, 2)
it = scalar(out, "Total iterations")
w = max((abs(v - exact(A)) / abs(exact(A)) for A, v in rows), default=None)
check("[3] a dc sweep of the gain from 1e12 to 1e15: exact to 1e-14 at every point, in at most 25 iterations",
      w is not None and len(rows) == 5 and w < 1e-14 and it is not None and it <= 25,
      "%s over %d points, %s iterations" % ("%.1e" % w if w is not None else "no run", len(rows), it))

# [4]
e, it = op(1e9)
check("[4] (control) a gain of 1e9: exact, 3 iterations as before",
      e is not None and e < 1e-14 and it == 3, "%s, %s iterations" % ("%.1e" % e if e is not None else "no run", it))

# [5]
out = run("e256", "v1 1 0 0.6\nr1 1 n 1\nb1 n 0 i=sqrt(v(n))", "op\nprint v(n)")
v = scalar(out, "v(n)")
root = ((-1 + math.sqrt(1 + 4 * 0.6)) / 2) ** 2
check("[5] (control) E-256's false point is still declined: v(n) = 0.17805 to 1e-3, not 0",
      v is not None and abs(v - root) / root < 1e-3, "v(n) = %s, root %.6f" % (v, root))

print(f"\n{passed}/{checks} checks passed")
sys.exit(0 if passed == checks else 1)
