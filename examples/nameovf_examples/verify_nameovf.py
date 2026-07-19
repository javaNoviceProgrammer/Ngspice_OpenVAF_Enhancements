#!/usr/bin/env python3
"""Enhancement-237: fix stack-buffer overflows on long vector/node names.

The SPICE2-compatibility rewrites for `.print`/`.plot`/`.four` output tokens, and
the vector-name helper they feed, all copied a (user-controlled, unbounded)
vector or node name into a fixed `BSIZE_SP` (512-byte) stack buffer:

  * `fixem()`  (frontend/dotcards.c) -- rewrites a differential form like
    `v(a,b)` into `v(a)-v(b)` (and the vm/vp/vi/vr/vdb variants) with
    `sprintf(buf, "v(%s)-v(%s)", a, b)` into `char buf[BSIZE_SP]`;
  * `gettoks()` (frontend/dotcards.c) -- rewrites `i(x)` into `x#branch` with
    `sprintf(buf, "%s#branch", x)` into `char buf[513]`;
  * `vec_basename()` (frontend/vectors.c) -- `strcpy(buf, v->v_name)` into
    `char buf[BSIZE_SP]`, reached by `.print`, `fft`, `spec`, `linearize`, ...

A `.print`/`.plot`/`.four` output token whose node/branch name(s) exceed the
buffer overran the stack; macOS aborts with a stack-smashing trap (SIGABRT/
SIGTRAP), and elsewhere it is plain stack corruption. E-237 sizes each scratch
buffer to its input (`fixem`/`vec_basename` allocate to fit; `gettoks` uses
`tprintf`), and every write in `fixem` is additionally a bounded `snprintf`, so
long names are handled instead of overflowing -- with no truncation, so a valid
long differential still computes correctly.

Checks (batch mode, `-b`). A crash shows up as a NEGATIVE return code (killed by
signal); a clean run is 0 (or 1 for a benign "no such vector" error).
 1. `.print tran v(<400>,<400>)` (nonexistent nodes) does not crash;
 2. a VALID long differential `v(A,B)` with v(A)=2, v(B)=1 runs (exit 0) and
    prints v(A)-v(B) = 1.0 exactly -- proving the fix does not truncate;
 3. `.four ... i(<600-char>)` (the gettoks path) does not crash;
 4. the ordinary short form `v(1,2)` still rewrites to v(1)-v(2) correctly.

Line 1 of every SPICE deck is the title (ignored).
"""
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from _setup import NG as NGSPICE

passed = failed = 0


def check(label, ok, detail=""):
    global passed, failed
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  {detail}" if detail else ""))
    if ok:
        passed += 1
    else:
        failed += 1


def run(deck):
    cir = os.path.join(HERE, "_name.cir")
    open(cir, "w").write(deck)
    r = subprocess.run([NGSPICE, "-b", cir], capture_output=True, text=True,
                       timeout=120)
    # subprocess reports a signal death as a negative returncode
    return r.returncode, r.stdout.replace("\r", "\n") + r.stderr


# 1: long differential, nonexistent nodes -> must not crash (was signal death)
A, B = "n" + "a" * 400, "n" + "b" * 400
rc, _ = run(f"* fixem long nonexistent\nv1 1 0 dc 1\nr1 1 0 1k\n"
            f".tran 1n 3n\n.print tran v({A},{B})\n.end\n")
check("long differential v(a,b), nonexistent nodes, does not crash (was SIGABRT)",
      rc >= 0, f"rc={rc}")

# 2: VALID long differential -> exit 0 AND correct value (non-truncation)
A, B = "n" + "a" * 300, "n" + "b" * 300
rc, out = run(f"* fixem long VALID differential\nv1 {A} 0 dc 2\nv2 {B} 0 dc 1\n"
              f"r1 {A} 0 1k\nr2 {B} 0 1k\n.tran 1n 3n\n"
              f".print tran v({A},{B})\n.end\n")
m = re.search(r"^0[ \t]+[-\d.eE+]+[ \t]+([-\d.eE+]+)", out, re.M)
val = float(m.group(1)) if m else None
check("valid long differential runs and prints v(A)-v(B)=1.0 (no truncation)",
      rc == 0 and val is not None and abs(val - 1.0) < 1e-6,
      f"rc={rc} diff={val}")

# 3: gettoks i(<long>) via .four -> must not crash
Q = "q" * 600
rc, _ = run(f"* gettoks i(long) via .four\nv1 1 0 dc 1 sin(0 1 1k)\nr1 1 0 1k\n"
            f".tran 1u 1m\n.four 1k i({Q})\n.end\n")
check("long i(x) branch name via .four does not crash (gettoks; was SIGABRT)",
      rc >= 0, f"rc={rc}")

# 4: ordinary short differential still correct
rc, out = run("* short differential control\nv1 1 0 dc 3\nv2 2 0 dc 1\n"
              "r1 1 0 1k\nr2 2 0 1k\n.tran 1n 3n\n.print tran v(1,2)\n.end\n")
hdr = "v(1)-v(2)" in out
m = re.search(r"^0[ \t]+[-\d.eE+]+[ \t]+([-\d.eE+]+)", out, re.M)
val = float(m.group(1)) if m else None
check("short v(1,2) still rewrites to v(1)-v(2)=2.0 correctly",
      rc == 0 and hdr and val is not None and abs(val - 2.0) < 1e-6,
      f"hdr={hdr} diff={val}")

p = os.path.join(HERE, "_name.cir")
if os.path.exists(p):
    os.remove(p)

print(f"\n{passed} passed, {failed} failed")
raise SystemExit(1 if failed else 0)
