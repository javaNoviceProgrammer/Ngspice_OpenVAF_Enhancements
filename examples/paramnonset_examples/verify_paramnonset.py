#!/usr/bin/env python3
"""
verify_paramnonset.py -- verifies Enhancement-93, end-to-end through the committed openvaf-r + ngspice.

A Verilog-A localparam (including a structural width parameter frozen by
Enhancement-92) is flagged non-settable in the OSDI parameter descriptor
(PARA_FLAG_FIXED). ngspice warns -- instead of silently swallowing the value --
when a netlist tries to set one.

  [1] paramnonset.va compiles
  [2] overriding the frozen width parameter N warns AND keeps the default value
      (`.model ws wsum N=8` -> warning + v(s)=2.08333, not the pre-E-92 6.08)
  [3] overriding a hand-written localparam (scale) warns AND keeps the default
  [4] overriding an ordinary parameter (gain) does NOT warn and DOES take effect
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
    p = os.path.join(HERE, "_t.sp")
    with open(p, "w") as f:
        f.write(text)
    r = subprocess.run([NGSPICE, "-b", "_t.sp"], capture_output=True, text=True, cwd=HERE)
    os.remove(p)
    return r.stdout + r.stderr

def vec(log, name):
    m = re.search(rf"v\({re.escape(name)}\)\s*=\s*([-\d.eE+]+)", log)
    return float(m.group(1)) if m else None

WARN = re.compile(r"parameter '(\w+)' is a fixed \(localparam\) value", re.I)

r = subprocess.run([OPENVAF, "paramnonset.va"], capture_output=True, text=True, cwd=HERE)
check("paramnonset.va compiles", r.returncode == 0, (r.stderr or r.stdout).strip()[:120])

log = run_deck("* frozen width override\n.model ws wsum N=8\nN1 s ws\n"
               ".control\npre_osdi paramnonset.osdi\nop\nprint v(s)\n.endc\n.end\n")
m = WARN.search(log)
check("overriding frozen width N warns", bool(m) and m.group(1) == "N",
      "no warning" if not m else m.group(1))
check("...and N keeps its default (v(s)=2.08333)",
      (v := vec(log, "s")) is not None and abs(v - 2.0833333) < 1e-5, str(v))

log = run_deck("* localparam override\n.model d derived scale=9\nN1 o d\n"
               ".control\npre_osdi paramnonset.osdi\nop\nprint v(o)\n.endc\n.end\n")
m = WARN.search(log)
check("overriding a hand-written localparam warns", bool(m) and m.group(1) == "scale",
      "no warning" if not m else m.group(1))
check("...and scale keeps its default (v(o)=2.5)",
      (v := vec(log, "o")) is not None and abs(v - 2.5) < 1e-6, str(v))

log = run_deck("* ordinary param override\n.model ws wsum gain=3\nN1 s ws\n"
               ".control\npre_osdi paramnonset.osdi\nop\nprint v(s)\n.endc\n.end\n")
check("overriding an ordinary parameter does NOT warn", not WARN.search(log))
check("...and gain takes effect (v(s)=6.25)",
      (v := vec(log, "s")) is not None and abs(v - 6.25) < 1e-6, str(v))

print(f"\n{passed}/{checks} checks passed")
raise SystemExit(0 if passed == checks else 1)
