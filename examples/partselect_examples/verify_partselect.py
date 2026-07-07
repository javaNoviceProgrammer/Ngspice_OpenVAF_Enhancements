#!/usr/bin/env python3
"""
verify_partselect.py -- verifies Enhancement-85 (F6): part-selects in
instance port connections, end-to-end through the committed openvaf-r +
ngspice.

`bus_split.va` drives a 4-bit bus with V(v[k]) = k volts and wires it to
three instances by slicing: a positional part-select (v[3:2]), a named one
(.i(v[1:0])), and a width-1 slice onto a scalar port (v[2:2]). Each `pair`
outputs 2*V(msb) + V(lsb), so the DC outputs pin the exact bit routing.

  [1] compile succeeds (part-selects used to be parse errors)
  [2] o1 = 2*3+2 = 8 V   (positional v[3:2])
  [3] o2 = 2*1+0 = 2 V   (named .i(v[1:0]))
  [4] o3 = 2 V           (width-1 slice v[2:2] == v[2])
  [5] a part-select in behavioral code is rejected with the dedicated
      diagnostic (and does not crash)
"""
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

r = subprocess.run([OPENVAF, "bus_split.va"], capture_output=True, text=True, cwd=HERE)
check("bus_split.va compiles", r.returncode == 0, (r.stderr or r.stdout).strip()[:100])

r = subprocess.run([NGSPICE, "-b", "deck.sp"], capture_output=True, text=True, cwd=HERE)
log = r.stdout + r.stderr
def node(name):
    m = re.search(rf"v\({name}\)\s*=\s*([-\d.eE+]+)", log)
    return float(m.group(1)) if m else None
for name, expect, why in [("o1", 8.0, "positional v[3:2]"),
                          ("o2", 2.0, "named .i(v[1:0])"),
                          ("o3", 2.0, "width-1 slice v[2:2]")]:
    v = node(name)
    check(f"{name} == {expect} V ({why})", v is not None and abs(v - expect) < 1e-9, str(v))

bad = os.path.join(HERE, "_bad_behavioral.va")
with open(bad, "w") as f:
    f.write('`include "disciplines.vams"\n'
            "module m(a, b);\n"
            "   inout a, b; electrical a, b;\n"
            "   real v[0:3];\n"
            "   analog begin\n"
            "      v[0] = 1.0;\n"
            "      V(a,b) <+ v[2:1];\n"
            "   end\n"
            "endmodule\n")
r = subprocess.run([OPENVAF, "_bad_behavioral.va"], capture_output=True, text=True, cwd=HERE)
out = (r.stderr or "") + (r.stdout or "")
check("behavioral part-select rejected with dedicated diagnostic",
      r.returncode != 0 and "part-select in an expression" in out and "crashed" not in out,
      out.strip().splitlines()[0] if out.strip() else "no output")
os.remove(bad)

print(f"\n{passed}/{checks} checks passed")
sys.exit(0 if passed == checks else 1)
