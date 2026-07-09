#!/usr/bin/env python3
"""
verify_paramwidth.py -- verifies Enhancement-91, end-to-end through version11's
own openvaf-r + ngspice.

Two features:
  * parameter-dependent declaration widths -- `real w[0:N-1];`,
    `electrical [0:bits-1] out;` -- folded from the parameter's default;
  * multi-name name-then-range declarations -- `input a[0:1], b[0:2], c;` --
    completing the single-name form of Enhancement-89.

  [1] param-sized array + runtime loop over the parameter: N=4 harmonic sum
      1 + 1/2 + 1/3 + 1/4 = 2.08333
  [2] the same source with N=8: 1 + 1/2 + ... + 1/8 = 2.71786 (width tracks
      the parameter default)
  [3] param-WIDTH node bus, bits=4: four terminals at 0.25/0.5/0.75/1.0
  [4] param-WIDTH node bus, bits=6: six terminals at 0.1..0.6 (the bus, and so
      the terminal count, tracks the parameter default)
  [5] multi-name name-then-range: two buses of different widths + a scalar,
      each bit read exactly (a[1]=2, b[2]=5, c=9)
  [6] a multi-DIMENSIONAL name-then-range (`in[0:2][0:1]`) is still rejected
      cleanly -- multi-dim vectored ports are unsupported in both spellings.
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

def compile_va(name):
    return subprocess.run([OPENVAF, name], capture_output=True, text=True, cwd=HERE)

def run_deck(deck):
    r = subprocess.run([NGSPICE, "-b", deck], capture_output=True, text=True, cwd=HERE)
    return r.stdout + r.stderr

def vec(log, name):
    m = re.search(rf"v\({re.escape(name)}\)\s*=\s*([-\d.eE+]+)", log)
    return float(m.group(1)) if m else None

# ---- parameter-dependent widths ----
r = compile_va("paramwidth.va")
check("paramwidth.va compiles (param-dependent widths)", r.returncode == 0,
      (r.stderr or r.stdout).strip()[:120])

with open(os.path.join(HERE, "pw.sp"), "w") as f:
    f.write("* param-width\n"
            ".model ws4 wsum4\n.model ws8 wsum8\n.model bo4 busout4\n.model bo6 busout6\n"
            "N1 s4 ws4\nN2 s8 ws8\n"
            "N3 a0 a1 a2 a3 bo4\n"
            "N4 c0 c1 c2 c3 c4 c5 bo6\n"
            ".control\npre_osdi paramwidth.osdi\nop\n"
            "print v(s4) v(s8) v(a0) v(a1) v(a2) v(a3) v(c0) v(c5)\n.endc\n.end\n")
log = run_deck("pw.sp")
s4 = vec(log, "s4")
check("param-sized array N=4 sum == 2.08333", s4 is not None and abs(s4 - 2.0833333) < 1e-5, str(s4))
s8 = vec(log, "s8")
check("param-sized array N=8 sum == 2.71786 (tracks default)",
      s8 is not None and abs(s8 - 2.7178571) < 1e-5, str(s8))
for k, ex in [(0, 0.25), (1, 0.5), (2, 0.75), (3, 1.0)]:
    v = vec(log, f"a{k}")
    check(f"busout4 (bits=4) out[{k}] == {ex}", v is not None and abs(v - ex) < 1e-6, str(v))
c0, c5 = vec(log, "c0"), vec(log, "c5")
check("busout6 (bits=6) has 6 bits: out[0]=0.1, out[5]=0.6",
      c0 is not None and c5 is not None and abs(c0 - 0.1) < 1e-6 and abs(c5 - 0.6) < 1e-6,
      f"{c0},{c5}")

# ---- multi-name name-then-range ----
r = compile_va("multiname.va")
check("multiname.va compiles (multi-name name-then-range)", r.returncode == 0,
      (r.stderr or r.stdout).strip()[:120])
with open(os.path.join(HERE, "mn.sp"), "w") as f:
    f.write("* multi-name\n.model mm mnbus\n"
            "Va0 na0 0 1\nVa1 na1 0 2\nVb0 nb0 0 3\nVb1 nb1 0 4\nVb2 nb2 0 5\nVc nc 0 9\n"
            "N1 na0 na1 nb0 nb1 nb2 nc o1 o2 o3 mm\n"
            ".control\npre_osdi multiname.osdi\nop\nprint v(o1) v(o2) v(o3)\n.endc\n.end\n")
log = run_deck("mn.sp")
o1, o2, o3 = vec(log, "o1"), vec(log, "o2"), vec(log, "o3")
check("multi-name buses read per-bit: a[1]=2, b[2]=5, c=9",
      o1 is not None and abs(o1 - 2) < 1e-6 and abs(o2 - 5) < 1e-6 and abs(o3 - 9) < 1e-6,
      f"{o1},{o2},{o3}")

# ---- multi-dim name-then-range still cleanly rejected ----
md = os.path.join(HERE, "_md.va")
with open(md, "w") as f:
    f.write('`include "disciplines.vams"\n'
            "module m(a); input a[0:2][0:1]; electrical a[0:2][0:1];\n"
            "   analog V(a[0][0]) <+ 1.0;\nendmodule\n")
rc = compile_va("_md.va").returncode
check("multi-dim name-then-range rejected cleanly (not a crash)", rc != 0)
if os.path.exists(md):
    os.remove(md)

for f in ("pw.sp", "mn.sp"):
    p = os.path.join(HERE, f)
    if os.path.exists(p):
        os.remove(p)

print(f"\n{passed}/{checks} checks passed")
raise SystemExit(0 if passed == checks else 1)
