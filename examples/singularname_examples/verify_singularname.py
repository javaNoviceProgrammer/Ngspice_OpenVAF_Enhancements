#!/usr/bin/env python3
"""
verify_singularname.py -- Enhancement-570: "singular matrix: check node" names the
node whose equation is vacuous, the same one under KLU and Sparse.

The index a factorization stops at is the column where ITS elimination order
first ran out of pivots; for a rank-deficient block that is any of the block's
columns, so the two solvers could blame different nodes for the same defect.
A BSIM4 whose gate hangs on a Verilog-A capacitor was "check node g" under
Sparse and "check node d" under KLU -- only the first told the user anything.

SMPgetError now looks at the loaded matrix first: a row that is all zero is a
node nothing conducts to in this analysis, and that node is named whatever the
pivot order (an all-zero column, an unknown no equation mentions, is the same
thing from the other side). Only when no such line exists does the pivot the
factorization stopped at stand. Both solvers, DC and AC alike.

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


def blamed(out):
    """The set of node names in 'singular matrix:  check node X' reports."""
    return set(re.findall(r"singular matrix:\s+check nodes? (\S+)", out))


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


def op_deck(title, body, prints, pre=""):
    return f"* {title}\n{body}\n.control\n{pre}op\nprint {prints}\n.endc\n.end\n"


MOS1 = ".model nm nmos(level=1 vto=0.7 kp=100u)\n.model pm pmos(level=1 vto=-0.7 kp=40u)"
BSIM4 = os.path.join(os.path.dirname(HERE), "benchmark_examples", "bsim4va.osdi")


def build(va):
    osdi = os.path.join(HERE, va.replace(".va", ".osdi"))
    r = subprocess.run([OPENVAF, va, "-o", osdi], cwd=HERE, capture_output=True, text=True, timeout=300)
    return os.path.isfile(osdi), r.stdout + r.stderr


def main():
    print("Enhancement-570: the singular-matrix report names the node whose equation is vacuous")

    print("\n[a zero row names its node, whatever the pivot order]")
    ok, log = build("va_cap.va")
    check("va_cap.va compiles", ok, log[-200:] if not ok else "")
    if ok and os.path.isfile(BSIM4):
        out = ngspice(op_deck("bsim4 gate on a capacitor", "vdd vdd 0 1.2\nvin in 0 0.6\nncap in g cm\nrd vdd d 10k\n"
                              "nm1 d g 0 0 nmv w=1u l=0.2u\n.model cm va_cap()\n.model nmv bsim4va(type=1 w=1e-6 l=0.2e-6)",
                              "v(d) v(g)", f"pre_osdi va_cap.osdi\npre_osdi {BSIM4}\n"))
        b = blamed(out)
        check("BSIM4 gate through a Verilog-A capacitor: every report says 'check node g' (KLU said d)",
              b == {"g"}, f"blamed={sorted(b)}")
        s = scalars(out)
        check("...and the point is the same as before: v(g)=0.5987, v(d)=0.4371",
              abs(s.get("v(g)", 9) - 0.5986935) < 1e-4 and abs(s.get("v(d)", 9) - 0.4370724) < 1e-4,
              f"v(g)={s.get('v(g)')} v(d)={s.get('v(d)')}")
        out = ngspice(op_deck("bsim4 open gate", "vdd vdd 0 1.2\nrd vdd d 10k\nnm1 d g 0 0 nmv w=1u l=0.2u\n"
                              ".model nmv bsim4va(type=1 w=1e-6 l=0.2e-6)", "v(d) v(g)", f"pre_osdi {BSIM4}\n"))
        check("BSIM4 with an open gate: 'check node g'", blamed(out) == {"g"}, f"blamed={sorted(blamed(out))}")
    out = ngspice(op_deck("mos1 open gate", "vdd vdd 0 3\nrd vdd d 10k\nm1 d g 0 0 nm w=10u l=1u\n" + MOS1, "v(d) v(g)"))
    check("built-in MOS1 with an open gate: 'check node g'", blamed(out) == {"g"}, f"blamed={sorted(blamed(out))}")
    out = ngspice(op_deck("inverter chain", "vdd vdd 0 3\nmp1 o1 in vdd vdd pm w=2u l=1u\nmn1 o1 in 0 0 nm w=1u l=1u\n"
                          "mp2 o2 o1 vdd vdd pm w=2u l=1u\nmn2 o2 o1 0 0 nm w=1u l=1u\n" + MOS1, "v(o1) v(o2) v(in)"))
    check("CMOS inverter chain with its input open: only 'check node in' (KLU also said o2)",
          blamed(out) == {"in"}, f"blamed={sorted(blamed(out))}")
    out = ngspice(op_deck("capacitor only", "v1 a 0 1\nr1 a b 1k\nc1 x 0 1p", "v(b) v(x)"))
    check("a capacitor alone on a node: 'check node x'", blamed(out) == {"x"}, f"blamed={sorted(blamed(out))}")
    ok, log = build("va_vcvs.va")
    check("va_vcvs.va compiles", ok, log[-200:] if not ok else "")
    if ok:
        out = ngspice(op_deck("osdi probed port", "v1 a 0 1\nr1 a b 1k\nnx1 x c vc\nrc c 0 1k\n.model vc va_vcvs()",
                              "v(b) v(c) v(x)", "pre_osdi va_vcvs.osdi\n"))
        check("a Verilog-A module's probed port on an untouched node (E-569's zero diagonal): 'check node x'",
              blamed(out) == {"x"} and "could not be simulated" not in out, f"blamed={sorted(blamed(out))}")

    print("\n[no zero line: the pivot the factorization stopped at still stands]")
    out = ngspice(op_deck("parallel sources", "v1 a 0 1\nv2 a 0 1\nr1 a 0 1k", "v(a)"))
    b = blamed(out)
    check("two ideal voltage sources in parallel: a source branch is named, the point is refused",
          b and b <= {"v1#branch", "v2#branch"} and "could not be simulated" in out, f"blamed={sorted(b)}")
    out = ngspice(op_deck("inductor loop", "v1 in 0 1\nr1 in a 1k\nl1 a b 1u\nl2 a b 1u\nr2 b 0 1k", "v(b)"))
    b = blamed(out)
    check("two ideal inductors in parallel: an inductor branch is named, optran splits the current",
          b and b <= {"l1#branch", "l2#branch"} and abs(scalars(out).get("v(b)", 9) - 0.5) < 1e-3, f"blamed={sorted(b)}")

    print("\n[AC goes through the same report]")
    out = ngspice("* ac on a capacitor node\nv1 a 0 dc 1 ac 1\nr1 a b 1k\nc1 x 0 1p\n.control\nac dec 1 1 10\nprint v(x)\n.endc\n.end\n")
    check("AC on the capacitor-only deck: the operating point's reports name x, the AC itself runs",
          blamed(out) == {"x"} and "matrix is singular" not in out, f"blamed={sorted(blamed(out))}")

    for f in ("_o.cir", "va_cap.osdi", "va_vcvs.osdi"):
        try:
            os.remove(os.path.join(HERE, f))
        except OSError:
            pass
    print(f"\n{'ALL PASS' if passed == checks else 'FAILURES'}: {passed}/{checks} passed")
    sys.exit(0 if passed == checks else 1)


if __name__ == "__main__":
    main()
