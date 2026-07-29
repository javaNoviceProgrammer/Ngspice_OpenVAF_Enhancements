#!/usr/bin/env python3
"""Enhancement-365: `pz` left every device's matrix bindings dangling, so a
following `hb` returned a WRONG answer (and read freed memory).

FOUND BY sequence fuzzing: the netlist was held fixed and valid, and the ORDER
of analyses was fuzzed instead. Every previous campaign in this project fuzzed
the input -- netlists, model cards, commands, expressions, rawfiles, .snp, the
OSDI loader -- and each input runs in a fresh process, so none of them can reach
a bug that lives in what one analysis leaves behind for the next. (Enhancement-360
was the same shape: a second Verilog-A model silenced the first in `.disto`.)

THE BUG. `CKTpzSetup` does

    NIdestroy(ckt);        /* frees ckt->CKTmatrix ... */
    NIinit(ckt);           /* ... and builds a DIFFERENT one */

while leaving `CKTisSetup` asserted. Every device's cached matrix-element
pointer, bound by `CKTsetup`, now points into the freed matrix. `com_hb` then
guarded its setup with

    if (ckt->CKTmatrix == NULL || SMPmatSize(ckt->CKTmatrix) <= 0)  /* CKTsetup */

which asks "is there a matrix?" -- and after a `pz` there is a perfectly good,
non-empty one. So `CKTsetup` was skipped and `CKTload` read the stale pointers:
an ASan heap-use-after-free in `VSRCload`, and on an ordinary build a silently
WRONG harmonic-balance result.

WHY THIS FILE CAN TEST IT WITHOUT A SANITIZER. The consequence is observable as
a number: `hb` after `pz` must equal `hb` on its own, because `pz` does not
change the circuit. Before the fix the DC term differed by ~2.5 % (0.2500 vs the
correct 0.2439 -- the diode's stamp was missing from the garbage matrix). That
inequality is what check [1] pins.

SCOPE, measured rather than assumed. Only this pair was affected: `pz` followed
by op/dc/ac/tran/noise/disto/tf/sp/pss is clean, and `hb` after any other
analysis is clean. `portnum` matters only because it lets `hb` run far enough to
load the circuit.

THE FIX. `pz` now records that it invalidated the bindings (`CKTbindStale`), and
`com_hb` honours it with a BALANCED `CKTunsetup()`/`CKTsetup()` pair -- a bare
`CKTsetup()` would return `E_NOCHANGE` because `CKTisSetup` is still 1, and
calling it without the unsetup would re-run `DEVsetup` on already-setup devices
and double-allocate their internal nodes. `CKTsetup` clears the flag, since a
successful setup is exactly what makes the bindings valid again.

The sequence fuzzer that found this is in `fuzz/` next to this file. It is NOT
run by the regression (it wants a sanitizer build to be worth anything).
"""
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from _setup import NG as NGSPICE  # noqa: E402

checks = passed = 0


def check(label, ok, detail=""):
    global checks, passed
    checks += 1
    passed += bool(ok)
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  [{detail}]" if detail else ""))


NET = """pz/hb binding test
V1 in 0 dc 0.5 ac 1 portnum 1 z0 50
R1 in mid 1k
R2 mid 0 1k
C1 mid 0 1n
D1 mid 0 dm
.model dm d(is=1e-14 n=1 cjo=1p)
"""


def run(ctl, tag, timeout=180):
    p = os.path.join(HERE, "_pz_%s.cir" % tag)
    with open(p, "w") as f:
        f.write(NET + ".control\noption noacct\nset numdgt=10\n" + ctl + "\n.endc\n.end\n")
    r = subprocess.run([NGSPICE, "-b", os.path.basename(p)], cwd=HERE, capture_output=True,
                       text=True, timeout=timeout, errors="replace")
    return r.returncode, r.stdout + r.stderr


NUM = r"[-+0-9.eE]+"


def harmonics(out):
    """`print v(mid)` after `hb` emits  index <tab> re, <tab> im  -- there is no
    frequency column, unlike the sweep analyses."""
    vals = []
    for m in re.finditer(r"^\s*\d+\s+(%s),\s*(%s)" % (NUM, NUM), out or "", re.M):
        vals.append((float(m.group(1)), float(m.group(2))))
    return vals


def main():
    # [1] THE bug: hb after pz must equal hb alone. pz does not change the
    #     circuit, so any difference is the stale-binding corruption.
    _, alone = run("hb 1meg 3\nprint v(mid)", "a")
    _, after = run("pz in 0 mid 0 vol pz\nhb 1meg 3\nprint v(mid)", "b")
    ha, hb_ = harmonics(alone), harmonics(after)
    if not ha or not hb_:
        check("hb after pz equals hb alone", False,
              "no spectrum (alone=%d after=%d)" % (len(ha), len(hb_)))
    elif len(ha) != len(hb_):
        check("hb after pz equals hb alone", False, "length %d vs %d" % (len(ha), len(hb_)))
    else:
        scale = max(max(abs(r) for r, _ in ha), 1e-30)
        worst = max(max(abs(a - b), abs(c - d)) for (a, c), (b, d) in zip(ha, hb_)) / scale
        check("hb after pz equals hb alone", worst < 1e-9,
              "max dev %.2e of full scale" % worst)

    # [2] pz itself is untouched by the fix
    _, p1 = run("pz in 0 mid 0 vol pz\nprint all", "c")
    m = re.search(r"^all\s*=\s*(%s)" % NUM, p1, re.M)
    pole = float(m.group(1)) if m else None
    # R1||R2 = 500 with C1 = 1n -> pole at -1/(500*1n) = -2e6 rad/s
    check("pz still reports the correct pole", pole is not None and abs(pole + 2e6) < 2e6 * 0.01,
          ("%.6e" % pole) if pole is not None else "no pole")

    # [3] the repeat case the fuzzer also produced: pz then hb twice
    rc, out = run("pz in 0 mid 0 vol pz\nhb 1meg 3\nhb 1meg 3\nprint v(mid)", "d")
    h2 = harmonics(out)
    check("pz then hb twice still matches", bool(h2) and bool(ha) and len(h2) >= len(ha) and
          abs(h2[0][0] - ha[0][0]) < max(abs(ha[0][0]), 1e-30) * 1e-9,
          "dc %.6e vs %.6e" % (h2[0][0], ha[0][0]) if (h2 and ha) else "no data")

    # [4] the analyses that were always fine must stay fine after pz
    bad = []
    for name, ctl in (("op", "op\nprint v(mid)"),
                      ("ac", "ac dec 5 1e3 1e6\nprint vdb(mid)[3]"),
                      ("tran", "tran 50n 2u\nprint v(mid)[10]")):
        r1, o1 = run(ctl, "e_%s" % name)
        r2, o2 = run("pz in 0 mid 0 vol pz\n" + ctl, "f_%s" % name)
        pat = r"^(?:v\(mid\)|vdb\(mid\))[^=]*=\s*(%s)" % NUM
        v1 = re.findall(pat, o1, re.M)
        v2 = re.findall(pat, o2, re.M)
        if not v1 or v1 != v2:
            bad.append(name)
    check("op/ac/tran after pz are unchanged", not bad,
          "3 analyses identical" if not bad else str(bad))

    for j in os.listdir(HERE):
        if j.startswith("_pz_"):
            os.remove(os.path.join(HERE, j))
    print(f"\n{'ALL PASS' if passed == checks else 'FAILURES'}: {passed}/{checks} passed")
    sys.exit(0 if passed == checks else 1)


main()
