#!/usr/bin/env python3
"""
verify_hierub.py -- Enhancement-757: a child instance's UNNAMED branch is the
child's own (LRM 5.5: the unnamed branch (a, b) is a per-module object).

The flattening used to spell the child's (p, n) with the parent's net names, so
it BECAME the parent's branch (2026-09-08 hierarchy hunt F1). The fourteen
models here are the hunt's decks plus the reverse-order, multiplied, ground-
branch and cross-instance-probe cases; every answer below is the LRM's.
"""
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from _setup import VAF as OPENVAF, NG as NGSPICE  # noqa: E402
from _setup import check_both_solvers as _cbs; _cbs(__file__)  # noqa: E702  # both KLU and Sparse

checks = passed = 0


def check(label, ok, detail=""):
    global checks, passed
    checks += 1
    passed += bool(ok)
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  [{detail}]" if detail and not ok else ""))
    return ok


def compile_va(stem):
    r = subprocess.run([OPENVAF, stem + ".va", "-o", f"_hu_{stem}.osdi"], capture_output=True,
                       text=True, cwd=HERE, timeout=300)
    return r.returncode == 0, (r.stderr or "") + (r.stdout or "")


def run(stem, deck, ctl):
    path = os.path.join(HERE, f"_hu_{stem}.cir")
    with open(path, "w") as f:
        f.write(f"* hierub {stem}\n{deck}\n.control\npre_osdi _hu_{stem}.osdi\noption noacct\n"
                f"set numdgt=10\n{ctl}\n.endc\n.end\n")
    r = subprocess.run([NGSPICE, "-b", os.path.basename(path)], capture_output=True, text=True,
                       cwd=HERE, timeout=180, errors="replace")
    return (r.stdout or "") + (r.stderr or "")


def val(out, name):
    m = re.findall(r"(?m)^\s*" + re.escape(name) + r"\s*=\s*(-?[\d.]+(?:[eE][-+]?\d+)?)", out)
    return float(m[-1]) if m else None


def near(a, b, tol=1e-6):
    return a is not None and abs(a - b) <= tol * max(1.0, abs(b))


LOAD = "vs s 0 2\nrs s 1 1k\nn1 1 0 m\n.model m {}\n"      # 2 V through 1k into the device
DIRECT = "v1 1 0 1\nn1 1 0 m\n.model m {}\n"               # 1 V across the device

print("hierub: a child's unnamed branch is its own")

ok, log = compile_va("hb3")
check("[1] hb3 (child V(p,n) <+ 1.0 under a parent I(p,n) <+ V/2k) compiles without L022",
      ok and "L022" not in log, log[-160:].replace("\n", " "))
out = run("hb3", LOAD.format("hb3"), "op\nprint v(1)")
check("[1] ...and the child's source holds: v(1) = 1.0 (was 1.333, the source dropped)",
      near(val(out, "v(1)"), 1.0), str(val(out, "v(1)")))

ok, log = compile_va("hb")
out = run("hb", DIRECT.format("hb"), "op\nprint @n1[iop] i(v1)")
check("[2] hb: the parent's own I(p,n) probe reads its own 1 mA, not the 3 mA with the child's",
      ok and near(val(out, "@n1[iop]"), 1e-3) and near(val(out, "i(v1)"), -3e-3),
      f"iop={val(out, '@n1[iop]')} i={val(out, 'i(v1)')}")

ok, log = compile_va("hb7")
out = run("hb7", LOAD.format("hb7"), "op\nprint v(1) @n1[iop]")
check("[3] hb7: a probe-only parent branch shorts again (v(1) = 0, L023 names the child's branch)",
      ok and "probe-only" in log and near(val(out, "v(1)"), 0.0, 1e-9),
      f"v={val(out, 'v(1)')} {log[-120:]}".replace("\n", " "))

ok, log = compile_va("hb11")
out = run("hb11", "vs s 0 2\nrs s 1 1k\nn1 1 0 m11\nrs2 s 2 1k\nn2 2 0 m12\n.model m11 hb11\n.model m12 hb12\n",
          "op\nprint v(1) v(2)")
check("[4] two sibling leaves, an ideal source beside a resistor: 1.0 V in either order (was 0.667 / 1.0)",
      ok and near(val(out, "v(1)"), 1.0) and near(val(out, "v(2)"), 1.0),
      f"{val(out, 'v(1)')} {val(out, 'v(2)')}")

ok, log = compile_va("sib")
out = run("sib", "vs s 0 2 ac 1\nrs s 1 1k\nn1 1 0 ma\nrs2 s 2 1k\nn2 2 0 mb\n.model ma sib\n.model mb sib2\n",
          "op\nprint v(1) v(2)\nac lin 1 1meg 1meg\nprint vm(1) vm(2)")
check("[5] a source beside a capacitor: 1.0 V at the operating point and 0 at 1 MHz, both orders "
      "(was 2.0 V and 0.157)",
      ok and near(val(out, "v(1)"), 1.0) and near(val(out, "v(2)"), 1.0)
      and near(val(out, "vm(1)"), 0.0, 1e-9) and near(val(out, "vm(2)"), 0.0, 1e-9),
      f"{val(out, 'v(1)')} {val(out, 'v(2)')} {val(out, 'vm(1)')} {val(out, 'vm(2)')}")

ok, log = compile_va("hb8")
out = run("hb8", LOAD.format("hb8"), "op\nprint v(1)")
check("[6] hb8: a conditional parent flow under the child's source: 1.0 V (was 1.333, and silent)",
      ok and near(val(out, "v(1)"), 1.0), str(val(out, "v(1)")))

ok, log = compile_va("hb10")
out = run("hb10", LOAD.format("hb10"), "op\nprint v(1)")
check("[7] hb10: two ideal sources in parallel (child 1 V, parent 2 V) are reported singular, not summed to 3 V",
      ok and "singular" in out.lower() and not near(val(out, "v(1)"), 3.0),
      f"v={val(out, 'v(1)')} singular={'singular' in out.lower()}")

ok, log = compile_va("hb9")
out = run("hb9", LOAD.format("hb9"), "op\nprint v(1)")
check("[8] hb9: the child on the parent's internal node (p, m): v(1) = 1.5",
      ok and near(val(out, "v(1)"), 1.5), str(val(out, "v(1)")))

ok, log = compile_va("hb5")
out = run("hb5", LOAD.format("hb5"), "op\nprint v(1)")
check("[9] control: a NAMED branch in the child was always its own: 1.0 V",
      ok and near(val(out, "v(1)"), 1.0), str(val(out, "v(1)")))

ok, log = compile_va("swh")
out = run("swh", "vs s 0 2\nrs s 1 1k\nn1 1 0 mon\nrs2 s 2 1k\nn2 2 0 moff\n.model mon swh on=1\n.model moff swh on=0\n",
          "op\nprint v(1) v(2)")
check("[10] a switch-branch child under a parent leakage: 0 V closed, 1.998 V open (unchanged)",
      ok and near(val(out, "v(1)"), 0.0, 1e-9) and near(val(out, "v(2)"), 1.998002, 1e-5),
      f"{val(out, 'v(1)')} {val(out, 'v(2)')}")

ok, log = compile_va("rev")
out = run("rev", DIRECT.format("rev"), "op\nprint @n1[irev] i(v1)")
check("[11] reverse-order accesses: a child's I(n,p) probe of its I(p,n) branch reads -1 mA, and "
      "I(n,p) <+ / V(n,p) <+ contributions are the same branch negated (1.5 mA total)",
      ok and near(val(out, "@n1[irev]"), -1e-3) and near(val(out, "i(v1)"), -1.5e-3),
      f"irev={val(out, '@n1[irev]')} i={val(out, 'i(v1)')}")

ok, log = compile_va("mf")
out = run("mf", DIRECT.format("mf"), "op\nprint @n1[ic] i(v1)")
check("[12] a #(.$mfactor(2)) child with a reverse-order contribution: 2 mA from the copies plus the "
      "parent's 1 mA, and its per-copy probe reads -1 mA (was -1.5 mA)",
      ok and near(val(out, "@n1[ic]"), -1e-3) and near(val(out, "i(v1)"), -3e-3),
      f"ic={val(out, '@n1[ic]')} i={val(out, 'i(v1)')}")

ok, log = compile_va("gnd")
out = run("gnd", "vs s 0 2\nrs s 1 1k\nn1 1 m\n.model m gnd\n", "op\nprint v(1)")
check("[13] the ground branch (p): a child's V(p) <+ 1.0 under a parent I(p) <+ V(p)/1k: 1.0 V",
      ok and near(val(out, "v(1)"), 1.0), str(val(out, "v(1)")))

ok, log = compile_va("e86")
out = run("e86", "v1 1 0 1\nn1 1 0 o m\n.model m e86\n", "op\nprint v(o)")
check("[14] I(<chain>.branch(p, m)) from outside reads the child's own unnamed branch, a port net "
      "included (was a compile error): 0.5 mA -> 0.5 V",
      ok and near(val(out, "v(o)"), 0.5), f"ok={ok} v={val(out, 'v(o)')} {log[-100:]}".replace("\n", " "))

ok, log = compile_va("gb")
out = run("gb", "v1 1 0 1\nn1 1 m2\nv3 3 0 1\nn3 3 m3\n.model m2 g2\n.model m3 g3\n", "op\nprint i(v1) i(v3)")
check("[15] a NAMED branch `(a, gnd)` over a `ground` net is the branch to ground, as the unnamed access "
      "always was: 1 mA each (the net used to float, singular)",
      ok and near(val(out, "i(v1)"), -1e-3) and near(val(out, "i(v3)"), -1e-3) and "nothing" not in out,
      f"i={val(out, 'i(v1)')} {val(out, 'i(v3)')}")

for f in os.listdir(HERE):
    if f.startswith("_hu_"):
        try:
            os.remove(os.path.join(HERE, f))
        except OSError:
            pass

print(f"\n{'ALL PASS' if passed == checks else 'FAILURES'}: {passed}/{checks} passed")
sys.exit(0 if passed == checks else 1)
