#!/usr/bin/env python3
"""
verify_busport.py -- verifies Enhancement-90 (multi-bit input bus port bit
reads), end-to-end through the committed openvaf-r + ngspice.

Reading a bit of a multi-bit INPUT bus port that is not the last port in a
non-ANSI header used to return the wrong terminal (or 0): the header created a
single placeholder for the bus name, the body appended the bus's remaining
bits after the later scalar ports, and the scrambled node order mis-mapped the
netlist terminals. Enhancement-90 pre-expands the bus in header-port order so
its bits stay contiguous.

  [1] busport.va compiles
  [2..4] each output mirrors its input bit: o0=in[0], o1=in[1], o2=in[2]
         (distinct 1/2/3 V -- a scramble would swap or zero these)
  [5] a bus port in the MIDDLE of the header (scalar, bus, scalar) reads its
      bits correctly too:  q = V(in[2]) - V(in[0]) + V(p)
  [6] range-then-name and name-then-range spellings of the same bus port read
      identically (the fix is orthogonal to the declaration spelling)
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

def compile_va(path):
    return subprocess.run([OPENVAF, os.path.basename(path)], capture_output=True,
                          text=True, cwd=HERE)

def run_deck(deck):
    r = subprocess.run([NGSPICE, "-b", deck], capture_output=True, text=True, cwd=HERE)
    return r.stdout + r.stderr

def vec(log, name):
    m = re.search(rf"v\({re.escape(name)}\)\s*=\s*([-\d.eE+]+)", log)
    return float(m.group(1)) if m else None

# [1] compile the main model
r = compile_va("busport.va")
check("busport.va compiles (multi-bit input bus, bus not last)", r.returncode == 0,
      (r.stderr or r.stdout).strip()[:120])

# [2..4] per-bit read (in[0]=1, in[1]=2, in[2]=3 V)
log = run_deck("deck.sp")
for k, expect in [(0, 1.0), (1, 2.0), (2, 3.0)]:
    v = vec(log, f"o{k}")
    check(f"o{k} == in[{k}] == {expect} V", v is not None and abs(v - expect) < 1e-6, str(v))

# [5] bus in the MIDDLE of the header (scalar, bus, scalar)
mid = os.path.join(HERE, "_mid.va")
with open(mid, "w") as f:
    f.write('`include "disciplines.vams"\n'
            "module midbus(p, in, q);\n"
            "   input p; electrical p;\n"
            "   input [0:2] in; electrical [0:2] in;\n"
            "   output q; electrical q;\n"
            "   analog V(q) <+ V(in[2]) - V(in[0]) + V(p);\n"
            "endmodule\n")
rc = compile_va("_mid.va").returncode
mid_deck = os.path.join(HERE, "_mid.sp")
with open(mid_deck, "w") as f:
    f.write("* middle bus\n.model mb midbus\n"
            "Vp np 0 0.5\nVa0 na0 0 1.0\nVa1 na1 0 2.0\nVa2 na2 0 3.0\n"
            "N1 np na0 na1 na2 q mb\n"
            ".control\npre_osdi _mid.osdi\nop\nprint v(q)\n.endc\n.end\n")
log = run_deck("_mid.sp")
q = vec(log, "q")
# q = in[2]-in[0]+p = 3-1+0.5 = 2.5
check("middle bus port reads correctly (q == 2.5 V)",
      rc == 0 and q is not None and abs(q - 2.5) < 1e-6, str(q))
for f in (mid, mid_deck):
    if os.path.exists(f):
        os.remove(f)

# [6] range-then-name vs name-then-range read identically
rtn = os.path.join(HERE, "_rtn.va")
with open(rtn, "w") as f:
    f.write('`include "disciplines.vams"\n'
            "module rtn(in, o1);\n"
            "   input in[0:2];\n"            # name-then-range (Enhancement-89)
            "   electrical in[0:2];\n"
            "   output o1; electrical o1;\n"
            "   analog V(o1) <+ V(in[1]);\n"
            "endmodule\n")
rc = compile_va("_rtn.va").returncode
rtn_deck = os.path.join(HERE, "_rtn.sp")
with open(rtn_deck, "w") as f:
    f.write("* name-then-range spelling\n.model rm rtn\n"
            "Va0 na0 0 1.0\nVa1 na1 0 2.0\nVa2 na2 0 3.0\n"
            "N1 na0 na1 na2 o1 rm\n"
            ".control\npre_osdi _rtn.osdi\nop\nprint v(o1)\n.endc\n.end\n")
log = run_deck("_rtn.sp")
o1 = vec(log, "o1")
check("name-then-range spelling reads in[1] == 2.0 V",
      rc == 0 and o1 is not None and abs(o1 - 2.0) < 1e-6, str(o1))
for f in (rtn, rtn_deck):
    if os.path.exists(f):
        os.remove(f)

print(f"\n{passed}/{checks} checks passed")
raise SystemExit(0 if passed == checks else 1)
