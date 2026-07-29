#!/usr/bin/env python3
"""Enhancement-369: the last site of the E-365/366 stale-binding class.

[E-366](../../enhancements_doc/Enhancement-366.md) fixed two sites and left one
open on purpose, because it could not be closed with another guard: under KLU the
pole-zero block at the end of `VSRCbindCSCComplex` read through a binding that
was NOT NULL but STALE, so a NULL test could not tell it apart from a live one.

THE ASYMMETRY IS THE BUG. `VSRCbindCSC` assigns the binding only INSIDE

    if (here->VSRCibrIbrPtr) { ... here->VSRCibrIbrBinding = matched ; ... }

and `VSRCibrIbrPtr` is allocated only by a POLE-ZERO analysis. So on any later
analysis that test is false and the binding keeps its previous value -- pointing
into the BindStruct that SMPdestroy() freed when the pz matrix went away. Both
consumers (`VSRCbindCSCComplex` and `VSRCbindCSCComplexToReal`) then dereference
it, because THEIR guard is `VSRCbranch != 0` rather than "was this binding
re-established for THIS matrix".

The fix is to clear the binding before the gate, so a stale value can never
survive a matrix rebuild. ASan on `option klu ; pz ; ac`:

    heap-use-after-free READ of size 8 in VSRCbindCSCComplex vsrcbindCSC.c
      freed by      SMPdestroy klusmp.c
      reallocated by SMPconvertCOOtoCSC klusmp.c

WHAT THIS FILE CAN AND CANNOT SEE -- stated plainly, because it matters.

The pre-fix binary PASSES every behavioural check below. The freed BindStruct
entry still held the right CSC_Complex pointer, so the use-after-free read
plausible values and the numbers came out correct -- verified deliberately,
including on a 40-node ladder with a `tran` between the `pz` and the `ac` to
churn the heap. So this is a MEMORY-SAFETY fix, not a wrong-answer fix, and the
checks below are a behavioural regression guard rather than a reproducer.

The defect itself is only observable under a sanitizer, so the last check runs
the deck under one when NGSPICE_ASAN points at an ASan build, and SKIPS (loudly)
otherwise. That is the check that actually fails before the fix.

The SPARSE rows are controls: they were never affected and must stay identical,
which is what shows the fix did not disturb the default solver.
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


NET = """klu binding lifecycle
V1 in 0 dc 0.5 ac 1 portnum 1 z0 50
V2 out 0 dc 0 ac 0 portnum 2 z0 50
Rs in mid 1k
Rl mid out 1k
C1 mid 0 1n
"""
NUM = r"[-+0-9.eE]+"
PZ = "pz in 0 mid 0 vol pz\n"


def run(ctl, tag, timeout=180):
    p = os.path.join(HERE, "_kb_%s.cir" % tag)
    with open(p, "w") as f:
        f.write(NET + ".control\noption noacct\nset numdgt=10\n" + ctl + "\n.endc\n.end\n")
    r = subprocess.run([NGSPICE, "-b", os.path.basename(p)], cwd=HERE, capture_output=True,
                       text=True, timeout=timeout, errors="replace")
    return r.stdout + r.stderr


def nums(out, pat):
    return [float(m.group(1)) for m in re.finditer(pat, out or "", re.M)]


def close(a, b, tol=1e-9):
    return (bool(a) and len(a) == len(b)
            and all(abs(x - y) <= max(abs(x), abs(y), 1e-30) * tol for x, y in zip(a, b)))


# (label, analysis, how to read the result back)
CASES = [
    ("ac", "ac dec 3 1e6 1e8\nprint vdb(mid)", r"^\s*\d+\s+\S+\s+(%s)\s*$" % NUM),
    ("sp", "sp lin 3 1e6 1e8\nprint S_1_1", r"^\s*\d+\s+\S+\s+(%s)," % NUM),
]


def main():
    for name, ctl, pat in CASES:
        # [1] under KLU, `pz` then the analysis must equal the analysis alone.
        #     `pz` only reads the circuit, so it cannot legitimately change it.
        alone = nums(run("option klu\n" + ctl, "a_%s" % name), pat)
        after = nums(run("option klu\n" + PZ + ctl, "b_%s" % name), pat)
        check("KLU: %s after pz == %s alone" % (name, name), close(alone, after),
              "%d pts" % len(alone) if close(alone, after)
              else "alone=%d after=%d" % (len(alone), len(after)))

        # [2] and it must equal what SPARSE computes -- a second, independent
        #     reference, so a plausible-but-wrong value is still caught
        sp = nums(run("option sparse\n" + PZ + ctl, "c_%s" % name), pat)
        check("KLU: %s after pz == SPARSE after pz" % name, close(after, sp),
              "%d pts" % len(sp) if close(after, sp) else "klu=%d sparse=%d" % (len(after), len(sp)))

        # [3] control: SPARSE was never affected and must not move
        spa = nums(run("option sparse\n" + ctl, "d_%s" % name), pat)
        check("SPARSE: %s after pz == %s alone (control)" % (name, name), close(spa, sp),
              "unchanged" if close(spa, sp) else "moved")

    # [4] repeat the sequence: the binding must survive more than one rebuild
    a = nums(run("option klu\nac dec 3 1e6 1e8\nprint vdb(mid)", "e"), CASES[0][2])
    b = nums(run("option klu\n" + PZ + PZ + "ac dec 3 1e6 1e8\nprint vdb(mid)", "f"), CASES[0][2])
    check("KLU: ac after TWO pz runs still correct", close(a, b),
          "%d pts" % len(a) if close(a, b) else "1pz=%d 2pz=%d" % (len(a), len(b)))

    # [5] THE check that discriminates. Everything above passes on the pre-fix
    #     binary; only a sanitizer sees the use-after-free itself.
    asan = os.environ.get("NGSPICE_ASAN")
    if asan and os.path.exists(asan):
        p = os.path.join(HERE, "_kb_san.cir")
        with open(p, "w") as f:
            f.write(NET + ".control\noption noacct\noption klu\n" + PZ +
                    "ac dec 3 1e6 1e8\nprint vdb(mid)\n.endc\n.end\n")
        env = dict(os.environ, ASAN_OPTIONS="detect_leaks=0")
        r = subprocess.run([asan, "-b", os.path.basename(p)], cwd=HERE, env=env,
                           capture_output=True, text=True, timeout=300, errors="replace")
        out = r.stdout + r.stderr
        bad = re.search(r"(AddressSanitizer: [a-z-]+)", out)
        check("ASan: option klu ; pz ; ac is memory-clean", not bad,
              bad.group(1) if bad else "no sanitizer report")
    else:
        print("  SKIP  ASan check (set NGSPICE_ASAN to an ASan build) -- "
              "this is the ONLY check that fails before the fix")

    for j in os.listdir(HERE):
        if j.startswith("_kb_"):
            os.remove(os.path.join(HERE, j))
    print(f"\n{'ALL PASS' if passed == checks else 'FAILURES'}: {passed}/{checks} passed")
    sys.exit(0 if passed == checks else 1)


main()
