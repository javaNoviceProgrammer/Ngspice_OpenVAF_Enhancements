#!/usr/bin/env python3
"""verify_ngcrashanalysis.py -- Enhancement-315: three ngspice analysis crashes on
adversarial-but-valid input, found by command/netlist fuzzing (the E-222..228 / E-270..285
hardening family). Each was a hard SIGSEGV/SIGABRT in the shipped binary; each is now a
clean error.

[6] `.tf` on a SINGULAR circuit -- a dangling inductor (`l1 2 3 1` with 2,3 floating) makes
    the operating point singular. tfanal.c IGNORED CKTop's return, so the matrix was never
    factored and the following SMPsolve() asserted `IS_VALID(Matrix) && IS_FACTORED(Matrix)`
    (spsolve.c:137, SIGABRT). Fix: propagate the CKTop error before solving.

[7] A second `.pz` over a URC device -- CKTic zeroes the RHS vectors (a loop the compiler
    vectorises into memset), but in this path `ckt->CKTrhs` is NULL, so it wrote through a
    NULL pointer (SIGSEGV). Fix: CKTic returns cleanly when the RHS vectors are unallocated
    (there are no initial conditions to place into vectors that do not exist).

[8] `.disto` with NO distortion sources (a plain resistor) -- distoan.c's output section
    left OUTpBeginPlot's result unchecked, so on failure `acPlot` stayed NULL and
    `OUTattributes(acPlot, ...)` dereferenced it (SIGSEGV at OUTattributes+268, addr 0x28).
    Fix: check the OUTpBeginPlot result and bail cleanly.

Legitimate `.tf`/`.pz`/`.disto` are unaffected -- the guards fire only on the failure paths.

Each check runs a deck that CRASHED the pre-fix binary and asserts it now exits cleanly (a
crash shows up as a negative return code = signal, or 134/139). A positive-value forward
check confirms a legitimate `.tf` still computes the right transfer function.
"""
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from _setup import NG as NGSPICE  # noqa: E402

passed = failed = 0


def check(label, ok, detail=""):
    global passed, failed
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  [{detail}]" if detail else ""))
    if ok:
        passed += 1
    else:
        failed += 1


def run(cir):
    try:
        r = subprocess.run([NGSPICE, "-b", cir], cwd=HERE, capture_output=True,
                           text=True, timeout=60, errors="replace")
    except subprocess.TimeoutExpired:
        return -99, "[TIMEOUT]"
    return r.returncode, (r.stdout or "") + (r.stderr or "")


print("Enhancement-315: ngspice analysis crash-hardening (.tf / .pz / .disto)")

for label, cir in [("[6] .tf singular circuit no longer SIGABRTs", "tf_singular.cir"),
                   ("[7] second .pz over a URC device no longer SIGSEGVs", "pz_urc.cir"),
                   ("[8] .disto with no distortion sources no longer SIGSEGVs", "disto_nosrc.cir")]:
    rc, _ = run(cir)
    # a signal shows up as a negative rc under subprocess; 134/139 if shell-wrapped
    check(label, rc >= 0 and rc not in (134, 139), f"rc={rc}")

# forward guard: a legitimate .tf still computes the right transfer function
with open(os.path.join(HERE, "_vtf.cir"), "w") as fh:
    fh.write("* valid tf\nv1 1 0 dc 1\nr1 1 2 1k\nr2 2 0 1k\n.tf v(2) v1\n.end\n")
rc, out = run("_vtf.cir")
m = re.search(r"transfer_function\s*=\s*([-\d.eE+]+)", out)
tf = float(m.group(1)) if m else None
check("legitimate .tf still computes the correct transfer function (0.5)",
      tf is not None and abs(tf - 0.5) < 1e-6, f"tf={tf}")

for f in os.listdir(HERE):
    if f.startswith("_"):
        os.remove(os.path.join(HERE, f))

print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
