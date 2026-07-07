#!/usr/bin/env python3
"""
verify_baregen.py -- verifies Enhancement-96 (module-level generate-for without
the optional `generate`/`endgenerate` keywords), end-to-end through the committed openvaf-r + ngspice.

A bare module-level `for` used to fail to parse ("unexpected token 'for'"), or
be silently dropped when a following analog block let the parser resync, in two
module shapes: with a header BUS PORT, and with NO analog block. Both now parse
and the loop is elaborated.

  [1] baregen.va compiles (both modules use a bare module-level generate-for)
  [2] busgen (bus port, no analog): each bus bit i connects to ground through a
      1m*(i+1) conductance -- driving each bit to 1 V draws i(v)=1m*(i+1)
  [3] the loop was actually APPLIED, not dropped: all four branch currents are
      the expected non-zero, index-scaled values
  [4] divgen (no analog block): 4 parallel two-gcell dividers -> i(vp)=-2 mA
      (0 if the generate-for had been dropped)
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

def run_deck(text):
    p = os.path.join(HERE, "_t.sp")
    with open(p, "w") as f:
        f.write(text)
    r = subprocess.run([NGSPICE, "-b", "_t.sp"], capture_output=True, text=True, cwd=HERE)
    os.remove(p)
    return r.stdout + r.stderr

def cur(log, name):
    m = re.search(rf"{re.escape(name)}\s*=\s*([-\d.eE+]+)", log)
    return float(m.group(1)) if m else None

r = subprocess.run([OPENVAF, "baregen.va"], capture_output=True, text=True, cwd=HERE)
check("baregen.va compiles (bare module-level generate-for x2)", r.returncode == 0,
      (r.stderr or r.stdout).strip()[:140])

# busgen: drive each bit to 1 V, read the current each voltage source supplies
log = run_deck("* busgen\n.model bg busgen\n"
               "V0 b0 0 1\nV1 b1 0 1\nV2 b2 0 1\nV3 b3 0 1\n"
               "N1 b0 b1 b2 b3 bg\n"
               ".control\npre_osdi baregen.osdi\nop\nprint i(v0) i(v1) i(v2) i(v3)\n.endc\n.end\n")
vals = [cur(log, f"i(v{k})") for k in range(4)]
# g(i) = 1m*(i+1), at 1 V the source supplies -g (current leaves +)
expect = [-1e-3 * (k + 1) for k in range(4)]
ok = all(v is not None and abs(v - e) < 1e-9 for v, e in zip(vals, expect))
check("busgen: each bus bit scaled by its index (loop applied, not dropped)",
      ok, str(vals))
check("busgen: bit currents are distinct and non-zero (generate-for expanded)",
      ok and len(set(round(v, 9) for v in vals)) == 4)

# divgen: total conductance seen at p = 4 * (2 x 1m in series) = 2 mS
log = run_deck("* divgen\n.model dg divgen\nVp p 0 1\nN1 p dg\n"
               ".control\npre_osdi baregen.osdi\nop\nprint i(vp)\n.endc\n.end\n")
ivp = cur(log, "i(vp)")
check("divgen (no analog block): 4 dividers -> i(vp) = -2 mA (0 if dropped)",
      ivp is not None and abs(ivp - (-2e-3)) < 1e-9, str(ivp))

for f in ("baregen.osdi",):
    p = os.path.join(HERE, f)
    if os.path.exists(p):
        os.remove(p)

print(f"\n{passed}/{checks} checks passed")
raise SystemExit(0 if passed == checks else 1)
