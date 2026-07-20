#!/usr/bin/env python3
"""Enhancement-245: two crash fixes in core ngspice command parsers.

Found by argument-fuzzing the `meas` and `altermod` commands; both reproduce on the
shipped binary and both are in STOCK ngspice code (not a recent enhancement). Each
is fixed and this script drives the repro and asserts it now exits gracefully.

  [meas]     frontend/com_measure2.c
             measure_parse_stdParams() split each token on '=' with strtok(); a
             token that is a lone '=' (a stray one in e.g. `meas ... find v(x)
             when v(x)=0.5 = y`) makes strtok return NULL for the name, which was
             then handed to strcasecmp() -> NULL deref (SIGSEGV). Fix: reject a
             NULL name as a clean syntax error.

  [altermod] frontend/spiceif.c (parmlookup)
             `altermod nm c` -- where the second token is a bare device-type letter
             (c/e/i/...) or a digit -- makes com_altermod treat it as another model
             to alter, with no `param=value`, so parmlookup() is called with a NULL
             `param`. The model-parameter loop passed it straight to eq()/strcmp()
             (the instance-parameter loop above already guarded !param) -> NULL
             deref (SIGSEGV). Fix: guard the model loop against a NULL param (and a
             NULL keyword).

See enhancements_doc/Enhancement-245.md.
"""
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from _setup import NG as NGSPICE
from _setup import check_both_solvers as _check_both_solvers
_check_both_solvers(__file__)

checks = passed = 0
def check(label, ok, detail=""):
    global checks, passed
    checks += 1; passed += bool(ok)
    print(f"[{'PASS' if ok else 'FAIL'}] {label}" + (f"  ({detail})" if detail and not ok else ""))

def _is_crash(rc, out):
    return rc < 0 or rc >= 128 or "segmentation" in out.lower() or "assertion failed" in out.lower()

def run_pipe(cmds):
    r = subprocess.run([NGSPICE, "-p"], input=cmds, capture_output=True, text=True,
                       timeout=60, cwd=HERE)
    return r.stdout + r.stderr, r.returncode

# base circuits
open(os.path.join(HERE, "_meas.cir"), "w").write(
    "* meas\nV1 in 0 dc 1 ac 1 sin(0 1 1meg)\nR1 in out 1k\nC1 out 0 1n\n.tran 1u 100u\n.end\n")
open(os.path.join(HERE, "_alt.cir"), "w").write(
    "* alt\nV1 in 0 dc 1\nR1 in out 1k\nM1 out in 0 0 nm w=1u l=1u\n.model nm nmos level=1\n.tran 1u 50u\n.end\n")

MPRE = "source _meas.cir\nrun\n"
APRE = "source _alt.cir\nrun\n"

# ---- [meas] stray '=' in find/when ----
for m in ["meas tran m when v(out)=0.5 = x",
          "meas tran m find v(out) when v(out)=0.5 = val= v(",
          "meas ac m find vdb(out) when vp(out)=-45 = val="]:
    out, rc = run_pipe(MPRE + m + "\nprint \"SURVIVED\"\nquit\n")
    check(f"[meas] stray '=' does not crash: {m[:44]}...", not _is_crash(rc, out) and "SURVIVED" in out, f"rc={rc}")
# valid meas still works (max of a settling RC ~ 0.23 V)
out, rc = run_pipe(MPRE + "meas tran mx max v(out)\nprint mx\nquit\n")
check("[meas] valid `max` measurement still works",
      not _is_crash(rc, out) and "mx" in out and "failed" not in out.lower(), f"rc={rc}")

# ---- [altermod] device-letter / digit second token ----
for x in ["c", "e", "i", "0", "1", "2"]:
    out, rc = run_pipe(APRE + f"altermod nm {x}\nprint \"SURVIVED\"\nquit\n")
    check(f"[altermod] `altermod nm {x}` does not crash", not _is_crash(rc, out) and "SURVIVED" in out, f"rc={rc}")
# valid altermod / alter still work
out, rc = run_pipe(APRE + "altermod nm vto=0.7\nprint \"OK1\"\nquit\n")
check("[altermod] valid `altermod nm vto=0.7` still works", not _is_crash(rc, out) and "OK1" in out, f"rc={rc}")
out, rc = run_pipe(APRE + "alter R1=2k\nprint \"OK2\"\nquit\n")
check("[alter] valid `alter R1=2k` still works", not _is_crash(rc, out) and "OK2" in out, f"rc={rc}")

for f in ("_meas.cir", "_alt.cir"):
    p = os.path.join(HERE, f)
    if os.path.exists(p):
        os.remove(p)

print(f"\n{passed}/{checks} checks passed")
raise SystemExit(0 if passed == checks else 1)
