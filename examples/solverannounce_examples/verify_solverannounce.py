#!/usr/bin/env python3
"""verify_solverannounce.py -- Enhancement-266: announce the direct linear solver
once, not on every analysis.

`CKTsetup` (and `CKTpzSetup`) printed "Using SPARSE 1.3 as Direct Linear Solver"
(or "Using KLU ...") unconditionally, once per analysis. Commands that re-run the
analysis for many points -- `sweep`, Monte Carlo, `optimize` -- therefore
reprinted it on every iteration (a five-point sweep printed it five times). The
line is now emitted only when the active solver *changes* (announce-on-change,
tracked process-wide), so:

  * a multi-point sweep announces the solver once, not per point;
  * a single analysis still announces it once (behaviour unchanged);
  * a genuine solver switch (`.option klu` / `.option sparse`) re-announces;
  * KLU detection that relies on seeing the line at least once (the HB and
    benchmark suites) still works.

Solver-agnostic: the checks drive ngspice directly and count the announce line,
so this does not go through the dual-solver harness. Exit 0 = pass.
"""
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from _setup import NG as NGSPICE  # noqa: E402

SPARSE = "Using SPARSE 1.3 as Direct Linear Solver"
KLU = "Using KLU as Direct Linear Solver"

checks = passed = 0


def check(label, ok, detail=""):
    global checks, passed
    checks += 1
    passed += bool(ok)
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  [{detail}]" if detail else ""))


def run_deck(text):
    """Run a deck in batch mode; return combined stdout+stderr."""
    path = os.path.join(tempfile.gettempdir(), "solverannounce_in.cir")
    with open(path, "w") as f:
        f.write(text)
    try:
        r = subprocess.run([NGSPICE, "-b", path],
                           capture_output=True, text=True, timeout=60, errors="replace")
    except subprocess.TimeoutExpired:
        return "[TIMEOUT]"
    return (r.stdout or "") + (r.stderr or "")


print("Enhancement-266: announce the direct linear solver once, not per analysis")

# [1] A five-point sweep announces SPARSE exactly once (was five times).
sweep = (
    "* param sweep\n.param rval=1k\nr1 1 0 {rval}\nv1 1 0 1\n"
    ".control\nsweep rval 1k 5k 1k -output v(1)\n.endc\n.end\n")
n = run_deck(sweep).count(SPARSE)
check("[1] 5-point sweep announces SPARSE once (was once-per-point)", n == 1, f"count={n}")

# [2] A single op still announces it once (behaviour preserved).
op = "* op\nr1 1 0 1k\nv1 1 0 1\n.control\nop\n.endc\n.end\n"
n = run_deck(op).count(SPARSE)
check("[2] single op still announces the solver once", n == 1, f"count={n}")

# [3] A genuine solver switch in one process re-announces.
switch = ("* switch\nr1 1 0 1k\nr2 2 1 1k\nv1 2 0 1\n"
          ".control\nop\noption klu\nop\n.endc\n.end\n")
out = run_deck(switch)
check("[3] sparse->klu switch re-announces (both lines present)",
      SPARSE in out and KLU in out, f"sparse={SPARSE in out} klu={KLU in out}")

# [4] KLU detection preserved: a KLU analysis prints the KLU line at least once
#     (the HB / benchmark suites grep for exactly this).
opklu = "* op klu\nr1 1 0 1k\nv1 1 0 1\n.options klu\n.control\nop\n.endc\n.end\n"
out = run_deck(opklu)
check("[4] KLU analysis still announces KLU (HB/benchmark detection)", KLU in out,
      f"present={KLU in out}")

print(f"\n{passed}/{checks} checks passed")
if passed == checks:
    print("ALL PASS")
raise SystemExit(0 if passed == checks else 1)
