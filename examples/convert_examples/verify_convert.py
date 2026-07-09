#!/usr/bin/env python3
"""
verify_convert.py -- verifies Enhancement-104 ($rtoi / $itor conversion
functions), through the committed
openvaf-r + ngspice.

`$rtoi(real)` truncates toward zero (LRM) -- distinct from the implicit
real->integer assignment, which rounds. `$itor(integer)` converts to real.
Only the implicit conversions existed before this enhancement.

  [1] convert_demo.va compiles ($rtoi / $itor recognized)
  [2] $rtoi truncates toward zero: 3.9->3, -3.9->-3, 3.2->3, -3.2->-3, 5.0->5
      (a rounding cast would give 4 and -4)
  [3] $rtoi in a localparam const-folds ($rtoi(9.6)=9)
  [4] $itor returns a real: itor(7)=7, itor(7)*0.5=3.5
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

def run_deck(text, name):
    with open(os.path.join(HERE, name), "w") as f:
        f.write(text)
    r = subprocess.run([NGSPICE, "-b", name], capture_output=True, text=True, cwd=HERE)
    return r.stdout + r.stderr

def opval(log, tag):
    m = re.search(rf"^{re.escape(tag)}\s*=\s*(-?[\d.eE+]+)", log, re.M)
    return float(m.group(1)) if m else None

for f in ("convert_demo.osdi", "_conv.sp"):
    p = os.path.join(HERE, f)
    if os.path.exists(p):
        os.remove(p)

r = subprocess.run([OPENVAF, "convert_demo.va"], capture_output=True, text=True, cwd=HERE)
compiled = r.returncode == 0 and os.path.exists(os.path.join(HERE, "convert_demo.osdi"))
check("convert_demo.va compiles ($rtoi / $itor recognized)", compiled,
      (r.stderr or r.stdout).strip().splitlines()[0] if (r.stderr or r.stdout).strip() else "")

if compiled:
    deck = ("* rtoi/itor\nvp pp 0 1.0\nn1 pp 0 m\n.model m convert_demo\n"
            ".control\npre_osdi convert_demo.osdi\nop\n"
            "echo r_a = $&@n1[r_a]\necho r_b = $&@n1[r_b]\necho r_c = $&@n1[r_c]\n"
            "echo r_d = $&@n1[r_d]\necho r_e = $&@n1[r_e]\necho r_l = $&@n1[r_l]\n"
            "echo i_k = $&@n1[i_k]\necho i_h = $&@n1[i_h]\n"
            ".endc\n.end\n")
    log = run_deck(deck, "_conv.sp")
    # truncation toward zero (a rounding cast would give 4 / -4)
    for tag, exp in [("r_a", 3), ("r_b", -3), ("r_c", 3), ("r_d", -3), ("r_e", 5)]:
        got = opval(log, tag)
        check(f"$rtoi -> {tag} == {exp} (truncate toward zero)", got == exp, f"got {got}")
    check("$rtoi in localparam const-folds ($rtoi(9.6)==9)", opval(log, "r_l") == 9,
          f"got {opval(log, 'r_l')}")
    check("$itor(7) == 7", opval(log, "i_k") == 7.0, f"got {opval(log, 'i_k')}")
    check("$itor(7)*0.5 == 3.5 ($itor is real)", opval(log, "i_h") == 3.5,
          f"got {opval(log, 'i_h')}")

for f in ("convert_demo.osdi", "_conv.sp"):
    p = os.path.join(HERE, f)
    if os.path.exists(p):
        os.remove(p)

print(f"\n{passed}/{checks} checks passed")
raise SystemExit(0 if passed == checks else 1)
