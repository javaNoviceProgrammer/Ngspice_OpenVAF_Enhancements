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

Enhancement-811 and -812 (F20 and F21 of the 2026-10-08 ngspice + OSDI hunt):
the same class in the output commands, run under macOS Guard Malloc where it
exists (it turns an overrun into a fault at the overrunning access, so a
regression fails every time rather than now and then), plainly elsewhere.
 5-10. E-811: `print` of a vector named by a long instance, node or Verilog-A
    parameter (600 and 3000 characters) -- `com_print` strcpy'd the name into a
    512-byte heap buffer -- in line, column and `print all` form, each name and
    value printed whole.
 11-13. E-812: `display` (`pvec` sprintf'd the name into a 512-byte stack
    buffer, a fortified abort), a noise analysis whose per-device contribution
    is named after a 600-character OSDI instance, and `load` of a raw file
    holding a 600-character name (load lists what it reads through `pvec`).
"""
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from _setup import NG as NGSPICE, VAF

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

# ---- Enhancement-811/812: the output commands, under Guard Malloc ----------
GMALLOC = "/usr/lib/libgmalloc.dylib"
GUARD = sys.platform == "darwin" and os.path.exists(GMALLOC)
print("\nE-811/812: print, display and load of long names"
      + (" (under Guard Malloc)" if GUARD else " (no Guard Malloc here: plain runs)"))


def grun(deck, tag="_name"):
    cir = os.path.join(HERE, f"{tag}.cir")
    open(cir, "w").write(deck)
    env = dict(os.environ)
    if GUARD:
        env["DYLD_INSERT_LIBRARIES"] = GMALLOC
    r = subprocess.run([NGSPICE, "-b", os.path.basename(cir)], capture_output=True,
                       text=True, timeout=300, cwd=HERE, env=env)
    return r.returncode, r.stdout.replace("\r", "\n") + r.stderr


for L in (600, 3000):
    R = "r" + "x" * (L - 1)
    N = "n" + "y" * (L - 1)
    rc, out = grun(f"* print long names\nv1 1 0 2\n{R} 1 0 1k\nr2 {N} 0 1k\nv2 {N} 0 1\n"
                   f".control\nop\nprint @{R}[i]\nprint v({N})\nprint col v({N}) v(1)\n"
                   f"print all\n.endc\n.end\n")
    check(f"[E-811] print @<{L}-char instance>[i]: the whole name and its value (was a heap overrun)",
          rc == 0 and re.search(rf"^@{R}\[i\] = 2\.000000e-03$", out, re.M) is not None,
          f"rc={rc}")
    check(f"[E-811] print v(<{L}-char node>): the whole name and its value",
          rc == 0 and f"v({N}) = 1.000000e+00" in out, f"rc={rc}")
    check(f"[E-811] print col and print all with the {L}-char names run to the end",
          rc == 0 and out.count(f"{N} = 1.000000e+00") >= 1, f"rc={rc}")

# a Verilog-A parameter whose NAME is long (the accessor @lpm[<name>])
PNAME = "p" + "q" * 599
va = os.path.join(HERE, "_name_lp.va")
open(va, "w").write('`include "disciplines.vams"\nmodule lp(a, b);\ninout a, b; electrical a, b;\n'
                    f"parameter real {PNAME} = 1e-3;\nanalog I(a,b) <+ {PNAME}*V(a,b);\nendmodule\n")
osdi = os.path.join(HERE, "_name_lp.osdi")
r = subprocess.run([VAF, va, "-o", osdi], capture_output=True, text=True)
check("[E-811] a module with a 600-char parameter name compiles", r.returncode == 0,
      (r.stdout + r.stderr)[-200:])
if r.returncode == 0:
    rc, out = grun(f"* long parameter name\n.control\npre_osdi {os.path.basename(osdi)}\n.endc\n"
                   f"v1 1 0 2\nn1 1 0 lpm\n.model lpm lp {PNAME}=2m\n.control\nop\n"
                   f"print @lpm[{PNAME}] i(v1)\n.endc\n.end\n")
    check("[E-811] print @lpm[<600-char parameter>]: the whole name and 2m",
          rc == 0 and f"@lpm[{PNAME}] = 2.000000e-03" in out and "i(v1) = -4.00000e-03" in out,
          f"rc={rc}")

N = "n" + "y" * 599
rc, out = grun(f"* display a long node\nv1 {N} 0 2\nr1 {N} 0 1k\n.control\nop\ndisplay\n.endc\n.end\n")
check("[E-812] display with a 600-char node: the whole name listed (was a fortified abort)",
      rc == 0 and re.search(rf"^    {N}\s*: voltage, real, 1 long", out, re.M) is not None, f"rc={rc}")

va = os.path.join(HERE, "_name_nr.va")
open(va, "w").write('`include "disciplines.vams"\nmodule nr(a, b);\ninout a, b; electrical a, b;\n'
                    "parameter real r = 1k;\nanalog begin\n  I(a,b) <+ V(a,b)/r;\n"
                    '  I(a,b) <+ white_noise(4*1.380649e-23*$temperature/r, "thermal");\nend\nendmodule\n')
osdi = os.path.join(HERE, "_name_nr.osdi")
r = subprocess.run([VAF, va, "-o", osdi], capture_output=True, text=True)
INST = "n" + "z" * 599
if r.returncode == 0:
    rc, out = grun(f"* noise contribution of a long instance\n.control\npre_osdi {os.path.basename(osdi)}\n.endc\n"
                   f"v1 1 0 dc 0 ac 1\nr1 1 2 1k\n{INST} 2 0 nrm\n.model nrm nr\n.control\n"
                   f"noise v(2) v1 lin 1 1k 1k 1\nsetplot noise1\ndisplay\n"
                   f"print onoise_{INST}_thermal\n.endc\n.end\n")
    m = re.search(rf"^onoise_{INST}_thermal = (\S+)", out, re.M)
    check("[E-812] noise: display of onoise_<600-char OSDI instance>_thermal, and its value (2.04e-9 V/rtHz)",
          rc == 0 and m is not None and abs(float(m.group(1)) / 2.0357e-9 - 1) < 1e-3, f"rc={rc}")
else:
    check("[E-812] the noisy resistor compiles", False, (r.stdout + r.stderr)[-200:])

raw = os.path.join(HERE, "_name_ld.raw")
rc, out = grun(f"* load a raw file with a long name\nv1 {N} 0 2\nr1 {N} 0 1k\n.control\nop\n"
               f"write {os.path.basename(raw)}\nload {os.path.basename(raw)}\nprint v({N})\n.endc\n.end\n")
check("[E-812] load of a raw file holding a 600-char name lists it and reads it back",
      rc == 0 and f"v({N}) = 2.000000e+00" in out, f"rc={rc}")

for f in ("_name.cir", "_name_lp.va", "_name_lp.osdi", "_name_nr.va", "_name_nr.osdi",
          "_name_ld.raw"):
    p = os.path.join(HERE, f)
    if os.path.exists(p):
        os.remove(p)

print(f"\n{passed} passed, {failed} failed")
raise SystemExit(1 if failed else 0)
