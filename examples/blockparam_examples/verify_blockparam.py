#!/usr/bin/env python3
"""
verify_blockparam.py -- verifies Enhancement-87: block-scoped parameters
(LRM 6.3 / page 112), end-to-end through the committed openvaf-r + ngspice.

`blockparam.va` declares `parameter`/`localparam` inside named `begin: label`
blocks, derives them from module parameters, and reads them hierarchically.
`nested.va` nests a block param derived from an outer block param.

  [1] both models compile
  [2] defaults: vout = gain^2 + 1 + offset*10 = 4 + 1 + 5 = 10 V
  [3] model-card override (gain=3, offset=0.2) flows into the block-scoped
      parameters: vout = 9 + 1 + 2 = 12 V   (the key propagation check)
  [4] nested block param derived from an outer block param: 7 V
  [5] an instance override of a block-scoped parameter (`#(.s.g2(9))`) is
      rejected with the targeted diagnostic (LRM page-112 `// error` case),
      and does NOT cascade or crash
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

for m in ("blockparam.va", "nested.va"):
    r = subprocess.run([OPENVAF, m], capture_output=True, text=True, cwd=HERE)
    check(f"{m} compiles", r.returncode == 0, (r.stderr or r.stdout).strip()[:100])

r = subprocess.run([NGSPICE, "-b", "deck.sp"], capture_output=True, text=True, cwd=HERE)
log = r.stdout + r.stderr
def vec(name):
    m = re.search(rf"v\({name}\)\s*=\s*([-\d.eE+]+)", log)
    return float(m.group(1)) if m else None
for name, expect, why in [("a", 10.0, "defaults gain=2 offset=0.5"),
                          ("b", 12.0, "override gain=3 offset=0.2 flows into block params"),
                          ("n", 7.0, "nested block param from outer block param")]:
    v = vec(name)
    check(f"v({name}) == {expect} V ({why})", v is not None and abs(v - expect) < 1e-9, str(v))

bad = os.path.join(HERE, "_bad_override.va")
with open(bad, "w") as f:
    f.write('`include "disciplines.vams"\n'
            "module ex(a); inout a; electrical a;\n"
            "   parameter integer p1 = 1;\n"
            "   analog begin\n"
            "      begin: s\n"
            "         parameter real g2 = p1;\n"
            "      end\n"
            "      V(a) <+ s.g2;\n"
            "   end\n"
            "endmodule\n"
            "module top(a); inout a; electrical a;\n"
            "   ex #(.s.g2(9)) inst(a);\n"
            "endmodule\n")
r = subprocess.run([OPENVAF, "_bad_override.va"], capture_output=True, text=True, cwd=HERE)
out = (r.stderr or "") + (r.stdout or "")
check("block-scoped override rejected with targeted diagnostic (no cascade/crash)",
      r.returncode != 0 and "hierarchical/block-scoped parameter" in out
      and "crashed" not in out and "already declared" not in out,
      out.strip().splitlines()[0] if out.strip() else "no output")
os.remove(bad)

print(f"\n{passed}/{checks} checks passed")
sys.exit(0 if passed == checks else 1)
