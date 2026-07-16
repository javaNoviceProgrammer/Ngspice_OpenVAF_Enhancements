#!/usr/bin/env python3
"""Enhancement-212: crash-hardening fixes for malformed / degenerate user input.

A static-analysis + argument-fuzzing pass over ngspice found seven reproducible
user-triggerable crashes (SIGSEGV / SIGABRT) in STOCK ngspice code -- all in
user-input handling (command parsers, .op output, netlist recursion), never in
the numerical core. Each is fixed; this script drives every repro and asserts it
now exits gracefully (no signal) instead of crashing, while valid forms still
work. See enhancements_doc/Enhancement-212.md.

The seven fixes:
  [iplot]      breakp.c    : `iplot -w` / `-d` as the trailing token derefed NULL
  [altermod]   device.c    : bare `altermod` -> com_alter_common(NULL) derefed NULL
  [measure]    vectors.c   : `meas ... FIND`/`WHEN` w/o operand -> vec_get(NULL)
  [emptyop]    dotcards.c  : empty / all-commented deck + .op -> assert/deref NULL
  [klupz]      cktpzset.c  : KLU pole-zero bsearch-miss guard derefed anyway
  [increcurse] inpcom.c    : self/circular .include recursed to stack overflow
  [funcrecurse]inpcom.c    : `.func f(x)={f(x)}` expanded to stack overflow

Run under BOTH linear solvers. Every deck starts with a title line.
"""
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from _setup import NG as NGSPICE
from _setup import check_both_solvers as _check_both_solvers
_check_both_solvers(__file__)   # verify under BOTH KLU and Sparse solvers

checks = passed = 0
def check(label, ok, detail=""):
    global checks, passed
    checks += 1; passed += bool(ok)
    print(f"[{'PASS' if ok else 'FAIL'}] {label}" + (f"  ({detail})" if detail and not ok else ""))

def _is_crash(rc, out):
    # subprocess returns a NEGATIVE code when the child is killed by a signal
    # (SIGSEGV -> -11, SIGABRT -> -6); >=128 covers shell-wrapped exits.
    return rc < 0 or rc >= 128 or "segmentation" in out.lower() or \
        ("abort" in out.lower() and "assertion" in out.lower())

def run_batch(deck, name):
    p = os.path.join(HERE, name)
    with open(p, "w") as f:
        f.write(deck)
    try:
        r = subprocess.run([NGSPICE, "-b", p], capture_output=True, text=True,
                           timeout=60, cwd=HERE)
    finally:
        if os.path.exists(p):
            os.remove(p)
    return r.stdout + r.stderr, r.returncode

def run_interactive(cmds):
    """Drive ngspice in interactive pipe mode (-p): needed for commands that
    check_batch() blocks in batch mode (e.g. iplot)."""
    r = subprocess.run([NGSPICE, "-p"], input=cmds, capture_output=True,
                       text=True, timeout=60, cwd=HERE)
    return r.stdout + r.stderr, r.returncode

def val(out, node):
    m = re.search(rf"{re.escape(node)}\s*=\s*([-\d.eE+]+)", out)
    return float(m.group(1)) if m else None

# base deck used as an interactive circuit source
BASE = "* base\nv1 1 0 1\nr1 1 0 1k\nc1 1 0 1n\n.end\n"
with open(os.path.join(HERE, "_base.cir"), "w") as f:
    f.write(BASE)

# ---- [iplot] trailing -w / -d flag (interactive; check_batch blocks batch) ----
for flag in ("-w", "-d"):
    out, rc = run_interactive(
        f'source _base.cir\ntran 1u 5u\niplot {flag}\nprint "SURVIVED"\nquit\n')
    check(f"[iplot] `iplot {flag}` trailing flag does not crash",
          not _is_crash(rc, out), f"rc={rc}")
# valid two-token form still works
out, rc = run_interactive(
    'source _base.cir\ntran 1u 5u\niplot -w 3 v(1)\nprint "IPLOT_OK"\nquit\n')
check("[iplot] valid `iplot -w 3 v(1)` still works",
      not _is_crash(rc, out) and "IPLOT_OK" in out, f"rc={rc}")

# ---- [altermod] bare altermod (executes inside a batch .control block) ----
out, rc = run_batch("""* E-212 bare altermod
v1 1 0 1
r1 1 0 1k
.control
op
altermod
.endc
.end
""", "_am.cir")
check("[altermod] bare `altermod` reports an error instead of crashing",
      not _is_crash(rc, out) and "no device" in out.lower(), f"rc={rc}")
# valid altermod still works
out, rc = run_batch("""* E-212 valid altermod
.model nm nmos
m1 d g s b nm
v1 d 0 1
.control
op
altermod nm vto=0.7
.endc
.end
""", "_am2.cir")
check("[altermod] valid `altermod nm vto=0.7` still works",
      not _is_crash(rc, out), f"rc={rc}")

# ---- [measure] FIND/WHEN with a missing operand -> vec_get(NULL) ----
for spec in ("FIND", "WHEN", "FIND v(1)"):
    out, rc = run_batch(f"""* E-212 meas {spec}
v1 1 0 sin(0 1 1k)
r1 1 0 1k
.control
tran 1u 20u
meas tran x {spec}
.endc
.end
""", "_meas.cir")
    check(f"[measure] `meas tran x {spec}` (bad syntax) does not crash",
          not _is_crash(rc, out), f"rc={rc}")
# valid measure still works
out, rc = run_batch("""* E-212 valid measure
v1 1 0 sin(0 1 1k)
r1 1 0 1k
.control
tran 1u 1m
meas tran vmax MAX v(1)
.endc
.end
""", "_meas2.cir")
vmax = val(out, "vmax")
check("[measure] valid `meas tran vmax MAX v(1)` still returns ~1.0",
      not _is_crash(rc, out) and vmax is not None and abs(vmax - 1.0) < 0.05,
      f"rc={rc} vmax={vmax}")

# ---- [emptyop] empty / all-commented deck + .op ----
out, rc = run_batch("* E-212 empty op\n.op\n.end\n", "_empty.cir")
check("[emptyop] empty circuit + .op does not abort",
      not _is_crash(rc, out), f"rc={rc}")
out, rc = run_batch("* E-212 all commented\n*r1 1 0 1k\n.op\n.end\n", "_comm.cir")
check("[emptyop] all-commented deck + .op does not abort",
      not _is_crash(rc, out), f"rc={rc}")
# valid .op still prints the node table
out, rc = run_batch("* E-212 valid op\nv1 1 0 2\nr1 1 0 1k\n.op\n.end\n", "_op.cir")
check("[emptyop] a normal .op still solves (v(1) = 2)",
      not _is_crash(rc, out) and "Voltage" in out, f"rc={rc}")

# ---- [klupz] KLU pole-zero setup path runs without crashing ----
out, rc = run_batch("""* E-212 klu pz
.options klu
r1 1 2 1k
r2 2 3 1k
r3 3 0 1k
c1 2 0 1n
c2 3 0 1n
v1 1 0 1
.control
pz 1 0 3 0 vol pz
.endc
.end
""", "_pz.cir")
check("[klupz] KLU `.pz` setup runs without crashing",
      not _is_crash(rc, out) and "not found in BindStruct" not in out, f"rc={rc}")

# ---- [increcurse] self-including and circular .include ----
with open(os.path.join(HERE, "_self.cir"), "w") as f:
    f.write("* self include\n.include _self.cir\nr1 1 0 1k\nv1 1 0 1\n.op\n.end\n")
try:
    r = subprocess.run([NGSPICE, "-b", "_self.cir"], capture_output=True,
                       text=True, timeout=60, cwd=HERE)
    out, rc = r.stdout + r.stderr, r.returncode
finally:
    for fn in ("_self.cir",):
        fp = os.path.join(HERE, fn)
        if os.path.exists(fp):
            os.remove(fp)
check("[increcurse] self-including .include errors instead of stack-overflow",
      not _is_crash(rc, out) and "too deep" in out.lower(), f"rc={rc}")

# a legitimate nested include chain must still work
with open(os.path.join(HERE, "_leaf.cir"), "w") as f:
    f.write("r2 2 0 1k\n")
with open(os.path.join(HERE, "_mid.cir"), "w") as f:
    f.write("r1 1 2 1k\n.include _leaf.cir\n")
try:
    r = subprocess.run([NGSPICE, "-b", "-o", os.devnull, "-"],
                       input="* legit nested include\nv1 1 0 1\n.include _mid.cir\n.op\n.end\n",
                       capture_output=True, text=True, timeout=60, cwd=HERE)
    out, rc = r.stdout + r.stderr, r.returncode
finally:
    for fn in ("_leaf.cir", "_mid.cir"):
        fp = os.path.join(HERE, fn)
        if os.path.exists(fp):
            os.remove(fp)
check("[increcurse] a legitimate 2-level nested .include still works",
      not _is_crash(rc, out), f"rc={rc}")

# ---- [funcrecurse] self-referential .func ----
out, rc = run_batch("""* E-212 recursive func
.func f(x)={f(x)}
v1 1 0 {f(1)}
r1 1 0 1k
.op
.end
""", "_rf.cir")
check("[funcrecurse] recursive `.func f(x)={f(x)}` errors instead of stack-overflow",
      not _is_crash(rc, out) and "too deep" in out.lower(), f"rc={rc}")
# a legitimate .func must still expand to the right value
out, rc = run_batch("""* E-212 valid func
.func sq(x)={x*x}
v1 1 0 {sq(4)}
r1 1 0 1k
.control
op
print v(1)
.endc
.end
""", "_vf.cir")
v1 = val(out, "v(1)")
check("[funcrecurse] a valid `.func sq(x)={x*x}` still expands (sq(4) = 16)",
      not _is_crash(rc, out) and v1 is not None and abs(v1 - 16.0) < 1e-6,
      f"rc={rc} v(1)={v1}")

# cleanup base
_bp = os.path.join(HERE, "_base.cir")
if os.path.exists(_bp):
    os.remove(_bp)

print(f"\n{passed}/{checks} checks passed")
raise SystemExit(0 if passed == checks else 1)
