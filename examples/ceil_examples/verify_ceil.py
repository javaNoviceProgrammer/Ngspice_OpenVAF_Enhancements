#!/usr/bin/env python3
"""
verify_ceil.py -- verifies Enhancement-103 (`ceil()` of a runtime argument),
through the committed openvaf-r + ngspice.

The codegen emitted `llvm.ceil.f64` for `ceil()`, but that intrinsic was never
registered (its sibling `llvm.floor.f64` was), so `ceil(x)` for any non-constant
`x` crashed the compiler ("intrinsic llvm.ceil.f64 not found"). Registering it
fixes the crash. The `c_*` opvars take `ceil` of PARAMETERS (the runtime path a
constant argument would fold away), `f_*` cross-check `floor`.

  [1] ceil_demo.va compiles (no crash on ceil of a non-constant argument)
  [2] ceil values are exact: ceil(2.1)=3, ceil(2.0)=2, ceil(-2.7)=-2,
      ceil(-0.5)=0, ceil(5.0)=5
  [3] floor still correct on the same inputs (floor(2.1)=2, floor(-2.7)=-3)
"""
import math
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from _setup import VAF as OPENVAF, NG as NGSPICE

checks = passed = 0
def check(label, ok, detail=""):
    global checks, passed
    checks += 1; passed += bool(ok)
    print(f"[{'PASS' if ok else 'FAIL'}] {label}" + (f"  ({detail})" if detail and not ok else ""))

def run_deck(text, name):
    with open(os.path.join(HERE, name), "w") as f:
        f.write(text)
    r = subprocess.run([NGSPICE, "-b", name], capture_output=True, text=True, cwd=HERE)
    return r.stdout + r.stderr

def opval(log, tag):
    m = re.search(rf"^{re.escape(tag)}\s*=\s*(-?[\d.eE+]+)", log, re.M)
    return float(m.group(1)) if m else None

for f in ("ceil_demo.osdi", "_ceil.sp"):
    p = os.path.join(HERE, f)
    if os.path.exists(p):
        os.remove(p)

# [1] compile -- this alone crashed the compiler before the fix
r = subprocess.run([OPENVAF, "ceil_demo.va"], capture_output=True, text=True, cwd=HERE)
compiled = r.returncode == 0 and os.path.exists(os.path.join(HERE, "ceil_demo.osdi"))
check("ceil_demo.va compiles (ceil of a non-constant argument)", compiled,
      (r.stderr or r.stdout).strip().splitlines()[0] if (r.stderr or r.stdout).strip() else "")

if compiled:
    deck = ("* ceil runtime\nvp pp 0 1.0\nn1 pp 0 m\n.model m ceil_demo\n"
            ".control\npre_osdi ceil_demo.osdi\nop\n"
            "echo c_a = $&@n1[c_a]\necho c_b = $&@n1[c_b]\necho c_c = $&@n1[c_c]\n"
            "echo c_d = $&@n1[c_d]\necho c_e = $&@n1[c_e]\n"
            "echo f_a = $&@n1[f_a]\necho f_c = $&@n1[f_c]\n"
            ".endc\n.end\n")
    log = run_deck(deck, "_ceil.sp")
    for tag, exp in [("c_a", 3.0), ("c_b", 2.0), ("c_c", -2.0), ("c_d", 0.0), ("c_e", 5.0)]:
        got = opval(log, tag)
        check(f"{tag} == {exp}", got is not None and got == exp, f"got {got}")
    for tag, exp in [("f_a", 2.0), ("f_c", -3.0)]:
        got = opval(log, tag)
        check(f"{tag} == {exp} (floor cross-check)", got is not None and got == exp, f"got {got}")

for f in ("ceil_demo.osdi", "_ceil.sp"):
    p = os.path.join(HERE, f)
    if os.path.exists(p):
        os.remove(p)

print(f"\n{passed}/{checks} checks passed")
raise SystemExit(0 if passed == checks else 1)
