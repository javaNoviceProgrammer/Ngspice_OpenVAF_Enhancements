#!/usr/bin/env python3
"""
verify_legacygen.py -- verifies Enhancement-88: the obsolete Verilog-A 1.0
`generate` statement (LRM Annex C.4), end-to-end through the committed
openvaf-r + ngspice.

`flashadc.va` is the LRM page-438 flash-ADC (constant bus width): a
`generate i (3, 0)` unrolls MSB-first with a body that mutates `sample`
across iterations, so the unroll order and index substitution both matter.
For a DC input of 0.7 (fullscale 1.0) the 4-bit code is 1011 (MSB out[3]):

  out[3]=1  out[2]=0  out[1]=1  out[0]=1

  [1] compiles (the legacy `generate` statement used to be a parse error)
  [2..5] each output bit reads its exact 1/0 value
  [6] a legacy generate with a PARAMETER bound is rejected with the
      targeted "must be elaboration-time constants" diagnostic (the
      structure cannot depend on a runtime-bindable parameter)
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

r = subprocess.run([OPENVAF, "flashadc.va"], capture_output=True, text=True, cwd=HERE)
check("flashadc.va compiles", r.returncode == 0, (r.stderr or r.stdout).strip()[:100])

r = subprocess.run([NGSPICE, "-b", "deck.sp"], capture_output=True, text=True, cwd=HERE)
log = r.stdout + r.stderr
def vec(name):
    m = re.search(rf"v\({name}\)\s*=\s*([-\d.eE+]+)", log)
    return float(m.group(1)) if m else None
# out[k] expected: out0=1, out1=1, out2=0, out3=1  (code 1011, MSB=out3)
for k, expect in [(0, 1.0), (1, 1.0), (2, 0.0), (3, 1.0)]:
    v = vec(f"o{k}")
    check(f"out[{k}] == {expect:.0f} V", v is not None and abs(v - expect) < 1e-6, str(v))

bad = os.path.join(HERE, "_bad_parambound.va")
with open(bad, "w") as f:
    f.write('`include "disciplines.vams"\n'
            "module m(o); output [0:7] o; electrical [0:7] o;\n"
            "   parameter integer n = 4;\n"
            "   analog begin generate i (n-1, 0) V(o[i]) <+ 1.0; end\n"
            "endmodule\n")
r = subprocess.run([OPENVAF, "_bad_parambound.va"], capture_output=True, text=True, cwd=HERE)
out = (r.stderr or "") + (r.stdout or "")
check("parameter-bound legacy generate rejected (targeted diagnostic, no crash)",
      r.returncode != 0 and "elaboration-time constants" in out and "crashed" not in out,
      out.strip().splitlines()[0] if out.strip() else "no output")
os.remove(bad)

print(f"\n{passed}/{checks} checks passed")
sys.exit(0 if passed == checks else 1)
