#!/usr/bin/env python3
"""verify_senscouple.py -- Enhancement-870: `sens ... ac` moves a coupled
inductor's mutual inductance with its inductance.

F4 of the Sparse and KLU correctness campaign of 2026-10-11.

A K element's mutual inductance is M = k sqrt(L1 L2), a device of its own that
the perturbation of an inductance never re-evaluated: the ac sensitivity to a
coupled L1 held M at its nominal value, where the deck names k and
`alter l1` moves M with L1. On a transformer that was 2528 - 977j against
5087 + 9448j. The couplings are now set up, recomputed and loaded with the
inductor they couple.

The reference is the exact complex MNA of the deck (numpy), differentiated by
a Richardson-extrapolated central difference.

  [1] d v(3)/d l1, the primary of the transformer, to 1e-6 of the exact value
  [2] d v(3)/d l2, the secondary, to 1e-6
  [3] sens d/dl1 agrees with a central difference of two `alter`ed ac runs
  [4] (control) d/dk1, right before, to 1e-6
  [5] (control) an uncoupled l3 and a resistor r1, right before, to 1e-6

Exit code 0 = pass.
"""
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

WORK = tempfile.mkdtemp(prefix="senscouple_")
checks = passed = 0
F = 1e5
NOM = dict(L1=10e-6, L2=40e-6, k=0.9, L3=5e-6, R1=50.0)


def check(label, ok, detail=""):
    global checks, passed
    checks += 1
    passed += bool(ok)
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  [{detail}]" if detail else ""))


def deck(p):
    return ("v1 1 0 dc 0 ac 1\nr1 1 2 %r\nl1 2 0 %r\nl2 3 0 %r\nk1 l1 l2 %r\nr2 3 0 200\n"
            "r3 3 4 100\nl3 4 0 %r" % (p["R1"], p["L1"], p["L2"], p["k"], p["L3"]))


def v3(**over):
    p = dict(NOM, **over)
    w = 2 * math.pi * F
    A = np.zeros((8, 8), complex)
    b = np.zeros(8, complex)

    def g(a, c, y):
        for r, q, s in ((a, a, 1), (c, c, 1), (a, c, -1), (c, a, -1)):
            if r >= 0 and q >= 0:
                A[r, q] += s * y

    def br(r, a, c):
        if a >= 0:
            A[a, r] += 1
            A[r, a] += 1
        if c >= 0:
            A[c, r] -= 1
            A[r, c] -= 1

    g(0, 1, 1 / p["R1"])
    g(2, -1, 1 / 200.0)
    g(2, 3, 1 / 100.0)
    br(4, 0, -1)
    b[4] = 1
    br(5, 1, -1)
    A[5, 5] -= 1j * w * p["L1"]
    br(6, 2, -1)
    A[6, 6] -= 1j * w * p["L2"]
    br(7, 3, -1)
    A[7, 7] -= 1j * w * p["L3"]
    m = p["k"] * math.sqrt(p["L1"] * p["L2"])
    A[5, 6] -= 1j * w * m
    A[6, 5] -= 1j * w * m
    return np.linalg.solve(A, b)[2]


def exact(name):
    p0 = NOM[name]
    def fd(h):
        return (v3(**{name: p0 * (1 + h)}) - v3(**{name: p0 * (1 - h)})) / (2 * h * p0)
    return (4 * fd(5e-5) - fd(1e-4)) / 3


def run(name, control, p=NOM):
    path = os.path.join(WORK, name + ".cir")
    with open(path, "w") as f:
        f.write("* %s\n%s\n.control\nset numdgt=12\n%s\n.endc\n.end\n" % (name, deck(p), control))
    r = subprocess.run([NGSPICE, "-b", path], cwd=WORK, capture_output=True, text=True, timeout=120)
    return r.stdout + r.stderr


def cvalue(out, name):
    m = re.search(r"^%s\s*=\s*(\S+),(\S+)" % re.escape(name), out, re.M)
    return complex(float(m.group(1)), float(m.group(2))) if m else None


out = run("sens", "sens v(3) ac lin 1 %r %r\nprint l1 l2 k1 l3 r1" % (F, F))
sens = {n: cvalue(out, n) for n in ("l1", "l2", "k1", "l3", "r1")}
ref = {"l1": exact("L1"), "l2": exact("L2"), "k1": exact("k"), "l3": exact("L3"), "r1": exact("R1")}


def rel(n):
    return abs(sens[n] - ref[n]) / abs(ref[n]) if sens[n] is not None else None


def line(names):
    return "; ".join("%s: %s (exact %.6g%+.6gj)" % (n, "%.1e" % rel(n) if rel(n) is not None else "no value",
                                                     ref[n].real, ref[n].imag) for n in names)


check("[1] d v(3)/d l1, the coupled primary, to 1e-6 of the exact value",
      rel("l1") is not None and rel("l1") < 1e-6, line(["l1"]))
check("[2] d v(3)/d l2, the coupled secondary, to 1e-6",
      rel("l2") is not None and rel("l2") < 1e-6, line(["l2"]))

# [3]
h = NOM["L1"] * 1e-5
outs = [run("alt%d" % s, "ac lin 1 %r %r\nprint v(3)" % (F, F), dict(NOM, L1=NOM["L1"] + s * h))
        for s in (1, -1)]
vals = [cvalue(o, "v(3)") for o in outs]
fd = (vals[0] - vals[1]) / (2 * h) if all(v is not None for v in vals) else None
r3 = abs(sens["l1"] - fd) / abs(fd) if fd is not None and sens["l1"] is not None else None
check("[3] sens d/dl1 agrees with a central difference of two altered ac runs to 1e-5",
      r3 is not None and r3 < 1e-5, "%s" % ("%.1e" % r3 if r3 is not None else "no value"))

check("[4] (control) d/dk1 to 1e-6", rel("k1") is not None and rel("k1") < 1e-6, line(["k1"]))
check("[5] (control) an uncoupled l3 and a resistor r1 to 1e-6",
      all(rel(n) is not None and rel(n) < 1e-6 for n in ("l3", "r1")), line(["l3", "r1"]))

print(f"\n{passed}/{checks} checks passed")
sys.exit(0 if passed == checks else 1)
