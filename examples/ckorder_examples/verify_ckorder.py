#!/usr/bin/env python3
"""verify_ckorder.py -- Enhancement-879: loadstate restores a checkpoint taken
with any maxord, and a mismatch names the order.

F6 of the transient stress campaign of 2026-10-12.

loadstate sets the circuit up before CKTdoJob copies the task's options, so
the circuit had the default maxord of 2. The signature compared the saved
maxord with it, and every checkpoint taken with maxord above 2 -- Gear or Adams
at a higher order, dynorder, sdirk -- was refused with "checkpoint does not
match this circuit (equations 4 vs 4, states 2 vs 2)": the two counts that
matched, not the order that did not. The method and maxord are now copied
before the setup, and the message names the order.

Checkpoints need Sparse (Enhancement-131), so every deck pins it.

  [1] gear maxord=3: the checkpoint restores in a fresh process, and v(b) at
      2.5 us is the uninterrupted run's to 1e-6 (the continuation's grid is not
      the uninterrupted one's, F7) (E-875: refused)
  [2] adams maxord=4, and gear maxord=6 with dynorder: the same (E-875: refused)
  [3] sdirk: the same (E-875: refused)
  [4] a checkpoint taken at maxord=3 and loaded into a deck at maxord=2 is
      refused with "maximum order 3 vs 2" in the message
  [5] (control) maxord=2 restores, as before

Exit code 0 = pass.
"""
import os
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from _setup import NG as NGSPICE  # noqa: E402
from _setup import check_both_solvers as _check_both_solvers; _check_both_solvers(__file__)  # noqa: E402

WORK = tempfile.mkdtemp(prefix="ckorder_")
checks = passed = 0


def check(label, ok, detail=""):
    global checks, passed
    checks += 1
    passed += bool(ok)
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  [{detail}]" if detail else ""))


DECK = """* checkpoint across processes
v1 a 0 pulse(0 1 0 1n 1n 1u 2u)
r1 a b 1k
c1 b 0 1n
l1 b c 1u
r2 c 0 50
.option sparse %s
.tran 10n 4u
.control
set numdgt=15
%s
.endc
.end
"""


def run(name, opts, body):
    path = os.path.join(WORK, name + ".cir")
    with open(path, "w") as f:
        f.write(DECK % (opts, body))
    r = subprocess.run([NGSPICE, "-b", path], cwd=WORK, capture_output=True, text=True, timeout=120)
    return r.stdout + r.stderr


def vb(out):
    m = re.search(r"^vbp\s*=\s*(\S+)", out, re.M)
    return float(m.group(1)) if m else None


def roundtrip(tag, opts_save, opts_load=None):
    ck = os.path.join(WORK, tag + ".bin")
    if os.path.exists(ck):
        os.remove(ck)
    run(tag + "_1", opts_save, "stop when time > 1.5u\nrun\nsavestate %s" % ck)
    out = run(tag + "_2", opts_load or opts_save, "loadstate %s\nmeas tran vb find v(b) at=2.5u\nlet vbp = vb\nprint vbp" % ck)
    ref = run(tag + "_3", opts_save, "run\nmeas tran vb find v(b) at=2.5u\nlet vbp = vb\nprint vbp")
    return vb(out), vb(ref), out


def agree(tag, opts):
    a, r, out = roundtrip(tag, opts)
    ok = a is not None and r is not None and abs(a - r) <= 1e-6 * max(abs(r), 1e-12)
    msg = " ".join(l.strip() for l in out.splitlines() if "loadstate" in l)
    return ok, "%s: loaded %s, uninterrupted %s%s" % (opts, a, r, "" if a is not None else " (" + msg[:90] + ")")


r1 = agree("g3", "method=gear maxord=3")
check("[1] gear maxord=3: the checkpoint restores and v(b) at 2.5 us is the uninterrupted run's to 1e-6", r1[0], r1[1])
r2 = [agree("a4", "method=adams maxord=4"), agree("g6d", "method=gear maxord=6 dynorder")]
check("[2] adams maxord=4, and gear maxord=6 with dynorder: the same", all(x[0] for x in r2), "; ".join(x[1] for x in r2))
r3 = agree("sd", "method=sdirk")
check("[3] sdirk: the same", r3[0], r3[1])

a, r, out = roundtrip("mm", "method=gear maxord=3", "method=gear maxord=2")
msg = " ".join(l.strip() for l in out.splitlines() if "loadstate" in l)
check("[4] a maxord=3 checkpoint loaded at maxord=2 is refused, and the message names the order",
      a is None and "maximum order 3 vs 2" in msg, msg[:140])

r5 = agree("g2", "method=gear maxord=2")
check("[5] (control) maxord=2 restores, as before", r5[0], r5[1])

print(f"\n{passed}/{checks} checks passed")
sys.exit(0 if passed == checks else 1)
