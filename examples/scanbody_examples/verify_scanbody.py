#!/usr/bin/env python3
"""
verify_scanbody.py -- a scan in the analog body must not crash the simulator.

A descriptor opened in `@(initial_step)` and scanned in the analog body used to
SEGFAULT ngspice:

    EXC_BAD_ACCESS (code=1, address=0x0)
    frame #0: scanbody.osdi`osdi_scan_real + 40

`$sscanf`/`$fscanf` lower to ScanBegin -> Scan* -> ScanCount, a sequence that
communicates through the runtime's cursor globals rather than through MIR
values. Nothing in the dataflow tied the three together, so the init/eval
splitter -- which copies every instruction that is not operating-point
dependent into the instance-setup function -- hoisted the field scanner and the
count while leaving ScanBegin behind with the descriptor it depends on. Setup
then ran a scanner with the cursor never initialised.

The fix marks the whole protocol operating-point dependent so it cannot be
split. These checks pin the crash AND the answer: a test that only asserted
"did not crash" would pass just as well on a build that hoisted the scanner and
silently used the fallback value instead of the scanned one.

  [1] both fixtures compile
  [2] $fscanf in the analog body does not crash (exit != -11/139)
  [3] ...and reads the right value: the file's 2.0 makes the device a 500 ohm
      conductance, so the 1k divider lands on exactly 500/1500
  [4] the manual $fgets + $sscanf equivalent does not crash either
  [5] ...and agrees with $fscanf to the last digit
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

ARTEFACTS = ["scanbody.osdi", "scanbody_manual.osdi", "scanbody_data.txt",
             "_sb.cir", "_sbm.cir"]
def clean():
    for f in ARTEFACTS:
        p = os.path.join(HERE, f)
        if os.path.exists(p):
            os.remove(p)
clean()

# first field 2.0 -> 2e-3 S -> 500 ohm
with open(os.path.join(HERE, "scanbody_data.txt"), "w") as f:
    f.write("2.0 first\n3.0 second\n5.0 third\n")
WANT = 500.0 / 1500.0

def compile_va(name):
    r = subprocess.run([OPENVAF, f"{name}.va"], capture_output=True, text=True, cwd=HERE)
    return r.returncode == 0 and os.path.exists(os.path.join(HERE, f"{name}.osdi"))

def run(name, deckname):
    deck = (f"* {name}\nv1 1 0 dc 1\nrs 1 mid 1k\nn1 mid 0 m\n.model m {name}\n"
            f".control\nset numdgt=12\npre_osdi {name}.osdi\nop\nprint v(mid)\nquit\n.endc\n.end\n")
    with open(os.path.join(HERE, deckname), "w") as f:
        f.write(deck)
    r = subprocess.run([NGSPICE, "-b", deckname], capture_output=True, text=True,
                       cwd=HERE, errors="replace")
    m = re.search(r"v\(mid\)\s*=\s*([-\d.eE+]+)", r.stdout + r.stderr)
    return r.returncode, (float(m.group(1)) if m else None)

ok_c = compile_va("scanbody") and compile_va("scanbody_manual")
check("both fixtures compile", ok_c)

if ok_c:
    rc1, v1 = run("scanbody", "_sb.cir")
    # a segfault surfaces as -11 (signal) or 139 (128+11) depending on the shell
    check("$fscanf in the analog body does not crash",
          rc1 not in (-11, 139), f"exit={rc1} (SIGSEGV)")
    check("...and reads the right value from the file",
          v1 is not None and abs(v1 - WANT) <= 1e-9 * WANT, f"got {v1}, want {WANT}")

    rc2, v2 = run("scanbody_manual", "_sbm.cir")
    check("the manual $fgets + $sscanf equivalent does not crash either",
          rc2 not in (-11, 139), f"exit={rc2} (SIGSEGV)")
    check("...and agrees with $fscanf",
          v1 is not None and v2 is not None and abs(v1 - v2) < 1e-12,
          f"fscanf={v1} manual={v2}")

clean()
print(f"\n{passed}/{checks} checks passed")
raise SystemExit(0 if passed == checks else 1)
