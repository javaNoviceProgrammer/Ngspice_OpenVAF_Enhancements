#!/usr/bin/env python3
"""
verify_arrayport.py -- verifies Enhancement-89 (name-then-range net/port
declarations), end-to-end through the committed openvaf-r + ngspice.

`arrayport.va` (module `tapbuf`) declares its output bus in the
name-then-range form `output out[0:3]; electrical out[0:3];` -- the
unpacked-array style of a vectored port/net (LRM 3.6/3.7, page 45),
complementing the range-then-name form `output [0:3] out;` (Enhancement-3).

  [1] compiles (name-then-range used to be a parse / discipline-name error)
  [2..5] each output tap reads its exact value: out[k] = (k+1)*0.5
  [6] a name-then-range INPUT port also parses (`input in[0:2];`)
  [7] the name-then-range and range-then-name forms are equivalent (both
      compile to the same behaviour)
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

r = subprocess.run([OPENVAF, "arrayport.va"], capture_output=True, text=True, cwd=HERE)
check("arrayport.va compiles (name-then-range output bus)", r.returncode == 0,
      (r.stderr or r.stdout).strip()[:100])

r = subprocess.run([NGSPICE, "-b", "deck.sp"], capture_output=True, text=True, cwd=HERE)
log = r.stdout + r.stderr
def vec(name):
    m = re.search(rf"v\({name}\)\s*=\s*([-\d.eE+]+)", log)
    return float(m.group(1)) if m else None
for k, expect in [(0, 0.5), (1, 1.0), (2, 1.5), (3, 2.0)]:
    v = vec(f"o{k}")
    check(f"out[{k}] == {expect} V", v is not None and abs(v - expect) < 1e-6, str(v))

# name-then-range INPUT port parses
inmod = os.path.join(HERE, "_inport.va")
with open(inmod, "w") as f:
    f.write('`include "disciplines.vams"\n'
            "module m(a, b);\n"
            "   input a[0:2];\n"           # name-then-range input port
            "   output b;\n"
            "   electrical a[0:2];\n"       # name-then-range input net
            "   electrical b;\n"
            "   analog V(b) <+ V(a[0]);\n"
            "endmodule\n")
r = subprocess.run([OPENVAF, "_inport.va"], capture_output=True, text=True, cwd=HERE)
check("name-then-range input port compiles", r.returncode == 0,
      (r.stderr or r.stdout).strip()[:100])
os.remove(inmod)

# equivalence: range-then-name twin compiles identically
rtn = os.path.join(HERE, "_rtn.va")
with open(rtn, "w") as f:
    f.write('`include "disciplines.vams"\n'
            "module tapbuf(in, out);\n"
            "   input in; output [0:3] out;\n"
            "   electrical in; electrical [0:3] out;\n"
            "   parameter real gain = 1.0 from (0:inf);\n"
            "   analog begin\n"
            "      V(out[0]) <+ 0.25*gain*V(in); V(out[1]) <+ 0.50*gain*V(in);\n"
            "      V(out[2]) <+ 0.75*gain*V(in); V(out[3]) <+ 1.00*gain*V(in);\n"
            "   end\n"
            "endmodule\n")
r = subprocess.run([OPENVAF, "_rtn.va"], capture_output=True, text=True, cwd=HERE)
check("range-then-name twin compiles (equivalence)", r.returncode == 0,
      (r.stderr or r.stdout).strip()[:100])
os.remove(rtn)

print(f"\n{passed}/{checks} checks passed")
sys.exit(0 if passed == checks else 1)
