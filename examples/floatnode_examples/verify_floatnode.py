#!/usr/bin/env python3
"""
verify_floatnode.py -- Enhancement-569: a node that a device only READS is held
and named like any other floating node, on BOTH solvers.

Enhancement-566 gives every node that owns no matrix entry a zero diagonal, so
gmin can hold it, and names it ("connected to nothing that conducts; it is held
only by gmin"). It decided "owns no entry" by looking at the node's matrix
COLUMN. That is right for a node nothing conducts to -- a current source's
only load, a controlled-current-source output -- whose equation contains no
unknown. It is wrong for a node that a device only reads: a B-source
`v=2*v(x)` or an XSPICE input port puts its derivative in the reader's row,
column x, so x had a column entry and an EMPTY row -- no equation at all, which
no gmin can rescue. The operating point failed on both solvers after 374
iterations, Sparse blaming node x and KLU the reader's branch.

Now a node is floating when its row OR its column is empty. Both cases are
pinned here, next to the ordinary shapes that must NOT be called floating.

Every SPICE deck starts with a title line (SPICE treats line 1 as the title!).
"""
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))          # the examples/ dir (holds _setup.py)
from _setup import NG as NGSPICE, VAF as OPENVAF
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


def iters(out):
    m = re.search(r"Total iterations\s*=\s*(\d+)", out)
    return int(m.group(1)) if m else None


def near(a, b, tol):
    return a is not None and abs(a - b) <= tol


def op_deck(title, body, prints, options=""):
    return f"* {title}\n{options}{body}\n.control\nop\nprint {prints}\nrusage totiter\n.endc\n.end\n"


HELD = "connected to nothing that conducts; it is held only by gmin"
FAILED = "could not be simulated"
OSDI = os.path.join(HERE, "va_vcvs.osdi")
BSIM4 = os.path.join(os.path.dirname(HERE), "benchmark_examples", "bsim4va.osdi")


def build_osdi():
    r = subprocess.run([OPENVAF, "va_vcvs.va", "-o", OSDI], cwd=HERE, capture_output=True, text=True, timeout=300)
    return os.path.isfile(OSDI), r.stdout + r.stderr


def main():
    print("Enhancement-569: a node a device only reads is held and named (row OR column empty)")

    print("\n[read-only nodes] -- these failed on both solvers before")
    out = ngspice(op_deck("bsrc reads x", "v1 a 0 1\nr1 a b 1k\nb1 c 0 v=2*v(x)\nrc c 0 1k", "v(b) v(c) v(x)"))
    s = scalars(out)
    check("B-source `v=2*v(x)`, nothing else on x: the point is found",
          FAILED not in out and near(s.get("v(b)"), 1.0, 1e-9) and near(s.get("v(c)"), 0.0, 1e-9) and near(s.get("v(x)"), 0.0, 1e-9),
          f"v(b)={s.get('v(b)')} v(c)={s.get('v(c)')} v(x)={s.get('v(x)')}")
    check("...and x is named as held only by gmin", "node 'x' is " + HELD in out)
    out = ngspice(op_deck("xspice input x", "vdd vdd 0 3\na1 %v(x) %v(y) gainm\n.model gainm gain(gain=2)\nrl y 0 1k", "v(y) v(x)"))
    s = scalars(out)
    check("XSPICE `gain` whose input port x touches nothing: the point is found",
          FAILED not in out and near(s.get("v(y)"), 0.0, 1e-9) and near(s.get("v(x)"), 0.0, 1e-9),
          f"v(y)={s.get('v(y)')} v(x)={s.get('v(x)')}")
    check("...and x is named as held only by gmin", "node 'x' is " + HELD in out)

    print("\n[empty-column nodes] -- Enhancement-566's cases, still caught")
    out = ngspice(op_deck("isrc only", "v1 a 0 1\nr1 a b 1k\ni1 0 x 1m", "v(b) v(x)"))
    s = scalars(out)
    check("a current source's only load: v(b)=1, v(x)=I/gmin=1e9, x named",
          near(s.get("v(b)"), 1.0, 1e-9) and near(s.get("v(x)"), 1e9, 1e3) and "node 'x' is " + HELD in out,
          f"v(b)={s.get('v(b)')} v(x)={s.get('v(x)')}")
    out = ngspice(op_deck("cccs output", "v1 a 0 1\nr1 a b 1k\nr2 b 0 1k\nf1 0 nx v1 1", "v(b) v(nx)"))
    s = scalars(out)
    check("a CCCS output: v(b)=0.5, v(nx)=i(v1)/gmin, nx named",
          near(s.get("v(b)"), 0.5, 1e-9) and near(s.get("v(nx)"), -5e8, 1e3) and "node 'nx' is " + HELD in out,
          f"v(b)={s.get('v(b)')} v(nx)={s.get('v(nx)')}")

    print("\n[not floating] -- ordinary shapes with a row and a column")
    out = ngspice(op_deck("read and driven", "v1 a 0 1\nr1 a x 1k\nb1 c 0 v=2*v(x)\nrc c 0 1k", "v(x) v(c)"))
    s = scalars(out)
    check("x read by a B-source AND reached through a resistor: v(x)=1, v(c)=2, no warning",
          near(s.get("v(x)"), 1.0, 1e-9) and near(s.get("v(c)"), 2.0, 1e-9) and HELD not in out and iters(out) is not None and iters(out) <= 5,
          f"v(x)={s.get('v(x)')} v(c)={s.get('v(c)')} iterations={iters(out)}")
    out = ngspice(op_deck("source only", "v1 a 0 1\nr1 a b 1k\nv2 q 0 2", "v(b) v(q)"))
    s = scalars(out)
    check("a node held only by a voltage source branch: v(q)=2, no warning",
          near(s.get("v(q)"), 2.0, 1e-9) and HELD not in out, f"v(q)={s.get('v(q)')}")
    out = ngspice(op_deck("inductor node", "v1 a 0 1\nl1 a m 1u\nl2 m b 1u\nr1 b 0 1k", "v(m) v(b)"))
    s = scalars(out)
    check("a node between two inductors: v(m)=1, no warning",
          near(s.get("v(m)"), 1.0, 1e-9) and HELD not in out, f"v(m)={s.get('v(m)')}")

    print("\n[the other floating shapes] -- solved through the ladder, unchanged")
    out = ngspice(op_deck("open gate", "vdd vdd 0 3\nrd vdd d 10k\nm1 d g 0 0 nm w=10u l=1u\n.model nm nmos(level=1 vto=0.7 kp=100u)", "v(d) v(g)"))
    s = scalars(out)
    check("an open MOSFET gate: v(g)=0, v(d)=3 through optran, within 400 iterations",
          near(s.get("v(g)"), 0.0, 1e-9) and near(s.get("v(d)"), 3.0, 1e-6) and "Transient op finished" in out and iters(out) is not None and iters(out) <= 400,
          f"v(g)={s.get('v(g)')} iterations={iters(out)}")
    out = ngspice(op_deck("E control open", "vcc p 0 1\nrin p inn 1k\neamp out 0 inp inn 1e5\nrl out 0 1k", "v(out)"))
    check("an E-source controlling node that touches nothing is still refused (Enhancement-492)",
          "controlling node 'inp' does not exist" in out and "v(out)" not in scalars(out), "")

    print("\n[OSDI] -- a compiled Verilog-A module has the same two shapes")
    ok, log = build_osdi()
    check("va_vcvs.va (V(out) <+ gain*V(in): the in port is only probed) compiles", ok, log[-200:] if not ok else "")
    if ok:
        out = ngspice(op_deck("osdi reads x", "v1 a 0 1\nr1 a b 1k\nnx1 x c vc\nrc c 0 1k\n.model vc va_vcvs()", "v(b) v(c) v(x)",
                              "").replace(".control\n", ".control\npre_osdi va_vcvs.osdi\n"))
        s = scalars(out)
        check("OSDI module whose probed port x touches nothing: the point is found, x named",
              FAILED not in out and near(s.get("v(c)"), 0.0, 1e-9) and near(s.get("v(x)"), 0.0, 1e-9) and "node 'x' is " + HELD in out,
              f"v(c)={s.get('v(c)')} v(x)={s.get('v(x)')}")
        out = ngspice(op_deck("osdi driven", "v1 a 0 1\nr1 a b 1k\nnx1 a c vc\nrc c 0 1k\n.model vc va_vcvs()", "v(b) v(c)",
                              "").replace(".control\n", ".control\npre_osdi va_vcvs.osdi\n"))
        s = scalars(out)
        check("the same module with its port driven: v(c)=2 in 3 iterations, no warning",
              near(s.get("v(c)"), 2.0, 1e-9) and HELD not in out and iters(out) is not None and iters(out) <= 4,
              f"v(c)={s.get('v(c)')} iterations={iters(out)}")
    if os.path.isfile(BSIM4):
        out = ngspice(op_deck("bsim4 open gate", "vdd vdd 0 1.2\nrd vdd d 10k\nnm1 d g 0 0 nmv w=1u l=0.2u\n.model nmv bsim4va(type=1 w=1e-6 l=0.2e-6)",
                              "v(d) v(g)", "").replace(".control\n", f".control\npre_osdi {BSIM4}\n"))
        s = scalars(out)
        check("BSIM4 (OSDI) with an open gate: solved through optran, v(g)=0.4317, v(d)=1.0083, within 400 iterations",
              near(s.get("v(g)"), 0.4317335, 1e-4) and near(s.get("v(d)"), 1.00831, 1e-4) and "Transient op finished" in out
              and iters(out) is not None and iters(out) <= 400, f"v(g)={s.get('v(g)')} v(d)={s.get('v(d)')} iterations={iters(out)}")

    print("\n[.option rshunt] -- the global workaround, for comparison")
    out = ngspice(op_deck("bsrc reads x, rshunt", "v1 a 0 1\nr1 a b 1k\nb1 c 0 v=2*v(x)\nrc c 0 1k", "v(b) v(c) v(x)", ".option rshunt=1e12\n"))
    s = scalars(out)
    check("the read-only deck with rshunt=1e12: 3 iterations, v(c)=0, no floating-node warning",
          near(s.get("v(c)"), 0.0, 1e-9) and iters(out) is not None and iters(out) <= 4 and HELD not in out,
          f"v(c)={s.get('v(c)')} iterations={iters(out)}")

    for f in ("_o.cir", os.path.basename(OSDI)):
        try:
            os.remove(os.path.join(HERE, f))
        except OSError:
            pass
    print(f"\n{'ALL PASS' if passed == checks else 'FAILURES'}: {passed}/{checks} passed")
    sys.exit(0 if passed == checks else 1)


if __name__ == "__main__":
    main()
