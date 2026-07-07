#!/usr/bin/env python3
"""
verify_annexe.py -- verifies Enhancement-89: the Annex E SPICE-compatibility
primitives library, end-to-end through the committed openvaf-r + ngspice.

`annex_e_primitives.va` provides resistor/capacitor/inductor, v/i sources,
and square-law spice_nmos/spice_pmos as clean Verilog-A modules. Two demos
instantiate them (flattened by Enhancement-5):

  rc_lowpass  -- resistor + capacitor
  cmos_inv    -- spice_pmos + spice_nmos

Checks:
  [1,2] both demos compile
  [3] RC lowpass DC: out == in (capacitor is open at DC)      -> 2.0 V
  [4] RC charging (tran) at t = RC reaches ~63.2% of the step  -> ~1.26 V
  [5] CMOS inverter, input low  -> output high (> 4.5 V)
  [6] CMOS inverter, input high -> output low  (< 0.5 V)
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

for m in ("rc_lowpass.va", "cmos_inv.va"):
    r = subprocess.run([OPENVAF, m], capture_output=True, text=True, cwd=HERE)
    check(f"{m} compiles", r.returncode == 0, (r.stderr or r.stdout).strip()[:100])

# DC op deck (RC + CMOS rails)
op = os.path.join(HERE, "_op.sp")
with open(op, "w") as f:
    f.write("annex-e op\n"
            "Vin in 0 2.0\n"
            "N1 in outrc rcmod\n.model rcmod rc_lowpass r=1k c=1u\n"
            "Vdd vdd 0 5\nVlo lo 0 0\nVhi hi 0 5\n"
            "Nl lo outl vdd 0 invmod\nNh hi outh vdd 0 invmod\n.model invmod cmos_inv\n"
            "Rl outl 0 1meg\nRh outh 0 1meg\n"
            ".control\npre_osdi rc_lowpass.osdi\npre_osdi cmos_inv.osdi\nop\n"
            "print v(outrc) v(outl) v(outh)\n.endc\n.end\n")
r = subprocess.run([NGSPICE, "-b", "_op.sp"], capture_output=True, text=True, cwd=HERE)
log = r.stdout + r.stderr
def vec(name):
    m = re.search(rf"v\({re.escape(name)}\)\s*=\s*([-\d.eE+]+)", log)
    return float(m.group(1)) if m else None
check("RC lowpass DC out == 2.0 V (cap open)", vec("outrc") is not None and abs(vec("outrc") - 2.0) < 1e-6, str(vec("outrc")))
check("CMOS inverter in low -> out high (> 4.5 V)", vec("outl") is not None and vec("outl") > 4.5, str(vec("outl")))
check("CMOS inverter in high -> out low (< 0.5 V)", vec("outh") is not None and vec("outh") < 0.5, str(vec("outh")))
os.remove(op)

# tran RC charging: at t = RC = 1ms, ~63.2% of 2.0 = 1.264 V
tr = os.path.join(HERE, "_tr.sp")
with open(tr, "w") as f:
    f.write("annex-e rc tran\n"
            "Vin in 0 PULSE(0 2 0 1n 1n 1 2)\n"
            "N1 in outrc rcmod\n.model rcmod rc_lowpass r=1k c=1u\n"
            ".control\npre_osdi rc_lowpass.osdi\ntran 20u 5m uic\n"
            "meas tran vrc find v(outrc) at=1m\n.endc\n.end\n")
r = subprocess.run([NGSPICE, "-b", "_tr.sp"], capture_output=True, text=True, cwd=HERE)
log = r.stdout + r.stderr
m = re.search(r"vrc\s*=\s*([-\d.eE+]+)", log)
vrc = float(m.group(1)) if m else None
check("RC charging at t=RC ~ 1.26 V (0.632*2.0)", vrc is not None and abs(vrc - 1.264) < 0.1, str(vrc))
os.remove(tr)

print(f"\n{passed}/{checks} checks passed")
sys.exit(0 if passed == checks else 1)
