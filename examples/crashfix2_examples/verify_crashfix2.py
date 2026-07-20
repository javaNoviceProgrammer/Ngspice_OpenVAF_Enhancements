#!/usr/bin/env python3
"""Enhancement-244: two user-triggerable crash fixes in recently-added code.

An argument-fuzzing pass over the newer devices/commands found two reproducible
crashes (both reproduce on the shipped binary); each is fixed here and this script
drives the repro and asserts it now exits gracefully (no signal), while valid forms
still work.

  [nport]   spicelib/devices/nport/nportsetup.c
            The native n-port device (E-242) never checked that the instance line
            connected all N+1 nodes the `.model`'s port count claims.  A `.nport`
            file with more ports than the instance wires (or `nports` beyond the
            device maximum) made setup stamp an UNBOUND (-1) node, tripping the
            sparse builder's `Row>=0 && Col>=0` assert (SIGABRT) / out-of-bounds.
            Fix: validate node binding and cap the port count -> clean error.

  [pyplot]  frontend/com_pyplot.c
            `pyplot -hist ...` / `pyplot -contour ...` (E-217/E-218) stripped the
            marker by unlinking and freeing a node of the command's OWN argument
            wordlist.  When the marker was the FIRST word it freed the list HEAD,
            which the command loop then freed again -> use-after-free (SIGSEGV).
            Fix: detect the marker without mutating the caller's list; hand plotit
            a filtered COPY.  (As a bonus, `-hist` as first arg now renders the
            histogram it silently turned into a line plot before.)

See enhancements_doc/Enhancement-244.md.
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
    return rc < 0 or rc >= 128 or "segmentation" in out.lower() or \
        ("assertion failed" in out.lower())

def run_batch(deck, name):
    p = os.path.join(HERE, name)
    open(p, "w").write(deck)
    try:
        r = subprocess.run([NGSPICE, "-b", name], capture_output=True, text=True,
                           timeout=60, cwd=HERE)
    finally:
        if os.path.exists(p):
            os.remove(p)
    return r.stdout + r.stderr, r.returncode

def run_pipe(cmds):
    r = subprocess.run([NGSPICE, "-p"], input=cmds, capture_output=True, text=True,
                       timeout=60, cwd=HERE)
    return r.stdout + r.stderr, r.returncode

# ======================================================================= nport
open(os.path.join(HERE, "two.nport"), "w").write(
    "NPORT 1\nnports 2\nnpoles 0\nd\n 1e-3 -1e-3\n -1e-3 1e-3\ne\n 0 0\n 0 0\n")

# (a) under-bound: 2-port model, instance connects only 2 nodes (needs p1 p2 ref)
out, rc = run_batch(
    "* nport underbind\nV1 a 0 dc 1\nN1 a 0 mod\n.model mod nport(file=\"two.nport\")\n.op\n.end\n",
    "_ub.cir")
check("[nport] under-bound instance -> clean error, no crash", not _is_crash(rc, out),
      f"rc={rc}")
check("[nport] under-bound instance is diagnosed", "connects fewer nodes" in out or
      "fewer" in out.lower(), "no diagnostic")

# (b) port count beyond the device maximum
over = "NPORT 1\nnports 900\nnpoles 0\nd\n" + \
       "".join(" ".join("1e-3" if i == j else "0" for j in range(900)) + "\n" for i in range(900)) + \
       "e\n" + "".join(" ".join("0" for _ in range(900)) + "\n" for _ in range(900))
open(os.path.join(HERE, "over.nport"), "w").write(over)
out, rc = run_batch(
    "* nport overmax\nV1 a 0 dc 1\nN1 a b 0 mod\n.model mod nport(file=\"over.nport\")\n.op\n.end\n",
    "_ov.cir")
check("[nport] port count > device max -> clean error, no crash", not _is_crash(rc, out),
      f"rc={rc}")

# (c) a correctly-bound 2-port still works
out, rc = run_batch(
    "* nport ok\nV1 a 0 dc 1\nRs a p1 1k\nN1 p1 p2 0 mod\n.model mod nport(file=\"two.nport\")\n"
    "Rl p2 0 1k\n.op\n.print v(p1)\n.end\n", "_ok.cir")
check("[nport] correctly-bound 2-port still simulates", not _is_crash(rc, out) and rc == 0,
      f"rc={rc}")
for f in ("two.nport", "over.nport"):
    p = os.path.join(HERE, f)
    if os.path.exists(p):
        os.remove(p)

# ====================================================================== pyplot
base = ("* pyplot base\nV1 in 0 dc 1 sin(0 1 1e6)\nR1 in out 1k\nC1 out 0 1n\n"
        ".tran 1u 100u\n.end\n")
open(os.path.join(HERE, "_pp.cir"), "w").write(base)
# pyplot_python=true makes the render a no-op (no matplotlib needed); the crash was
# in ngspice's C wordlist handling, exercised regardless.
PRE = "source _pp.cir\nrun\nset pyplot_terminal=png\nset pyplot_python=true\n"
for cmd, lbl in [("pyplot -hist v(out)",        "[pyplot] `-hist` as first arg"),
                 ("pyplot -contour v(out) time time", "[pyplot] `-contour` as first arg"),
                 ("pyplot -hist",               "[pyplot] `-hist` alone (no signals)")]:
    out, rc = run_pipe(PRE + cmd + "\nprint \"SURVIVED\"\nquit\n")
    check(f"{lbl} does not crash", not _is_crash(rc, out) and "SURVIVED" in out, f"rc={rc}")

# the -hist-first form now generates a real histogram (plt.hist), not a line plot
for f in ("pyplot.py", "pyplot.data"):
    p = os.path.join(HERE, f)
    if os.path.exists(p):
        os.remove(p)
run_pipe(PRE + "pyplot -hist v(out)\nquit\n")
pyf = os.path.join(HERE, "pyplot.py")
hist_ok = os.path.exists(pyf) and "hist(" in open(pyf).read()
check("[pyplot] `-hist` first arg now renders a histogram (hist(), not plot())", hist_ok)

# valid non-first marker (always worked) still works
out, rc = run_pipe(PRE + "pyplot v(out) -hist\nprint \"OK2\"\nquit\n")
check("[pyplot] `-hist` as trailing arg still works", not _is_crash(rc, out) and "OK2" in out)

for f in ("_pp.cir", "pyplot.py", "pyplot.data", "pyplot.png"):
    p = os.path.join(HERE, f)
    if os.path.exists(p):
        os.remove(p)

print(f"\n{passed}/{checks} checks passed")
raise SystemExit(0 if passed == checks else 1)
