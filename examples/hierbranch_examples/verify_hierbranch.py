#!/usr/bin/env python3
"""
verify_hierbranch.py -- verifies Enhancement-86: hierarchical branch probes
(the LRM page-119 forms), end-to-end through the committed openvaf-r +
ngspice.

`hier_probe.va`: a `probes` module reads, from OUTSIDE the instances,
  V(top.a1.b)               -- named branch of instance a1        -> 1.34 V
  V(top.d1.branch(va, vb))  -- unnamed branch of instance d1      -> 2.5 V
  I(top.d1.branch(<p>))*1k  -- d1's OWN current into its port p   -> 5 V

d1 and d2 are identical 1k loads in parallel: the node carries 10 mA, so the
port-branch probe pinning 5 V (= 5 mA * 1k) proves the synthesized 0V
ammeter reads INSTANCE current, not node current.

  [1] compile succeeds (all three forms were errors/panics before)
  [2] named-branch probe exact
  [3] unnamed-branch probe exact
  [4] port-branch probe reads d1's share only (5 V, not 10 V)
  [5] total source current is 10 mA (both instances conduct through
      the ammeter -- pins the two DAE fixes: small-signal
      misclassification and collapse-of-probed-branch)
  [6] an unresolvable chain is a compile error, not a silent zero
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

r = subprocess.run([OPENVAF, "hier_probe.va"], capture_output=True, text=True, cwd=HERE)
check("hier_probe.va compiles", r.returncode == 0, (r.stderr or r.stdout).strip()[:100])

r = subprocess.run([NGSPICE, "-b", "deck.sp"], capture_output=True, text=True, cwd=HERE)
log = r.stdout + r.stderr
def vec(name):
    m = re.search(rf"{re.escape(name)}\s*=\s*([-\d.eE+]+)", log)
    return float(m.group(1)) if m else None
check("V(top.a1.b) == 1.34 V (named branch)", vec("v(ovb)") is not None and abs(vec("v(ovb)") - 1.34) < 1e-9, str(vec("v(ovb)")))
check("V(top.d1.branch(va,vb)) == 2.5 V (unnamed branch)",
      vec("v(ovub)") is not None and abs(vec("v(ovub)") - 2.5) < 1e-9, str(vec("v(ovub)")))
check("I(top.d1.branch(<p>)) == 5 mA (instance current, not the 10 mA node total)",
      vec("v(oip)") is not None and abs(vec("v(oip)") - 5.0) < 1e-6, str(vec("v(oip)")))
check("i(V1) == -10 mA (both instances conduct through the ammeter)",
      vec("i(v1)") is not None and abs(vec("i(v1)") + 10e-3) < 1e-9, str(vec("i(v1)")))

bad = os.path.join(HERE, "_bad_chain.va")
with open(bad, "w") as f:
    f.write('`include "disciplines.vams"\n'
            "module m(x);\n"
            "   inout x; electrical x;\n"
            "   analog V(x) <+ V(top.nosuch.branch(a, b));\n"
            "endmodule\n")
r = subprocess.run([OPENVAF, "_bad_chain.va"], capture_output=True, text=True, cwd=HERE)
out = (r.stderr or "") + (r.stdout or "")
check("unresolvable chain is a compile error (no crash, no silent zero)",
      r.returncode != 0 and "crashed" not in out,
      out.strip().splitlines()[0] if out.strip() else "no output")
os.remove(bad)

print(f"\n{passed}/{checks} checks passed")
sys.exit(0 if passed == checks else 1)
