#!/usr/bin/env python3
"""
verify_acgminhold.py -- Enhancement-571: a node the operating point holds only
by gmin is held in the small-signal matrix too, on BOTH solvers.

The DC point of such a node -- one nothing conducts to (Enhancements 566 and
569), or an open MOSFET gate with no capacitance -- is the solution with gmin
on every diagonal: the ladder leaves CKTdiagGmin at gmin and optran solves
with it. The AC load added nothing to any diagonal, so the same node's AC row
(or, for a current-source output, its column) came out all zero and every
AC-family analysis on the deck ended in "matrix is singular" under both
solvers, right after an operating point that had succeeded.

CKTacLoad now holds exactly the nodes whose AC row or column is all zero,
with the conductance the DC hold used (gshunt when set, else gmin), and
nothing else: a node with any admittance at all is untouched.

Every SPICE deck starts with a title line (SPICE treats line 1 as the title!).
"""
import math
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))          # the examples/ dir (holds _setup.py)
from _setup import NG as NGSPICE
from _setup import check_both_solvers as _check_both_solvers; _check_both_solvers(__file__)  # verify under BOTH KLU and Sparse solvers

checks = 0
passed = 0


def check(label, ok, detail=""):
    global checks, passed
    checks += 1
    passed += bool(ok)
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  [{detail}]" if detail else ""))


def ngspice(deck, name="_o.cir"):
    path = os.path.join(HERE, name)
    with open(path, "w") as fh:
        fh.write(deck)
    r = subprocess.run([NGSPICE, "-b", name], cwd=HERE, capture_output=True, text=True, timeout=300)
    return r.stdout + r.stderr


def scalars(out):
    vals = {}
    for line in out.splitlines():
        m = re.match(r"\s*([\w\(\)\[\]#@.,-]+)\s*=\s*([-+0-9.eE]+)", line)
        if m:
            try:
                vals[m.group(1).lower()] = float(m.group(2))
            except ValueError:
                pass
    return vals


def near(a, b, rel):
    return a is not None and abs(a - b) <= rel * abs(b) + 1e-30


def deck(title, body, control, options=""):
    return f"* {title}\n{options}{body}\n.control\n{control}\n.endc\n.end\n"


AC1K = "ac lin 1 1k 1k"
SING = "matrix is singular"
MOS1 = ".model nm nmos(level=1 vto=0.7 kp=100u)"


def main():
    print("Enhancement-571: a gmin-held node is held in AC, noise and sp too")

    print("\n[the AC-family analyses run where they were refused]")
    out = ngspice(deck("isrc ac-driven", "v1 a 0 dc 1 ac 1\nr1 a b 1k\ni1 0 x dc 1m ac 1", AC1K + "\nprint vm(b) vm(x)"))
    s = scalars(out)
    check("a current source's only load, AC-driven: vm(x) = 1/gmin = 1e12 (the DC hold's I/gmin, in AC), vm(b) = 1",
          SING not in out and near(s.get("vm(x)"), 1e12, 1e-6) and near(s.get("vm(b)"), 1.0, 1e-9),
          f"vm(x)={s.get('vm(x)')} vm(b)={s.get('vm(b)')}")
    out = ngspice(deck("bsrc read-only", "v1 a 0 dc 1 ac 1\nr1 a b 1k\nb1 c 0 v=2*v(x)\nrc c 0 1k", AC1K + "\nprint vm(b) vm(c)"))
    s = scalars(out)
    check("a node only a B-source reads: the AC runs, v(c) = 2*v(x) = 0",
          SING not in out and near(s.get("vm(b)"), 1.0, 1e-9) and s.get("vm(c)") is not None and abs(s["vm(c)"]) < 1e-15,
          f"vm(b)={s.get('vm(b)')} vm(c)={s.get('vm(c)')}")
    out = ngspice(deck("cccs output", "v1 a 0 dc 1 ac 1\nr1 a b 1k\nr2 b 0 1k\nf1 0 nx v1 1", AC1K + "\nprint vm(b) vm(nx)"))
    s = scalars(out)
    check("a CCCS output (all-zero column, not row): the AC runs, vm(b) = 0.5, vm(nx) = |i(v1)|/gmin = 5e8",
          SING not in out and near(s.get("vm(b)"), 0.5, 1e-9) and near(s.get("vm(nx)"), 5e8, 1e-6),
          f"vm(b)={s.get('vm(b)')} vm(nx)={s.get('vm(nx)')}")
    out = ngspice(deck("mos1 open gate", "vdd vdd 0 3\nvin in 0 dc 1 ac 1\nrin in q 1k\nrd vdd d 10k\nm1 d g 0 0 nm w=10u l=1u\n" + MOS1,
                       AC1K + "\nprint vm(q) vm(g)"))
    s = scalars(out)
    check("a MOS1 with an open gate and no capacitances: the AC runs, vm(q) = 1, vm(g) = 0",
          SING not in out and near(s.get("vm(q)"), 1.0, 1e-9) and s.get("vm(g)") is not None and abs(s["vm(g)"]) < 1e-15,
          f"vm(q)={s.get('vm(q)')} vm(g)={s.get('vm(g)')}")
    out = ngspice(deck("xspice input", "v1 a 0 dc 1 ac 1\nr1 a b 1k\na1 %v(x) %v(y) gainm\n.model gainm gain(gain=2)\nrl y 0 1k",
                       AC1K + "\nprint vm(b) vm(y)"))
    s = scalars(out)
    check("an XSPICE input port on an untouched node: the AC runs, vm(y) = 0",
          SING not in out and near(s.get("vm(b)"), 1.0, 1e-9) and s.get("vm(y)") is not None and abs(s["vm(y)"]) < 1e-15,
          f"vm(b)={s.get('vm(b)')} vm(y)={s.get('vm(y)')}")
    out = ngspice(deck("noise", "v1 a 0 dc 1 ac 1\nr1 a b 1k\nb1 c 0 v=2*v(x)\nrc c 0 1k",
                       "noise v(b) v1 lin 1 1k 1k\nprint onoise_spectrum"))
    s = scalars(out)
    check("noise on the read-only deck: runs, output noise density of the 1k resistor = sqrt(4kTR) = 4.07 nV/rtHz",
          SING not in out and near(s.get("onoise_spectrum"), math.sqrt(4 * 1.380649e-23 * 300.15 * 1e3), 5e-3),
          f"onoise_spectrum={s.get('onoise_spectrum')}")
    out = ngspice(deck("sp", "v1 a 0 dc 1 ac 1 portnum 1 z0 50\nr1 a b 1k\nb1 c 0 v=2*v(x)\nrc c 0 1k", "sp lin 1 1k 1k\nprint S_1_1"))
    check("sp on the read-only deck: runs and prints S_1_1", SING not in out and re.search(r"s_1_1\s*=", out, re.I) is not None and "Error" not in out, "")

    print("\n[the hold is the DC hold]")
    out = ngspice(deck("gshunt", "v1 a 0 dc 1 ac 1\nr1 a b 1k\ni1 0 x dc 1m ac 1", AC1K + "\nprint vm(x)", ".option gshunt=1e-9\n"))
    s = scalars(out)
    check("with .option gshunt=1e-9 the AC hold follows it: vm(x) = 1e9", near(s.get("vm(x)"), 1e9, 1e-6), f"vm(x)={s.get('vm(x)')}")

    print("\n[nothing else changes]")
    out = ngspice(deck("rc lowpass", "v1 in 0 dc 0 ac 1\nr1 in out 1k\nc1 out 0 159.155n", AC1K + "\nprint vm(out) vp(out)"))
    s = scalars(out)
    check("an RC low-pass at its corner: vm = 0.70711, vp = -pi/4, as ever",
          near(s.get("vm(out)"), 1 / math.sqrt(2), 1e-5) and near(s.get("vp(out)"), -math.pi / 4, 1e-4), f"vm={s.get('vm(out)')} vp={s.get('vp(out)')}")
    out = ngspice(deck("cap node", "v1 a 0 dc 1 ac 1\nr1 a b 1k\ni1 0 x dc 0 ac 1\nc1 x 0 1p", AC1K + "\nprint vm(x)"))
    s = scalars(out)
    check("a node with only a capacitor (an admittance, so not held): vm(x) = 1/(2*pi*f*C) = 1.5915e8, no gmin in it",
          near(s.get("vm(x)"), 1 / (2 * math.pi * 1e3 * 1e-12), 1e-6), f"vm(x)={s.get('vm(x)')}")

    try:
        os.remove(os.path.join(HERE, "_o.cir"))
    except OSError:
        pass
    print(f"\n{'ALL PASS' if passed == checks else 'FAILURES'}: {passed}/{checks} passed")
    sys.exit(0 if passed == checks else 1)


if __name__ == "__main__":
    main()
