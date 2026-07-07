#!/usr/bin/env python3
"""
verify_gcontrib.py -- verifies Enhancement-97 (clean diagnostic instead of an
ICE when contributing to a ground-only branch), through the committed openvaf-r + ngspice.

`V(gnd) <+ ...` -- a contribution whose branch is entirely the `ground`
reference -- used to PANIC the compiler ("unreachable!()" in
lower_contribute_unnamed_branch). It is now a clean, located diagnostic. A real
node-to-ground contribution is unaffected.

  [1] a valid node-to-ground model (gcontrib.va) compiles and drives the node
      (V(p, gnd) <+ 1.5 -> v(p) = 1.5)
  [2] V(gnd) <+ 0 is REJECTED with the "ground node" diagnostic
  [3] ...and does NOT crash the compiler (no "please open an issue" ICE banner)
  [4] a valid node-to-ground contribution is NOT rejected (no false positive)
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

def compile_src(text):
    p = os.path.join(HERE, "_t.va")
    with open(p, "w") as f:
        f.write(text)
    r = subprocess.run([OPENVAF, "_t.va"], capture_output=True, text=True, cwd=HERE)
    out = r.stdout + r.stderr
    for ext in ("_t.va", "_t.osdi"):
        q = os.path.join(HERE, ext)
        if os.path.exists(q):
            os.remove(q)
    return r.returncode, out

HDR = ('`include "disciplines.vams"\n'
       "module m(a); inout a; electrical a; ground gnd; electrical gnd;\n")

# [1] valid model compiles + runs
r = subprocess.run([OPENVAF, "gcontrib.va"], capture_output=True, text=True, cwd=HERE)
check("gcontrib.va (node-to-ground contribution) compiles", r.returncode == 0,
      (r.stderr or r.stdout).strip()[:120])
with open(os.path.join(HERE, "t.sp"), "w") as f:
    f.write("* node-to-ground source\n.model vs vsrc\nN1 p vs\nRl p 0 1meg\n"
            ".control\npre_osdi gcontrib.osdi\nop\nprint v(p)\n.endc\n.end\n")
r = subprocess.run([NGSPICE, "-b", "t.sp"], capture_output=True, text=True, cwd=HERE)
m = re.search(r"v\(p\)\s*=\s*([-\d.eE+]+)", r.stdout + r.stderr)
check("V(p, gnd) <+ 1.5 drives the node (v(p) = 1.5)",
      m is not None and abs(float(m.group(1)) - 1.5) < 1e-6, m and m.group(1))

# [2]/[3] V(gnd) <+ 0 rejected cleanly, no ICE
rc, out = compile_src(HDR + "analog V(gnd) <+ 0.0; endmodule\n")
check("V(gnd) <+ 0 is rejected", rc != 0 and "ground node" in out, out.strip()[:120])
check("...with a clean diagnostic, NOT a compiler panic",
      "open an issue" not in out and "has crashed" not in out, out.strip()[:120])

# [4] valid node-to-ground contribution not a false positive
rc, _ = compile_src(HDR + "analog V(a, gnd) <+ 1.0; endmodule\n")
check("V(a, gnd) <+ 1 is NOT rejected (no false positive)", rc == 0)

for f in ("t.sp", "gcontrib.osdi"):
    p = os.path.join(HERE, f)
    if os.path.exists(p):
        os.remove(p)

print(f"\n{passed}/{checks} checks passed")
raise SystemExit(0 if passed == checks else 1)
