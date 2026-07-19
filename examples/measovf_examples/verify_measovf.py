#!/usr/bin/env python3
"""Enhancement-236: fix a stack-buffer overflow in the `.meas` command.

`get_measure2()` (com_measure2.c) formatted every measurement result line with
`sprintf(out_line, "%-20s=  ...", mName, ...)` into the caller's fixed `char
out_line[1000]` (measure.c). `mName` is the measurement NAME token, taken
verbatim from the `.meas <analysis> <name> ...` card via `cp_unquote` -- an
unbounded user string. A `.meas` name longer than ~1000 characters therefore
overran the stack buffer; macOS aborts with a stack-smashing SIGABRT (exit 134),
and on other platforms it is a straight stack corruption.

E-225 had already hardened the sibling `errbuf[100]` in this same file to
snprintf, but missed `out_line`. E-236 threads the buffer size through
get_measure2() and converts all ten `sprintf(out_line, ...)` sites to
`snprintf(out_line, max_out_line, ...)`, so any combination of long fields is
safely truncated instead of overflowing.

Checks (batch mode, -b, since `.meas` is a dot-card evaluated after analysis):
 1. a `.meas` statement with a ~4000-character NAME no longer crashes (exit 0;
    pre-fix it aborted with signal -> exit 134/139);
 2. normal measurements still produce the correct numbers (regression guard):
    MAX = 1.0, AVG = 0.6, and a 0.1->0.9 rise time of 0.8 ns.

Every SPICE deck's first line is the title (SPICE ignores line 1).
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
    cir = os.path.join(HERE, "_meas.cir")
    open(cir, "w").write(deck)
    r = subprocess.run([NGSPICE, "-b", cir], capture_output=True, text=True,
                       timeout=120)
    return r.returncode, r.stdout.replace("\r", "\n") + r.stderr


STIM = ("v1 1 0 dc 0 pulse(0 1 0 1n 1n 5n 10n)\n"
        "r1 1 0 1k\n.tran 0.1n 20n\n")

# 1: a ~4000-char measurement name must not overflow out_line[1000]
longname = "m" + "a" * 4000
rc, out = run(f"* meas long-name (overflow repro)\n{STIM}"
              f".meas tran {longname} MAX v(1) FROM=0 TO=20n\n.end\n")
check("~4000-char .meas name does not crash (was stack-smash SIGABRT / exit 134)",
      rc == 0, f"exit={rc}")

# 2: normal measurements still correct
rc, out = run("* meas normal sanity\n" + STIM +
              ".meas tran vmax MAX v(1) FROM=0 TO=20n\n"
              ".meas tran vavg AVG v(1) FROM=0 TO=20n\n"
              ".meas tran trise TRIG v(1) VAL=0.1 RISE=1 "
              "TARG v(1) VAL=0.9 RISE=1\n.end\n")


def meas(name):
    m = re.search(name + r"\s*=\s*([-\d.eE+]+)", out)
    return float(m.group(1)) if m else None


vmax, vavg, trise = meas("vmax"), meas("vavg"), meas("trise")
ok = (vmax is not None and abs(vmax - 1.0) < 1e-6 and
      vavg is not None and abs(vavg - 0.6) < 1e-3 and
      trise is not None and abs(trise - 0.8e-9) < 1e-11)
check("normal measurements still correct (MAX=1.0, AVG=0.6, rise=0.8ns)", ok,
      f"vmax={vmax} vavg={vavg} trise={trise}")

# tidy
p = os.path.join(HERE, "_meas.cir")
if os.path.exists(p):
    os.remove(p)

print(f"\n{passed} passed, {failed} failed")
raise SystemExit(1 if failed else 0)
