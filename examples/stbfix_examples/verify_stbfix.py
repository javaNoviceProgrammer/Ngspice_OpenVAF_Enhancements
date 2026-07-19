#!/usr/bin/env python3
"""Enhancement-235: fix a latent use-after-free in the `stb` command (E-198).

`com_stb` looked its voltage probe up with `INPretrieve(&name, symtab)`, which
REPLACES the pointer with the interned symbol-table string -- the same memory the
voltage source's own name field points at -- and does NOT free the old copy. The
subsequent `tfree(name)` therefore double-freed the source's live name (and the
symbol-table entry). It never bit in practice because `stb` runs once with no
re-setup, but it is a real corruption, and it is the identical bug the E-234
`loadpull` work uncovered (there it DID bite, via the sweep's per-point
re-setups).

The fix drops `INPretrieve` (top-level device names need no subcircuit
translation -- `findInstance` does its own name match) and lowercases a private
copy instead (ngspice stores instance names lowercased). That frees only our own
copy AND, as a bonus, makes the probe lookup case-insensitive: `stb Vprobe ...`
used to fail with "no such probe source" and now resolves. The now-unused complex
helper `stbsub` was removed to keep the build warning-free.

Checks (drive ngspice in pipe mode, -p):
 1. a MIXED-CASE probe name (`stb Vprobe Iprobe`) now resolves and reports a loop
    gain -- on the pre-fix binary it failed "no such probe source 'Vprobe'";
 2. the loop gain is still correct: a gain-1e5 buffer loop -> ~100 dB DC loop gain;
 3. running `stb` many times in a row stays stable (the use-after-free stress).

Every SPICE deck starts with a title line (SPICE treats line 1 as the title).
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


DECK = """* stb loop-gain test (gain-1e5 buffer feedback)
Vin in 0 dc 0 ac 0
E1 amp 0 in fb 1e5
Rout amp aa 100
Vprobe aa fb dc 0 ac 0
Iprobe 0 fb dc 0 ac 0
Rload fb 0 10k
.end
"""


def run(script):
    cir = os.path.join(HERE, "_stb.cir")
    open(cir, "w").write(DECK)
    full = f"source {cir}\n" + script + "\nquit\n"
    r = subprocess.run([NGSPICE, "-p"], input=full, capture_output=True,
                       text=True, timeout=120)
    return r.stdout.replace("\r", "\n") + r.stderr


# 1 + 2: mixed-case probe resolves AND the loop gain is right
out = run("stb Vprobe Iprobe dec 5 1 1meg")
m = re.search(r"DC loop gain\s*:\s*([-\d.]+)\s*dB", out)
gain = float(m.group(1)) if m else None
check("mixed-case `stb Vprobe Iprobe` resolves (was 'no such probe source')",
      "no such probe source" not in out and gain is not None,
      "resolved" if gain is not None else out[-200:])
check("loop gain still correct (~100 dB for the gain-1e5 buffer loop)",
      gain is not None and abs(gain - 100.0) < 1.0,
      f"DC loop gain = {gain} dB" if gain is not None else "no loop gain")

# 3: running stb many times stays stable (use-after-free stress)
loop = ("let i=0\ndowhile i < 60\n  stb vprobe iprobe dec 3 1 1meg\n"
        "  i = i + 1\nend\necho STB_STABLE_60")
out = run(loop)
check("60 repeated `stb` runs stay stable (no crash / corruption)",
      "STB_STABLE_60" in out)

# tidy
p = os.path.join(HERE, "_stb.cir")
if os.path.exists(p):
    os.remove(p)

print(f"\n{passed} passed, {failed} failed")
raise SystemExit(1 if failed else 0)
