#!/usr/bin/env python3
"""
verify_paramarray.py -- verifies Enhancement-102 (name-then-range array-valued
parameters), through the committed
openvaf-r + ngspice.

`parameter real c[0:2] = '{...}` (dimensions after the name) now compiles,
complementing the type-then-range form `parameter real [0:2] c`. Local vars,
nets, and ports already accepted the name-then-range spelling (E-18/89/91);
this closes the gap for parameters. Elements are exposed as OSDI parameters
`c[0]`, `c[1]`, ... so per-element `.model` overrides work unchanged.

  [1] paramarray_demo.va compiles (name-then-range parameter arrays)
  [2] element defaults resolve: c/a/b/g/m/w read their initializer values
  [3] per-element OSDI override: `.model ... c[1]=99` changes only that element
  [4] type-then-range form still compiles (regression)
"""
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from _setup import VAF as OPENVAF, NG as NGSPICE
from _setup import check_both_solvers as _check_both_solvers; _check_both_solvers(__file__)  # verify under BOTH KLU and Sparse solvers

checks = passed = 0
def check(label, ok, detail=""):
    global checks, passed
    checks += 1; passed += bool(ok)
    print(f"[{'PASS' if ok else 'FAIL'}] {label}" + (f"  ({detail})" if detail and not ok else ""))

def compile_va(name, out=None):
    args = [OPENVAF, name] + (["-o", out] if out else [])
    return subprocess.run(args, capture_output=True, text=True, cwd=HERE)

def run_deck(text, name):
    with open(os.path.join(HERE, name), "w") as f:
        f.write(text)
    r = subprocess.run([NGSPICE, "-b", name], capture_output=True, text=True, cwd=HERE)
    return r.stdout + r.stderr

def opval(log, tag):
    m = re.search(rf"{re.escape(tag)}\s*=\s*(-?[\d.eE+]+)", log)
    return float(m.group(1)) if m else None

for f in ("paramarray_demo.osdi", "_ttr.va", "_ttr.osdi", "_pa.sp"):
    p = os.path.join(HERE, f)
    if os.path.exists(p):
        os.remove(p)

# [1] compile
r = compile_va("paramarray_demo.va", "paramarray_demo.osdi")
compiled = r.returncode == 0 and os.path.exists(os.path.join(HERE, "paramarray_demo.osdi"))
check("paramarray_demo.va compiles (name-then-range parameter arrays)", compiled,
      (r.stderr or r.stdout).strip()[:160])

if compiled:
    # [2] element defaults + [3] per-element override
    deck = ("* param array name-then-range\n"
            "vp pp 0 1.0\nn1 pp 0 def\n.model def paramarray_demo\n"
            "vq qq 0 1.0\nn2 qq 0 ov\n.model ov paramarray_demo c[1]=99.0\n"
            ".control\npre_osdi paramarray_demo.osdi\nop\n"
            "echo c0 = $&@n1[oc0]\necho c1 = $&@n1[oc1]\necho c2 = $&@n1[oc2]\n"
            "echo a1 = $&@n1[oa1]\necho b2 = $&@n1[ob2]\necho g = $&@n1[og]\n"
            "echo m10 = $&@n1[om10]\necho w = $&@n1[ow]\n"
            "echo ovc1 = $&@n2[oc1]\necho ovc0 = $&@n2[oc0]\n"
            ".endc\n.end\n")
    log = run_deck(deck, "_pa.sp")
    expect = {"c0": 1.0, "c1": 2.0, "c2": 3.0, "a1": 20.0, "b2": 50.0,
              "g": 7.0, "m10": 3.0, "w": 8.0}
    for tag, exp in expect.items():
        got = opval(log, tag)
        check(f"default {tag} == {exp}", got is not None and abs(got - exp) < 1e-9, f"got {got}")
    check("override c[1]=99 changes only that element",
          opval(log, "ovc1") == 99.0 and opval(log, "ovc0") == 1.0,
          f"c1={opval(log,'ovc1')} c0={opval(log,'ovc0')}")

# [4] type-then-range regression
with open(os.path.join(HERE, "_ttr.va"), "w") as f:
    f.write('`include "disciplines.vams"\n'
            "module ttr (p, n);\n  inout p, n; electrical p, n;\n"
            "  parameter real [0:2] c = '{1.0, 2.0, 3.0};\n"
            "  analog I(p,n) <+ V(p,n)*c[1];\nendmodule\n")
check("type-then-range parameter array still compiles",
      compile_va("_ttr.va").returncode == 0)

for f in ("paramarray_demo.osdi", "_ttr.va", "_ttr.osdi", "_pa.sp"):
    p = os.path.join(HERE, f)
    if os.path.exists(p):
        os.remove(p)

print(f"\n{passed}/{checks} checks passed")
raise SystemExit(0 if passed == checks else 1)
