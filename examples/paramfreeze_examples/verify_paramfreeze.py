#!/usr/bin/env python3
"""
verify_paramfreeze.py -- verifies Enhancement-92, end-to-end through the committed openvaf-r + ngspice.

A parameter that shapes a declaration width (Enhancement-91) is structural and
is frozen to a localparam, so a netlist override cannot desync the frozen
structure from behavioural code.

  [1] paramfreeze.va compiles
  [2] wsum default (N=4): harmonic sum 1 + 1/2 + 1/3 + 1/4 = 2.08333
  [3] wsum with `.model ws wsum N=8`: STILL 2.08333 -- the override is ignored,
      the model keeps its default width and value (before E-92 this desynced
      the default-sized array from a loop that ran to 8, giving garbage ~6.08).
      A width parameter is frozen to a localparam, so it is not settable.
  [4] mp: a non-width parameter (`gain`) stays overridable -- `.model m mp
      gain=10` scales the outputs (out[0]=1.0, out[3]=4.0), proving only the
      structural name froze (the multi-parameter declaration was split)
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

def run_deck(text):
    path = os.path.join(HERE, "_t.sp")
    with open(path, "w") as f:
        f.write(text)
    r = subprocess.run([NGSPICE, "-b", "_t.sp"], capture_output=True, text=True, cwd=HERE)
    os.remove(path)
    return r.stdout + r.stderr

def vec(log, name):
    m = re.search(rf"v\({re.escape(name)}\)\s*=\s*([-\d.eE+]+)", log)
    return float(m.group(1)) if m else None

r = subprocess.run([OPENVAF, "paramfreeze.va"], capture_output=True, text=True, cwd=HERE)
check("paramfreeze.va compiles", r.returncode == 0, (r.stderr or r.stdout).strip()[:120])

DEF = "* wsum default\n.model ws wsum\nN1 s ws\n.control\npre_osdi paramfreeze.osdi\nop\nprint v(s)\n.endc\n.end\n"
d = vec(run_deck(DEF), "s")
check("wsum default N=4 == 2.08333", d is not None and abs(d - 2.0833333) < 1e-5, str(d))

OV = "* wsum N=8 override\n.model ws wsum N=8\nN1 s ws\n.control\npre_osdi paramfreeze.osdi\nop\nprint v(s)\n.endc\n.end\n"
o = vec(run_deck(OV), "s")
check("wsum N=8 override IGNORED, stays 2.08333 (no corruption)",
      o is not None and abs(o - 2.0833333) < 1e-5, str(o))

MP = ("* mp gain override\n.model m mp gain=10\nN1 a b c d m\n"
      ".control\npre_osdi paramfreeze.osdi\nop\nprint v(a) v(d)\n.endc\n.end\n")
log = run_deck(MP)
a, dd = vec(log, "a"), vec(log, "d")
check("non-width parameter 'gain' stays overridable (gain=10: out[0]=1.0, out[3]=4.0)",
      a is not None and dd is not None and abs(a - 1.0) < 1e-6 and abs(dd - 4.0) < 1e-6,
      f"{a},{dd}")

print(f"\n{passed}/{checks} checks passed")
raise SystemExit(0 if passed == checks else 1)
