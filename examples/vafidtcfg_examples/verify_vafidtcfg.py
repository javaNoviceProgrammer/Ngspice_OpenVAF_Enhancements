#!/usr/bin/env python3
"""verify_vafidtcfg.py -- Enhancement-317: an idt() initial condition inside a statically-false
branch crashed openvaf-r codegen.

`ceil(0) > 1` is always false but ceil() is not const-folded, so the dead branch survives into
MIR. The guarded `w = idt(V(a),0)` initial-condition state is never used, so codegen prunes the
branch CONDITION's computation as dead -- yet the Branch instruction survives into
osdi::setup::setup_instance, and reading its now-Undef condition hit unreachable!() in the LLVM
builder (mir_llvm/builder.rs:143), crashing the SHIPPED compiler (exit 101). The fix lowers an
Undef branch condition as constant false (the guarded code is dead on either edge).

Checks (the first FAILS on the pre-fix binary):
  1. the reproducer compiles (it crashed the compiler before);
  2. its model simulates to a finite operating point -- it reduces to a 1mS conductance in
     parallel with a tiny integrator, I(a,b) = 1e-3*V + 1e-6*idt(V).
"""
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from _setup import VAF as OPENVAF, NG as NGSPICE  # noqa: E402
from _setup import check_both_solvers as _check_both_solvers  # noqa: E402
_check_both_solvers(__file__)

checks = passed = 0


def check(label, ok, detail=""):
    global checks, passed
    checks += 1
    passed += bool(ok)
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  [{detail}]" if detail else ""))


osdi = os.path.join(HERE, "idt_deadbranch.osdi")
r = subprocess.run([OPENVAF, os.path.join(HERE, "idt_deadbranch.va"), "-o", osdi],
                   capture_output=True, text=True, timeout=120, errors="replace")
out = ((r.stdout or "") + (r.stderr or "")).lower()
crashed = "has crashed" in out or "panicked at" in out or "please open an issue" in out
print("Enhancement-317: idt initial-condition in a dead branch")
check("reproducer compiles (crashed the shipped compiler before)",
      not crashed and r.returncode == 0 and os.path.exists(osdi),
      "COMPILER CRASH" if crashed else f"rc={r.returncode}")

if os.path.exists(osdi):
    deck = (f"* idt cfg op\n.control\npre_osdi {osdi}\n.endc\n"
            f"v1 a 0 dc 0.5\nn1 a 0 m1\n.model m1 idtcfg\n"
            f".control\nop\nprint i(v1)\n.endc\n.end\n")
    with open(os.path.join(HERE, "_op.cir"), "w") as fh:
        fh.write(deck)
    r2 = subprocess.run([NGSPICE, "-b", "_op.cir"], cwd=HERE, capture_output=True,
                        text=True, timeout=60, errors="replace")
    o2 = (r2.stdout or "") + (r2.stderr or "")
    m = re.search(r"i\(v1\)\s*=\s*([-\d.eE+]+)", o2)
    iv = float(m.group(1)) if m else None
    finite = iv is not None and abs(iv) < 1e3 and "nan" not in o2.lower()
    # DC: idt of a constant integrates unboundedly in tran, but .op treats idt as 0-state ->
    # I(a,b) = 1e-3*0.5 = 5e-4, so i(v1) = -5e-4. Accept any finite op.
    check("model simulates to a finite operating point", finite, f"i(v1)={iv}")

for f in os.listdir(HERE):
    if f.startswith("_") or f.endswith(".osdi"):
        os.remove(os.path.join(HERE, f))

print(f"\n{passed}/{checks} checks passed")
sys.exit(0 if passed == checks else 1)
